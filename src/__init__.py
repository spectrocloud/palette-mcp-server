from . import server


def main():
    """Main entry point for the package."""
    # MCP servers use stdio transport, not HTTP ports
    server.mcp.run(transport='stdio')


# Optionally expose other important items at package level
__all__ = ["main", "server"]