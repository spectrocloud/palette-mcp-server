## MCP Servers

Read the instructions below to understand how to use the different MCP servers.

### Palette

The Palette MCP server is a tool that you can use to interact with the Palette platform and its API. The MCP server is active in a container and is accessible via the MCP protocol. A few things to keep in mind:

- When you use the kubeconfig function, `getKubeconfig`, it will download the kubeconfig to the container at `/tmp/kubeconfig` and mapped to a local directory on your machine located at `/Users/demo/projects/mcp-kubeconfig`. Remember to use the file in the local filesystem path, not the container path. Otherwise when you try to use `kubectl` you will get an error. Set the KUBECONFIG environment variable to the local filesystem path or use the `kubectl` command with the `--kubeconfig` flag, but ensure the path is correct and the one in the local filesystem path.
