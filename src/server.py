from typing import Any
import os, logging, signal, sys, atexit
from fastmcp import FastMCP, Context
from context import MCPSessionContext
from helpers import cleanup_temp_files, create_signal_handler
from tools import getClusters, getActiveClusters, getClusterDetailsByUID, deleteClusterByUID, getAdminKubeconfig, getKubeconfig, getPodsInCluster, analyzeCluster, prepareUnhealthyClusterNotificationMessage, sendSlackNotificationForUnhealthyCluster


logger = logging.getLogger('palette_mcp_server')
logger.info("Starting Palette MCP Server")
 


palette_host = os.environ.get('SPECTROCLOUD_HOST')
palette_apikey = os.environ.get('SPECTROCLOUD_APIKEY')
default_project_id = os.environ.get('SPECTROCLOUD_DEFAULT_PROJECT_ID')
allow_dangerous_actions = os.environ.get('ALLOW_DANGEROUS_ACTIONS') == '1'

if allow_dangerous_actions:
    logger.info("⚠️ ALLOW_DANGEROUS_ACTIONS environment variable enabled. This allows dangerous actions to be performed.")


if not palette_host:
    logger.info("SPECTROCLOUD_HOST environment variable is not set. Using default value: api.spectrocloud.com")
    palette_host = "api.spectrocloud.com"

if not palette_apikey:
    logger.error("SPECTROCLOUD_APIKEY environment variable is required but not set. Please set the SPECTROCLOUD_APIKEY environment variable for tracing.")
    exit(1)


 
 
phoenix_endpoint = os.environ.get('PHOENIX_COLLECTOR_ENDPOINT')
if not phoenix_endpoint:
    print("Phoenix collector endpoint is not set. Please set the PHOENIX_COLLECTOR_ENDPOINT environment variable for tracing.")
else:
    from phoenix.otel import register
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    tracer_provider = register(
        project_name="palette-mcp-server",
        endpoint=phoenix_endpoint,
        set_global_tracer_provider=True
    )
    tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(phoenix_endpoint)))

  
mcp = FastMCP("Palette MCP Server")

# Create and store our custom MCP session context
mcp.session_context = MCPSessionContext(
    host=palette_host,
    apikey=palette_apikey,
    default_project_id=default_project_id,
    allow_dangerous_actions=allow_dangerous_actions
)

# # Register tools here
TOOLS = [
    getClusters,
    getActiveClusters,
    getClusterDetailsByUID,

    getAdminKubeconfig,
    getKubeconfig,
    getPodsInCluster,
    analyzeCluster,
    prepareUnhealthyClusterNotificationMessage,
    sendSlackNotificationForUnhealthyCluster
]

DANGEROUS_TOOLS = [
    deleteClusterByUID,
]

# Register all tools
tools_to_register = TOOLS
if allow_dangerous_actions:
    tools_to_register = TOOLS + DANGEROUS_TOOLS

for tool in tools_to_register:
    mcp.tool()(tool)

if __name__ == "__main__":
    # Register cleanup function to run on normal exit
    atexit.register(cleanup_temp_files)
    signal_handler = create_signal_handler(logger)
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Container termination
    
    try:
        # Initialize and run the server
        logger.info("Server running with stdio transport")
        mcp.run(transport='stdio')
    except KeyboardInterrupt:
        # This shouldn't be reached due to signal handler, but just in case
        signal_handler(signal.SIGINT, None)