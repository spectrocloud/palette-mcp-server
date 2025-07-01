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
- A pre-existing folder to store the kubeconfig file on the host machine. This is optional but improves the experience when retrieving Kubeconfig files. The configuations below assumes the host machine folder is `/tmp/kubeconfig` but you can use any folder you prefer. For example, you can use the `~/.kube` folder.

> [!IMPORTANT]
> If you are using Docker, you must enable resource sharing for the container. This is required to allow the container to access the host machine's kubeconfig file. Refer to [Virtual file shares](https://docs.docker.com/desktop/settings-and-maintenance/settings/#virtual-file-shares) for steps on how to setup.

```json
        "-v",
        "~/.kube/:/tmp/kubeconfig",
```

### Cursor

To use the Palette MCP server in Cursor, you can add the following to your `$HOME/.cursor/mcp.json` file. If you don't want to use Docker, swap out the `docker` command for `podman` in the `command` field.

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
        "-v",
        "/tmp/kubeconfig:/tmp/kubeconfig",
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
        "-v",
        "/tmp/kubeconfig:/tmp/kubeconfig",
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

Open up the application you configured to use the Palette MCP server. Issue the following command to ensure the container is active:

```shell
docker ps | grep palette-mcp
```

For example, if you are using Cursor, an output similar to the following should be displayed:

```shell
de70907c4b6f   public.ecr.aws/palette-ai/palette-mcp-server:dev   "uv run python src/s…"   2 minutes ago   Up 2 minutes             palette-mcp-cursor
```

Next, issue a prompt that uses the Palette MCP server tools. For example, you can issue the following command:

```shell
Can you use help me identify how many active clusters I have in Palette?
```

Some applications may require your approval to use the Palette MCP server tools.

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
