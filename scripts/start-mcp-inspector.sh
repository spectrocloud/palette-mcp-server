#!/bin/bash
# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0


# Palette MCP Server Inspector Startup Script
# This script starts the MCP Inspector with the correct configuration for the Palette MCP server
# 
# Usage: Run this script from the palette-mcp-server directory
#   cd /path/to/palette-mcp-server
#   ./start-mcp-inspector.sh


COMMAND="uv"
ARGS=("run" "python" "src/server.py")

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

# Check if KAPA_API_KEY is set
KAPA_API_KEY_ENABLED=false
if [ -n "${KAPA_API_KEY}" ]; then
    KAPA_API_KEY_ENABLED=true
fi
echo "🔧 Setting environment variables..."


# Set environment variables
export DANGEROUSLY_OMIT_AUTH="true"

# Set default for ALLOW_DANGEROUS_ACTIONS if not set
if [ -z "${ALLOW_DANGEROUS_ACTIONS}" ]; then
    export ALLOW_DANGEROUS_ACTIONS="0"
fi

echo "🔍 Starting MCP Inspector..."
echo "   Command: ${COMMAND} ${ARGS[*]}"
echo "   Project ID: ${SPECTROCLOUD_DEFAULT_PROJECT_ID}"
echo "   Phoenix Endpoint: ${PHOENIX_COLLECTOR_ENDPOINT}"
echo "   Auth Disabled: ${DANGEROUSLY_OMIT_AUTH}"
echo "   Dangerous Actions: ${ALLOW_DANGEROUS_ACTIONS}"
echo "   Auto Generate MCP Tools: ${AUTO_GENERATE_MCP_TOOLS}"
echo "   Kapa API Key Enabled: ${KAPA_API_KEY_ENABLED}" 
echo ""
echo "📖 Inspector will be available at: http://localhost:6274"
echo "🛑 Press Ctrl+C to stop the inspector"
echo ""

# Start the MCP Inspector
exec npx @modelcontextprotocol/inspector \
    -e "SPECTROCLOUD_PROJECT_ID=${SPECTROCLOUD_DEFAULT_PROJECT_ID}" \
    -e "SPECTROCLOUD_APIKEY=${SPECTROCLOUD_APIKEY}" \
    -e "PHOENIX_COLLECTOR_ENDPOINT=${PHOENIX_COLLECTOR_ENDPOINT}" \
    -e "ALLOW_DANGEROUS_ACTIONS=${ALLOW_DANGEROUS_ACTIONS}" \
    -e "AUTO_GENERATE_MCP_TOOLS=${AUTO_GENERATE_MCP_TOOLS}" \
    -e "KAPA_API_KEY=${KAPA_API_KEY}" \
    -- uv run python src/server.py 