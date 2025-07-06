# Palette MCP Server

The Palette MCP server is tool for interacting with Palette through the Model Context Protocol (MCP).

## Available Tools

The Palette MCP server provides the following tools. Checkout the [Usage](#usage) section to learn more about how to use the tools. Some tools require explicit enablement before they can be used. Refer to the [Dangerous Actions](#dangerous-actions) section for more information.

| Tool                     | Description                          | Dangerous Action |
| ------------------------ | ------------------------------------ | ---------------- |
| `getClusters`            | Get a list of clusters.              | No               |
| `getActiveClusters`      | Get a list of active clusters.       | No               |
| `getClusterDetailsByUID` | Get a cluster by UID.                | No               |
| `deleteClusterByUID`     | Delete a cluster by UID.             | Yes              |
| `getAdminKubeconfig`     | Get an Admin kubeconfig for cluster. | No               |
| `getKubeconfig`          | Get a kubeconfig for the cluster.    | No               |

## Get Started

To get started with the Palette MCP server, you can use the container image we provide. Review the following steps to get started.

### Prerequisites

The following items are required to use the Palette MCP server:

- A Palette account.
- A Palette API key. Check out the [Create API Key](https://docs.spectrocloud.com/user-management/authentication/api-key/create-api-key/) guide for additional guidance.
- [Docker](https://docs.docker.com/get-docker/) or [Podman](https://podman.io/getting-started/installation) installed on your machine.
- Network access to the Palette API from your machine.
- A pre-existing folder to store kubeconfig file retrieved from Palette. This is optional but improves the experience when retrieving Kubeconfig files.

### Setup

Start by creating a `.env-mcp` file in your home directory under the `.palette` folder. If this folder does not exist, create it.

```bash
mkdir -p ~/.palette
touch ~/.palette/.env-mcp
```

The `.env-mcp` file should contain the following variables.

```bash
SPECTROCLOUD_DEFAULT_PROJECT_ID=your-project-id
SPECTROCLOUD_APIKEY=your-api-key
SPECTROCLOUD_HOST=api.spectrocloud.com
ALLOW_DANGEROUS_ACTIONS=0
```

Next, create a folder to store the kubeconfig file on the host machine. This is optional but improves the experience when retrieving Kubeconfig files. The configuations below assumes the host machine folder is `/home/demouser/kubeconfig` but you can use any folder you prefer. In the following command replace the `/home/demouser/kubeconfig` with the path to your kubeconfig folder.

```bash
mkdir -p /home/REPLACEME/kubeconfig
```

Next, use the Palette MCP server, add the following MCP configuration to your application. If you don't want to use Docker, swap out the `docker` command for `podman` in the `command` field. Update the file paths to match your environment. Specify full paths to the kubeconfig folder and the `.env-mcp` file. Be aware that ENV variables such as `$HOME` will not be interpolated in most tools.

> [!WARNING]
> Ensure you use full path specifications for the kubeconfig folder and the `.env-mcp` file. Do not use relative paths, or `~`, `$HOME`, or other environment variables. Docker requires full paths to be specified for the `--mount` flag. And most tools do not support environment variable interpolation for MCP configurations.

```json
  "mcpServers": {
    "palette": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--mount",
        "type=bind,source=/FILE_PATH_REPLACE_ME/kubeconfig,target=/tmp/kubeconfig",
        "--env-file",
        "/FILE_PATH_REPLACE_ME/.env-mcp",
        "public.ecr.aws/palette-ai/palette-mcp-server:dev"
      ]
    }
  }
```

</details>

<details><summary>💾 Without Env File</summary><br>

If you don't want to use the `.env` file, you can add the environment variables directly to the MCP configuration.
However, this is not recommended as it may create a scecario where this could get committed to a repository.

```json
{
  "mcpServers": {
    "palette": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
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

</details>

### Validate

Open up the application you configured to use the Palette MCP server. Issue the following command to ensure the container is active:

```shell
docker ps | grep palette-ai/palette-mcp-server
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

## Usage

There are various ways to use the Palette MCP server tools. The primary way to use the tools is to enable integration with a Large Language Model (LLM) to access the tools. You can enable integration with a LLM by adding the Palette MCP server to the MCP configuration of your application.

### Dangerous Actions

To prevent accidental use of dangerous actions, the Palette MCP server requires you to set the `ALLOW_DANGEROUS_ACTIONS` environment variable to `1`. This is a precautionary measure to prevent accidental use of dangerous actions. Review the [Tools](#available-tools) section to understand which tools are dangerous and require approval.

### Accessing Kubeconfig Files

The Palette MCP server provides tools to access kubeconfig files for clusters. You can access the kubeconfig files by mounting a local folder to the container. In the container, all kubeconfig files are stored in the `/tmp/kubeconfig` folder. If you use the tool calls `getAdminKubeconfig` or `getKubeconfig`, the kubeconfig file will be stored in the `/tmp/kubeconfig` folder. The filename will have the cluster's UID as the name, for example, `68669fcfee517a7f9a91a9e5.kubeconfig`.

Once you have the kubeconfig file locally, assuming your application with an LLM has access to your local filesystem and a shell environment, you can have the application use the kubeconfig file to access the cluster. For example, if you are using Cursor, you can ask it to use the kubeconfig file to with the `kubectl` command to access the cluster.

### Accessing Cluster Information

The Palette MCP server provides tools to access cluster information. You can access the cluster information by using the `getClusters` or `getActiveClusters` tools. These tools will return a list of clusters.

### Accessing Cluster Details

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
