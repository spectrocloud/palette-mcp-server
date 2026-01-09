# Overview

This is a repository that contains the code for the Palette MCP server. The Palette MCP server is a tool for interacting with Palette through the Model Context Protocol (MCP). The MCP server is designed to be deployed and ran as a container. UV is used to manage the Python dependencies and start the server.

## Repository Structure

- `src/`: Contains the Python code for the Palette MCP server.
- `scripts/`: Contains internal scripts for development and debugging.
- `public/`: Contains public assets for the Palette MCP server.
- `tmp/`: Contains temporary files that developers use and can store without worrying about committing to the repository.

## Development

- Use Taskfile for quick and pre-established tasks.

## General Guidelines

- Comments should be complete sentences and end with a period.
- Review the `pyproject.toml` file to understand what dependencies are installed and what versions are used.
- If you need to update a dependency, update the `pyproject.toml` file and run the `uv sync` command to update the `uv.lock` file. Also use the bulwark_scan_project tool to scan the project for compromised packages.
- DO NOT UPDATE THE `uv.lock` file manually. It is automatically updated by the `uv sync` command.
- DO NOT UPDATE DEPENDENCIES UNLESS EXPLICITLY REQUESTED.
- DO NOT CREATE MANUAL GIT TAGS. They are automatically created by CI/CD release workflow, thanks to Goreleaser.

## Commit Messages and Pull Requests

- Follow the [Chris Beams](https://chris.beams.io/posts/git-commit/) style for commit messages.
- Use the angular commit message format. Such as: `fix: <description>`, `feat: <description>`, `refactor: <description>`, `test: <description>`, `docs: <description>`, `chore: <description>`.

- Every pull request should answer:
  - What changed?
  - Why?
  - Breaking changes?
