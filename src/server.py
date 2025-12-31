from typing import Any
import os, logging, signal, sys, atexit, operator
import httpx
from fastmcp import FastMCP, Context
from fastmcp.server.openapi import RouteMap, MCPType
from fastmcp.utilities.logging import get_logger
from context import MCPSessionContext
from helpers import cleanup_temp_files, create_signal_handler
from tools import getClusters, getClusterProfiles, getClusterProfileByUID, getActiveClusters, getClusterDetailsByUID, deleteClusterByUID, deleteClusterProfileByUID, getAdminKubeconfig, getKubeconfig, getPodsInCluster, analyzeCluster
from openapi import load_openapi_spec, generate_mcp_names

# Use FastMCP's logging utility for server-side logging
logger = get_logger('palette_mcp_server')
version = os.environ.get('VERSION', 'unknown')
logger.info(f"Starting Palette MCP Server {version}")

 
palette_host = os.environ.get('SPECTROCLOUD_HOST')
palette_apikey = os.environ.get('SPECTROCLOUD_APIKEY')
default_project_id = os.environ.get('SPECTROCLOUD_DEFAULT_PROJECT_ID') or ''
allow_dangerous_actions = os.environ.get('ALLOW_DANGEROUS_ACTIONS') == '1'
kapa_apikey = os.environ.get('KAPA_API_KEY') or ''
all_palette_apis = os.environ.get('AUTO_GENERATE_MCP_TOOLS') == '1'

if allow_dangerous_actions:
    logger.info("⚠️ ALLOW_DANGEROUS_ACTIONS environment variable enabled. This allows dangerous actions to be performed.")

if not palette_host:
    logger.info("SPECTROCLOUD_HOST environment variable is not set. Using default value: api.spectrocloud.com")
    palette_host = "api.spectrocloud.com"

if not palette_apikey:
    logger.error("SPECTROCLOUD_APIKEY environment variable is required but not set. Please set the SPECTROCLOUD_APIKEY environment variable for tracing.")
    exit(1)
    
if kapa_apikey:
    logger.info("KAPA_API_KEY environment variable is set. Enabling Palette MCP Proxy Server.")


phoenix_endpoint = os.environ.get('PHOENIX_COLLECTOR_ENDPOINT')
if not phoenix_endpoint:
    logger.info("Phoenix collector endpoint is not set. Tracing will be disabled.")
else:
    logger.info(f"Phoenix collector endpoint is set to {phoenix_endpoint}")
    try:
        from phoenix.otel import register
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        tracer_provider = register(
            project_name="palette-mcp-server",
            endpoint=phoenix_endpoint,
            set_global_tracer_provider=True
        )
        tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(phoenix_endpoint)))
        logger.info(f"Phoenix tracing enabled for {phoenix_endpoint}")
    except Exception as e:
        logger.warning(f"Failed to setup Phoenix tracing: {e}. Tracing will be disabled.")
        # Remove the environment variable so helpers.py knows Phoenix is not available
        os.environ.pop('PHOENIX_COLLECTOR_ENDPOINT', None)



# Load the OpenAPI spec
if all_palette_apis:
    openapi_spec = load_openapi_spec('../openapi/openapi.yaml', logger)
    mcp_names = generate_mcp_names(openapi_spec, logger)
    
else:
    openapi_spec = None 
    mcp = FastMCP("Palette MCP Server", version=version)
    # Safe tools (always loaded)
    SAFE_TOOLS = [
        getClusters,
        getClusterProfiles,
        getClusterProfileByUID,
        getActiveClusters,
        getClusterDetailsByUID,
        getAdminKubeconfig,
        getKubeconfig
    ]

    # Dangerous tools (only loaded if dangerous actions are allowed)
    DANGEROUS_TOOLS = [
        deleteClusterByUID,
        deleteClusterProfileByUID
    ]

    TOOLS = sorted(SAFE_TOOLS + (DANGEROUS_TOOLS if allow_dangerous_actions else []), key=operator.attrgetter('__name__'))
    # Register all tools
    for tool in TOOLS:
        mcp.tool()(tool) 

    # Create and store our custom MCP session context
    mcp.session_context = MCPSessionContext(
        host=palette_host,
        apikey=palette_apikey,
        default_project_id=default_project_id,
        allow_dangerous_actions=allow_dangerous_actions
    )

    # =========================================================================
    # MCP Proxy Servers Configuration
    # Add new MCP servers here. Each entry will be mounted as a proxy.
    # =========================================================================
    MCP_PROXY_SERVERS = []

    # Kapa docs search proxy (requires KAPA_API_KEY) - This is an internal Spectro Cloud use case and not applicable to the public's use of the Palette MCP server.
    if kapa_apikey:
        MCP_PROXY_SERVERS.append({
            "prefix": "",
            "name": "Spectro Cloud Docs Search",
            "config": {
                "mcpServers": {
                    "kapa": {
                        "url": "https://spectro-cloud-server.mcp.kapa.ai",
                        "transport": "http",
                        "headers": {
                            "Authorization": f"Bearer {kapa_apikey}",
                        },
                    }
                }
            }
        })

    # Add more MCP proxy servers here (unconditionally or with their own conditions)
    # MCP_PROXY_SERVERS.append({...})

    # Mount all configured MCP proxy servers
    for server_config in MCP_PROXY_SERVERS:
        try:
            proxy = FastMCP.as_proxy(
                server_config["config"],
                name=server_config["name"]
            )
            mcp.mount(server_config["prefix"], proxy)
            logger.info(f"Mounted MCP proxy: {server_config['name']} at prefix '{server_config['prefix']}'")
        except Exception as e:
            logger.warning(f"Failed to mount MCP proxy {server_config['name']}: {e}")

if __name__ == "__main__":
    # Register cleanup function to run on normal exit
    atexit.register(cleanup_temp_files)
    signal_handler = create_signal_handler(logger)
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Container termination
    
    try:
      if all_palette_apis:
        client = httpx.AsyncClient(
            base_url=f"https://{palette_host}",
            headers={"apiKey": palette_apikey, "projectUID": default_project_id},
            timeout=20
        )
        mcp = FastMCP.from_openapi(
          openapi_spec=openapi_spec,
          client=client,
          name="Palette MCP Server",
          timeout=20,
          route_maps=[
              RouteMap(mcp_type=MCPType.TOOL),
          ],
          mcp_names=mcp_names
      )
        logger.info("Server running with stdio transport and auto generated MCP tools")
      else:
        logger.info("Server running with stdio transport")
      # Initialize and run the server
      mcp.run(transport='stdio')
    except KeyboardInterrupt:
        # This shouldn't be reached due to signal handler, but just in case
        signal_handler(signal.SIGINT, None)