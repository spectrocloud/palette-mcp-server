# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import signal
import atexit
from . import server
from .helpers import cleanup_temp_files, create_signal_handler


def main():
    """Main entry point for the package."""
    # Register cleanup function to run on normal exit
    atexit.register(cleanup_temp_files)

    # Create signal handler (without logger, so it uses print statements)
    signal_handler = create_signal_handler()

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Container termination

    try:
        print("🚀 Starting Palette MCP Server...")
        # MCP servers use stdio transport, not HTTP ports
        mcp = server.create_mcp()
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        # This shouldn't be reached due to signal handler, but just in case
        signal_handler(signal.SIGINT, None)


# Optionally expose other important items at package level
__all__ = ["main", "server"]
