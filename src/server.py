# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import atexit
import operator
import os
import signal
from fastmcp import FastMCP, Context
from fastmcp.utilities.logging import get_logger
from context import MCPSessionContext
from helpers import (
    cleanup_temp_files,
    create_signal_handler,
    ensure_otlp_traces_path,
    normalize_phoenix_endpoint_for_container,
)
from tools import (
    gather_or_delete_clusters,
    gather_or_delete_clusterprofiles,
    getKubeconfig,
    search_and_manage_resource_tags,
)

# Use FastMCP's logging utility for server-side logging
logger = get_logger("palette_mcp_server")
version = os.environ.get("VERSION", "unknown")
logger.info(f"Starting Palette MCP Server {version}")


palette_host = os.environ.get("SPECTROCLOUD_HOST")
palette_apikey = os.environ.get("SPECTROCLOUD_APIKEY")
default_project_id = os.environ.get("SPECTROCLOUD_DEFAULT_PROJECT_ID") or ""
allow_dangerous_actions = os.environ.get("ALLOW_DANGEROUS_ACTIONS", "").strip() == "1"
if allow_dangerous_actions:
    logger.info(
        "⚠️ ALLOW_DANGEROUS_ACTIONS environment variable enabled. This allows dangerous actions to be performed."
    )

if not palette_host:
    logger.info(
        "SPECTROCLOUD_HOST environment variable is not set. Using default value: api.spectrocloud.com"
    )
    palette_host = "api.spectrocloud.com"

if not palette_apikey:
    logger.error(
        "SPECTROCLOUD_APIKEY environment variable is required but not set. Please set the SPECTROCLOUD_APIKEY environment variable for tracing."
    )
    exit(1)

phoenix_endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")


if not phoenix_endpoint:
    logger.info("Phoenix collector endpoint is not set. Tracing will be disabled.")
else:
    normalized_phoenix_endpoint = normalize_phoenix_endpoint_for_container(
        phoenix_endpoint
    )
    if normalized_phoenix_endpoint != phoenix_endpoint:
        logger.info(
            "Detected container runtime. Rewriting PHOENIX_COLLECTOR_ENDPOINT to use host.docker.internal."
        )
        phoenix_endpoint = normalized_phoenix_endpoint
        os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = phoenix_endpoint
    phoenix_endpoint = ensure_otlp_traces_path(phoenix_endpoint)
    os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = phoenix_endpoint
    logger.info(f"Phoenix collector endpoint is set to {phoenix_endpoint}")
    try:
        from phoenix.otel import register

        register(
            project_name="palette-mcp-server",
            endpoint=phoenix_endpoint,
            protocol="http/protobuf",
            set_global_tracer_provider=True,
        )
        logger.info(f"Phoenix tracing enabled for {phoenix_endpoint}")
    except Exception as e:
        logger.warning(
            f"Failed to setup Phoenix tracing: {e}. Tracing will be disabled."
        )
        # Remove the environment variable so helpers.py knows Phoenix is not available
        os.environ.pop("PHOENIX_COLLECTOR_ENDPOINT", None)


def create_mcp() -> FastMCP:
    """Construct and return the curated manual-tool MCP server."""
    _mcp = FastMCP("Palette MCP Server", version=version)
    # All tools - dangerous actions are handled internally at runtime via session_ctx.is_dangerous_actions_allowed().
    SAFE_TOOLS = [
        gather_or_delete_clusters,
        gather_or_delete_clusterprofiles,
        getKubeconfig,
        search_and_manage_resource_tags,
    ]

    # Only functions that are considered dangerous by design are loaded here. If an action contains a dangerous method it's not included here.
    # Dangerous methods are handled internally at runtime via session_ctx.is_dangerous_actions_allowed().
    DANGEROUS_TOOLS = []

    TOOLS = sorted(
        SAFE_TOOLS + (DANGEROUS_TOOLS if allow_dangerous_actions else []),
        key=operator.attrgetter("__name__"),
    )
    # Register all tools.
    for tool in TOOLS:
        _mcp.tool()(tool)

    # Create and store our custom MCP session context.
    _mcp.session_context = MCPSessionContext(
        host=palette_host,
        apikey=palette_apikey,
        default_project_id=default_project_id,
        allow_dangerous_actions=allow_dangerous_actions,
    )

    logger.info("Server running with stdio transport")
    return _mcp


if __name__ == "__main__":
    # Register cleanup function to run on normal exit
    atexit.register(cleanup_temp_files)
    signal_handler = create_signal_handler(logger)

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Container termination

    try:
        mcp = create_mcp()
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        # This shouldn't be reached due to signal handler, but just in case
        signal_handler(signal.SIGINT, None)
