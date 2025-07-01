from typing import Any
import os, logging
from fastmcp import FastMCP, Context
from context import PaletteContext
from tools import getClusters, getActiveClusters, getClusterDetailsByUID, deleteClusterByUID, getAdminKubeconfig, getKubeconfig, getPodsInCluster, analyzeCluster, prepareUnhealthyClusterNotificationMessage, sendSlackNotificationForUnhealthyCluster


logger = logging.getLogger('palette_mcp_server')
logger.info("Starting Palette MCP Server")
 


palette_host = os.environ.get('SPECTROCLOUD_HOST')
palette_apikey = os.environ.get('SPECTROCLOUD_APIKEY')
default_project_id = os.environ.get('SPECTROCLOUD_DEFAULT_PROJECT_ID')

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

# Create and store our custom Palette context
mcp.palette_context = PaletteContext(
    host=palette_host,
    apikey=palette_apikey,
    default_project_id=default_project_id
)

# # Register tools here
TOOLS = [
    getClusters,
    getActiveClusters,
    getClusterDetailsByUID,
    deleteClusterByUID,
    getAdminKubeconfig,
    getKubeconfig,
    getPodsInCluster,
    analyzeCluster,
    prepareUnhealthyClusterNotificationMessage,
    sendSlackNotificationForUnhealthyCluster
]

# Register all tools
for tool in TOOLS:
    mcp.tool()(tool)

if __name__ == "__main__":
    # Initialize and run the server
    logger.info("Server running with stdio transport")
    mcp.run(transport='stdio')