from typing import Any
import os, sys, logging
from phoenix.otel import register
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from mcp.server.fastmcp import FastMCP
from tools import getClusters, getActiveClusters, getClusterDetailsByUID, deleteClusterByUID, getAdminKubeconfig, getKubeconfig, getPodsInCluster, analyzeCluster, prepareUnhealthyClusterNotificationMessage, sendSlackNotificationForUnhealthyCluster

# Phoenix tracing configuration
phoenix_endpoint = os.environ.get('PHOENIX_COLLECTOR_ENDPOINT')
if not phoenix_endpoint:
    print("Phoenix collector endpoint is not set. Please set the PHOENIX_COLLECTOR_ENDPOINT environment variable for tracing.")
else:
    tracer_provider = register(
        project_name="palette-mcp-server",
        endpoint=phoenix_endpoint,
        set_global_tracer_provider=True
    )
    tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(phoenix_endpoint)))

logger = logging.getLogger('palette_mcp_server')
logger.info("Starting Palette MCP Server")
mcp = FastMCP("Palette MCP Server")

# Register tools here
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