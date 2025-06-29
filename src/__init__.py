from . import server
import asyncio
import argparse


def main():
    """Main entry point for the package."""
    parser = argparse.ArgumentParser(description='Palette MCP Server')
    parser.add_argument('--port', type=int, default=4128, help='Port to run the server on')
    args = parser.parse_args()
    asyncio.run(server.main(port=args.port))


# Optionally expose other important items at package level
__all__ = ["main", "server"]