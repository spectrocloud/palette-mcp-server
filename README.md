# Palette MCP Server

The Palette MCP server is tool for interacting with Palette through the Model Context Protocol (MCP).

## Get Started

To get started with the Palette MCP server, you can use the container image we provide. Review the following steps to get started.

### Prerequisites

The following items are required to use the Palette MCP server:

- A Palette account.
- A Palette API key. Check out the [Create API Key](https://docs.spectrocloud.com/user-management/authentication/api-key/create-api-key/) guide for additional guidance.
- [Docker](https://docs.docker.com/get-docker/) or [Podman](https://podman.io/getting-started/installation) installed on your machine.
- Network access to the Palette API from your machine.

### Cursor

To use the Palette MCP server in Cursor, you can add the following to your `.cursor/mcp.json` file. If you don't want to use Docker, swap out the `docker` command for `podman` in the `command` field.

```json
{
  "mcpServers": {
    "palette": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "--name",
        "palette-mcp-cursors",
        "-i",
        "-e",
        "SPECTROCLOUD_HOST=api.spectrocloud.com",
        "-e",
        "SPECTROCLOUD_APIKEY=your-api-key",
        "-e",
        "SPECTROCLOUD_DEFAULT_PROJECT_ID=your-project-id",
        "-e",
        "ALLOW_DANGEROUS_ACTIONS=0",
        "public.ecr.aws/palette-ai/palette-mcp-server:dev"
      ]
    }
  }
}
```

### Claude Desktop

To use the Palette MCP server in Claude Desktop, you can add the following to your `claude_desktop_config.json`. Open up Claude Desktop and click on the `Settings`. Next, click on `Advanced` and then `MCP Servers`. Add the following to the `mcpServers` object:

```json
{
  "mcpServers": {
    "palette": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "--name",
        "palette-mcp-claude",
        "-i",
        "-e",
        "SPECTROCLOUD_HOST=api.spectrocloud.com",
        "-e",
        "SPECTROCLOUD_APIKEY=your-api-key",
        "-e",
        "SPECTROCLOUD_DEFAULT_PROJECT_ID=your-project-id",
        "-e",
        "ALLOW_DANGEROUS_ACTIONS=0",
        "public.ecr.aws/palette-ai/palette-mcp-server:dev"
      ]
    }
  }
}
```

### Validate

You can validate that the MCP server is working by issuing a prompt that uses the Palette MCP server tools. For example, you can issue the following prompt:

```shell
Can you use the Palette MCP server to tell me how many clusters I have that are active?
```

## Development

Start by creating a `.env` file in the root of the project. This file should contain the following variables:

```bash
SPECTROCLOUD_DEFAULT_PROJECT_ID=your-project-id
SPECTROCLOUD_APIKEY=your-api-key
SPECTROCLOUD_HOST=api.spectrocloud.com
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
ALLOW_DANGEROUS_ACTIONS=0
```

Next, issue the command `uv sync --frozen` to install the required Python dependencies.

If you are using a self-hosted Palette instance, you will need to set the `SPECTROCLOUD_HOST` variable to the URL of your Palette instance.

To start the local development server, issue the following command in the root of the project:

```bash
task start-debug
```

This will start the a container for the Phoenix collector and the Palette MCP server. Use the Phoenix AI to review traces to help debug issues and verify expected behavior. Phoenix AI will be available at [http://localhost:6006](http://localhost:6006).

To stop the development server, press `Ctrl+C` in the terminal where the server is active. The server will gracefully shutdown and clean up any temporary files.
