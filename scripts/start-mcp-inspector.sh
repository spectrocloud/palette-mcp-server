#!/bin/bash

# Palette MCP Server Inspector Startup Script
# This script starts the MCP Inspector with the correct configuration for the Palette MCP server
# 
# Usage: Run this script from the palette-mcp-server directory
#   cd /path/to/palette-mcp-server
#   ./start-mcp-inspector.sh


COMMAND="uv"
ARGS="run python src/server.py"

echo "🚀 Starting Palette MCP Server Inspector..."
echo "📁 Using current directory: $(pwd)"

# Check if we're in the right directory (should have src folder and server.py)
if [ ! -d "src" ]; then
    echo "❌ Error: This doesn't appear to be the Palette MCP server directory"
    echo "   Expected to find 'src' directory in: $(pwd)"
    echo "   Please run this script from the palette-mcp-server directory"
    exit 1
fi

if [ ! -f "src/server.py" ]; then
    echo "❌ Error: src/server.py not found"
    echo "   Please run this script from the palette-mcp-server directory"
    exit 1
fi

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ Error: 'uv' command not found"
    echo "   Please install uv first: https://docs.astral.sh/uv/"
    exit 1
fi

# Check if npx is installed
if ! command -v npx &> /dev/null; then
    echo "❌ Error: 'npx' command not found"
    echo "   Please install Node.js first: https://nodejs.org/"
    exit 1
fi

echo "🔧 Setting environment variables..."

# Load environment variables from .env file
if [ -f ".env" ]; then
    source .env
fi

# Set environment variables
export DANGEROUSLY_OMIT_AUTH="true"

echo "🔍 Starting MCP Inspector..."
echo "   Command: ${COMMAND} ${ARGS}"
echo "   Project ID: ${SPECTROCLOUD_PROJECT_ID}"
echo "   Phoenix Endpoint: ${PHOENIX_COLLECTOR_ENDPOINT}"
echo "   Auth Disabled: ${DANGEROUSLY_OMIT_AUTH}"
echo ""
echo "📖 Inspector will be available at: http://localhost:6274"
echo "🛑 Press Ctrl+C to stop the inspector"
echo ""

# Start the MCP Inspector
npx @modelcontextprotocol/inspector \
    -e "SPECTROCLOUD_PROJECT_ID=${SPECTROCLOUD_PROJECT_ID}" \
    -e "SPECTROCLOUD_APIKEY=${SPECTROCLOUD_APIKEY}" \
    -e "PHOENIX_COLLECTOR_ENDPOINT=${PHOENIX_COLLECTOR_ENDPOINT}" \
    "${COMMAND}" "${ARGS}" 