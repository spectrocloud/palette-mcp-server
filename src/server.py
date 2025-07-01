from typing import Any
import os, logging, signal, sys, atexit, operator
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

mcp = FastMCP("Palette MCP Server")


# Safe tools (always loaded)
SAFE_TOOLS = [
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

# Dangerous tools (only loaded if dangerous actions are allowed)
DANGEROUS_TOOLS = [
    deleteClusterByUID
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