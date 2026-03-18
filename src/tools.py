# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import json
import httpx
from typing import Dict, TypedDict, Any, List, Optional, Union
from pydantic import BaseModel
from datetime import datetime
from fastmcp import FastMCP, Context
from context import MCPSessionContext
from helpers import (
    write_kubeconfig_to_temp,
    create_span,
    safe_set_tool,
    safe_set_input,
    safe_set_output,
    safe_set_status,
)


def get_session_context(ctx: Context) -> MCPSessionContext:
    """Helper function to get our custom MCP session context from FastMCP context"""
    return ctx.fastmcp.session_context


"""
  This file contains the tools that are used by the Palette MCP server.
  The tools are used to get information about the clusters that are managed by Palette.
  The tools are also used to get information about the Palette platform itself.

"""


class Cluster(BaseModel):
    name: str
    uid: Optional[str] = None
    state: Optional[str] = None
    cloud_type: Optional[str] = None
    location: Optional[str] = None


class OutputModel(BaseModel):
    clusters: List[Cluster]
    summary: str


class MCPResult(TypedDict):
    """Type definition for MCP tool results"""

    content: list[dict]
    isError: bool


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects."""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


"""
  This function masks sensitive data by only showing the last 8 characters.
  It is used to mask the API key and project ID in the trace.
"""


def mask_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Masks sensitive data by only showing the last 8 characters."""
    masked = data.copy()
    if "api_key" in masked:
        api_key = masked["api_key"]
        masked["api_key"] = (
            f"{'*' * (len(api_key) - 8)}{api_key[-8:]}" if len(api_key) > 8 else api_key
        )
    return masked


def safe_set_span_status(span, status_code: str, description: str = None):
    """Helper to safely set span status without importing trace when Phoenix is not configured"""
    if span is None:
        return
    try:
        from opentelemetry import trace

        if status_code == "OK":
            safe_set_status(span, trace.Status(trace.StatusCode.OK))
        elif status_code == "ERROR":
            safe_set_status(
                span, trace.Status(trace.StatusCode.ERROR, description or "")
            )
    except ImportError:
        # OpenTelemetry not available, skip
        pass


async def _list_clusters(
    ctx: Context, project_id: Optional[str] = None, api_key: Optional[str] = None
) -> MCPResult:
    """Internal helper: Queries the Palette API to find all clusters in a given project, regardless of state."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)

    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()

    if not api_key:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: No api_key provided and no default API key configured",
                }
            ],
            "isError": True,
        }

    with create_span("_list_clusters") as span:
        safe_set_tool(
            span,
            name="_list_clusters",
            description="Queries Palette API for all clusters in a project, returning cluster metadata with values.yaml removed",
            parameters={
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)",
                },
                "api_key": {
                    "type": "string",
                    "description": "The API key for the Palette API (optional, uses default if not provided)",
                },
            },
        )

        safe_set_input(
            span,
            mask_sensitive_data(
                {
                    "api_key": api_key,
                }
            ),
        )

        try:
            headers = {"Accept": "application/json", "apiKey": api_key}

            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers["ProjectUid"] = project_id

            all_clusters = []
            continue_token = None

            async with httpx.AsyncClient(
                base_url=f"https://{palette_host}", timeout=30
            ) as client:
                while True:
                    if continue_token:
                        headers["Continue"] = continue_token

                    res = await client.get("/v1/spectroclusters/", headers=headers)

                    if res.status_code == 422:
                        raise Exception(
                            f"Validation error (422): The request was well-formed but contains semantic errors. Details: {res.json()}"
                        )

                    if res.status_code == 429:
                        raise Exception(
                            f"Rate limit error (429): Too many requests. Please wait before retrying. Response: {res.text}"
                        )

                    if res.status_code >= 400:
                        raise Exception(
                            f"API request failed with status {res.status_code}: {res.text}"
                        )

                    json_data = res.json()
                    items = json_data.get("items") or []
                    all_clusters.extend(items)

                    continue_token = json_data.get("listmeta", {}).get("continue")
                    if not continue_token:
                        break

            # Clean up values.yaml from cluster profile templates
            for cluster in all_clusters:
                if "spec" in cluster:
                    spec = cluster["spec"]
                    if "clusterProfileTemplates" in spec:
                        for template in spec["clusterProfileTemplates"]:
                            if "packs" in template:
                                for pack in template["packs"]:
                                    if "values" in pack:
                                        del pack["values"]

            result = {"clusters": {"items": all_clusters}}
            safe_set_output(span, result)
            safe_set_span_status(span, "OK")

            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False,
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))

            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True,
            }


async def _list_active_clusters(
    ctx: Context, project_id: Optional[str] = None, api_key: Optional[str] = None
) -> MCPResult:
    """Internal helper: Queries the Palette API to find all active (running) clusters in a given project."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)

    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()

    if not api_key:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: No api_key provided and no default API key configured",
                }
            ],
            "isError": True,
        }
    with create_span("_list_active_clusters") as span:
        safe_set_tool(
            span,
            name="_list_active_clusters",
            description="Queries Palette API for active clusters in a project, returning cluster metadata",
            parameters={
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)",
                },
                "api_key": {
                    "type": "string",
                    "description": "The API key for the Palette API (optional, uses default if not provided)",
                },
            },
        )

        safe_set_input(span, mask_sensitive_data({"api_key": api_key}))

        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "apiKey": api_key,
            }

            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers["ProjectUid"] = project_id

            payload = {
                "filter": {
                    "conjunction": "and",
                    "filterGroups": [
                        {
                            "conjunction": "and",
                            "filters": [
                                {
                                    "property": "clusterState",
                                    "type": "string",
                                    "condition": {
                                        "string": {
                                            "operator": "eq",
                                            "negation": False,
                                            "match": {
                                                "conjunction": "or",
                                                "values": ["Running"],
                                            },
                                            "ignoreCase": False,
                                        }
                                    },
                                }
                            ],
                        },
                        {
                            "conjunction": "and",
                            "filters": [
                                {
                                    "property": "environment",
                                    "type": "string",
                                    "condition": {
                                        "string": {
                                            "operator": "eq",
                                            "negation": True,
                                            "match": {
                                                "conjunction": "or",
                                                "values": ["nested"],
                                            },
                                            "ignoreCase": False,
                                        }
                                    },
                                },
                                {
                                    "property": "isDeleted",
                                    "type": "bool",
                                    "condition": {"bool": {"value": False}},
                                },
                            ],
                        },
                    ],
                },
                "sort": [{"field": "clusterName", "order": "asc"}],
            }

            active_clusters = []
            continue_token = None

            async with httpx.AsyncClient(
                base_url=f"https://{palette_host}", timeout=30
            ) as client:
                while True:
                    if continue_token:
                        headers["Continue"] = continue_token

                    res = await client.post(
                        "/v1/dashboard/spectroclusters/search",
                        headers=headers,
                        json=payload,
                    )

                    if res.status_code == 422:
                        raise Exception(
                            f"Validation error (422): The request was well-formed but contains semantic errors. Details: {res.json()}"
                        )

                    if res.status_code == 429:
                        raise Exception(
                            f"Rate limit error (429): Too many requests. Please wait before retrying. Response: {res.text}"
                        )

                    if res.status_code >= 400:
                        raise Exception(
                            f"API request failed with status {res.status_code}: {res.text}"
                        )

                    json_data = res.json()
                    active_clusters.extend(json_data.get("items", []))

                    continue_token = json_data.get("listmeta", {}).get("continue")
                    if not continue_token:
                        break

            result = {"clusters": {"items": active_clusters}}
            safe_set_output(span, result)
            safe_set_span_status(span, "OK")

            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False,
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))

            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True,
            }


async def _get_cluster_by_uid(
    ctx: Context,
    cluster_uid: str,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> MCPResult:
    """Internal helper: Queries the Palette API to find detailed information about a specific cluster."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)

    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()

    if not api_key:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: No api_key provided and no default API key configured",
                }
            ],
            "isError": True,
        }

    with create_span("_get_cluster_by_uid") as span:
        safe_set_tool(
            span,
            name="_get_cluster_by_uid",
            description="Queries Palette API for detailed information about a specific cluster",
            parameters={
                "cluster_uid": {
                    "type": "string",
                    "description": "The UID of the cluster to query",
                },
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)",
                },
                "api_key": {
                    "type": "string",
                    "description": "The API key for the Palette API (optional, uses default if not provided)",
                },
            },
        )

        safe_set_input(span, mask_sensitive_data({"api_key": api_key}))

        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "apiKey": api_key,
            }

            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers["ProjectUid"] = project_id

            url = f"/v1/spectroclusters/{cluster_uid}"
            params = {
                "includeTags": "true",
                "resolvePackValues": "true",
                "includePackMeta": "false",
                "profileType": "<string>",
                "includeNonSpectroLabels": "false",
            }

            async with httpx.AsyncClient(
                base_url=f"https://{palette_host}", timeout=30
            ) as client:
                res = await client.get(url, headers=headers, params=params)

            if res.status_code == 422:
                raise Exception(
                    f"Validation error (422): The request was well-formed but contains semantic errors. Details: {res.json()}"
                )

            if res.status_code == 429:
                raise Exception(
                    f"Rate limit error (429): Too many requests. Please wait before retrying. Response: {res.text}"
                )

            if res.status_code >= 400:
                raise Exception(
                    f"API request failed with status {res.status_code}: {res.text}"
                )

            result = {"cluster": res.json()}
            safe_set_output(span, result)

            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False,
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))

            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True,
            }


async def _delete_cluster_by_uid(
    ctx: Context,
    cluster_uid: str,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
    force_delete: bool = False,
) -> MCPResult:
    """Internal helper: Deletes a specific cluster using its UID."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)

    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()

    if not api_key:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: No api_key provided and no default API key configured",
                }
            ],
            "isError": True,
        }

    with create_span("_delete_cluster_by_uid") as span:
        safe_set_tool(
            span,
            name="_delete_cluster_by_uid",
            description="Deletes a specific cluster from Palette using its UID",
            parameters={
                "cluster_uid": {
                    "type": "string",
                    "description": "The UID of the cluster to delete",
                },
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)",
                },
                "api_key": {
                    "type": "string",
                    "description": "The API key for the Palette API (optional, uses default if not provided)",
                },
                "force_delete": {
                    "type": "boolean",
                    "description": "Whether to force delete the cluster (optional, defaults to false)",
                },
            },
        )

        safe_set_input(
            span,
            mask_sensitive_data(
                {
                    "api_key": api_key,
                    "project_id": project_id,
                    "cluster_uid": cluster_uid,
                    "force_delete": force_delete,
                }
            ),
        )

        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "apiKey": api_key,
            }

            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers["ProjectUid"] = project_id

            url = f"/v1/spectroclusters/{cluster_uid}"
            params = {"forceDelete": str(force_delete).lower()}

            async with httpx.AsyncClient(
                base_url=f"https://{palette_host}", timeout=30
            ) as client:
                res = await client.delete(url, headers=headers, params=params)

            if res.status_code == 422:
                raise Exception(
                    f"Validation error (422): The request was well-formed but contains semantic errors. Details: {res.json()}"
                )

            if res.status_code == 429:
                raise Exception(
                    f"Rate limit error (429): Too many requests. Please wait before retrying. Response: {res.text}"
                )

            if res.status_code >= 400:
                raise Exception(
                    f"API request failed with status {res.status_code}: {res.text}"
                )

            # Handle successful DELETE response (typically 204 No Content)
            if res.status_code == 204 or not res.content:
                result = {
                    "status": "success",
                    "message": f"Cluster {cluster_uid} deleted successfully",
                    "http_status": res.status_code,
                }
            else:
                try:
                    result = {"status": res.json()}
                except Exception:
                    result = {
                        "status": "success",
                        "message": f"Cluster {cluster_uid} deleted successfully",
                        "response": res.text,
                        "http_status": res.status_code,
                    }

            safe_set_output(span, result)
            safe_set_span_status(span, "OK")

            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False,
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))

            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True,
            }


async def gather_or_delete_clusters(
    ctx: Context,
    action: str,
    uid: Optional[str] = None,
    active_only: bool = False,
    force_delete: bool = False,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> MCPResult:
    """Gather information about clusters or delete a cluster in Palette.

    Args:
        action: The operation to perform. Must be one of:
            - "list": Get all clusters in the project (use active_only=True to filter to active clusters only)
            - "get": Get detailed information about a specific cluster (requires uid)
            - "delete": Delete a cluster (requires uid, requires ALLOW_DANGEROUS_ACTIONS=1)
        uid: The UID of the cluster. Required for "get" and "delete" actions.
        active_only: If True and action="list", only return active clusters. Default is False.
        force_delete: If True and action="delete", perform a force delete. Default is False.
        project_id: Optional project ID override.
        api_key: Optional API key override.
    """
    session_ctx = get_session_context(ctx)

    with create_span("gather_or_delete_clusters") as span:
        safe_set_tool(
            span,
            name="gather_or_delete_clusters",
            description="Gather information about clusters or delete a cluster in Palette",
            parameters={
                "action": {
                    "type": "string",
                    "description": "The operation: 'list', 'get', or 'delete'",
                },
                "uid": {
                    "type": "string",
                    "description": "The UID of the cluster (required for get/delete)",
                },
                "active_only": {
                    "type": "boolean",
                    "description": "If True and action='list', only return active clusters",
                },
                "force_delete": {
                    "type": "boolean",
                    "description": "If True and action='delete', perform a force delete",
                },
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project (optional)",
                },
                "api_key": {"type": "string", "description": "The API key (optional)"},
            },
        )

        safe_set_input(
            span,
            {
                "action": action,
                "uid": uid,
                "active_only": active_only,
                "force_delete": force_delete,
            },
        )

        # Validate action - only get, list, delete are allowed.
        if action not in ["list", "get", "delete"]:
            error_msg = f"Error: Invalid action '{action}'. Only 'get', 'list', and 'delete' are allowed actions."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Validate uid requirement for get.
        if action == "get" and not uid:
            error_msg = "Error: The 'get' action requires a cluster UID. Use action='list' first to retrieve all clusters and identify the UID of the cluster you are interested in."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Validate uid requirement for delete.
        if action == "delete" and not uid:
            error_msg = "Error: The 'delete' action requires a cluster UID. Use action='list' to retrieve all clusters and identify the UID of the cluster you want to delete."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Check dangerous action permission for delete.
        if action == "delete" and not session_ctx.is_dangerous_actions_allowed():
            error_msg = "Error: The 'delete' action is not allowed. The ALLOW_DANGEROUS_ACTIONS environment variable must be set to '1' to enable dangerous operations like delete."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Route to appropriate helper.
        if action == "list":
            if active_only:
                result = await _list_active_clusters(ctx, project_id, api_key)
            else:
                result = await _list_clusters(ctx, project_id, api_key)
        elif action == "get":
            result = await _get_cluster_by_uid(ctx, uid, project_id, api_key)
        elif action == "delete":
            result = await _delete_cluster_by_uid(
                ctx, uid, project_id, api_key, force_delete
            )

        if not result.get("isError", False):
            safe_set_span_status(span, "OK")
        else:
            safe_set_span_status(span, "ERROR")

        return result


async def getKubeconfig(
    ctx: Context,
    cluster_uid: str,
    admin_config: bool = False,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> MCPResult:
    """Gets the kubeconfig file for a specific cluster.

    Args:
        cluster_uid: The UID of the cluster to get the kubeconfig for.
        admin_config: If True, retrieves the admin kubeconfig. If False (default), retrieves the regular kubeconfig.
        project_id: Optional project ID override.
        api_key: Optional API key override.
    """
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)

    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()

    if not api_key:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: No api_key provided and no default API key configured",
                }
            ],
            "isError": True,
        }

    with create_span("getKubeconfig") as span:
        safe_set_tool(
            span,
            name="getKubeconfig",
            description="Gets the kubeconfig or admin kubeconfig file for a specific cluster. To use the admin kubeconfig, set admin_config to True.",
            parameters={
                "cluster_uid": {
                    "type": "string",
                    "description": "The UID of the cluster to get the kubeconfig for",
                },
                "admin_config": {
                    "type": "boolean",
                    "description": "If True, retrieves the admin kubeconfig. Default is False.",
                },
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project to query (optional)",
                },
                "api_key": {
                    "type": "string",
                    "description": "The API key for the Palette API (optional)",
                },
            },
        )

        safe_set_input(
            span,
            mask_sensitive_data(
                {
                    "api_key": api_key,
                    "project_id": project_id,
                    "cluster_uid": cluster_uid,
                    "admin_config": admin_config,
                }
            ),
        )

        try:
            headers = {"Accept": "application/octet-stream", "apiKey": api_key}

            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers["ProjectUid"] = project_id

            # Choose endpoint based on admin_config
            if admin_config:
                url = f"/v1/spectroclusters/{cluster_uid}/assets/adminKubeconfig"
            else:
                url = f"/v1/spectroclusters/{cluster_uid}/assets/kubeconfig"

            # Track whether the fetched config is actually an admin config.
            # If the admin endpoint returns 404, fall back to the regular kubeconfig
            # and mark actual_admin_config as False so downstream code reflects the
            # real config type.
            actual_admin_config = admin_config
            async with httpx.AsyncClient(
                base_url=f"https://{palette_host}", timeout=30
            ) as client:
                res = await client.get(url, headers=headers)

                if admin_config and res.status_code == 404:
                    actual_admin_config = False
                    res = await client.get(
                        f"/v1/spectroclusters/{cluster_uid}/assets/kubeconfig",
                        headers=headers,
                        params={"frp": "true"},
                    )

            if res.status_code == 422:
                raise Exception(
                    f"Validation error (422): The request was well-formed but contains semantic errors. Details: {res.json()}"
                )

            if res.status_code == 429:
                raise Exception(
                    f"Rate limit error (429): Too many requests. Please wait before retrying. Response: {res.text}"
                )

            if res.status_code >= 400:
                raise Exception(
                    f"API request failed with status {res.status_code}: {res.text}"
                )

            kubeconfig_content = res.text

            # Write kubeconfig to temp directory with cluster UID
            try:
                kubeconfig_path = write_kubeconfig_to_temp(
                    cluster_uid, kubeconfig_content, is_admin=actual_admin_config
                )
                # Set the kubeconfig path in context
                session_ctx.kubeconfig.set_path(kubeconfig_path)
            except OSError as e:
                print(f"Warning: Failed to write kubeconfig to temp file: {e!s}")
                kubeconfig_path = None

            safe_set_output(
                span,
                {
                    "status": "Kubeconfig retrieved successfully",
                    "admin_config": actual_admin_config,
                },
            )

            config_type = "Admin kubeconfig" if actual_admin_config else "Kubeconfig"
            return {
                "content": [
                    {"type": "text", "text": kubeconfig_content},
                    {
                        "type": "text",
                        "text": (
                            f"\n{config_type} written to: {kubeconfig_path}"
                            if kubeconfig_path
                            else f"\nWarning: Failed to write {config_type.lower()} to temp file"
                        ),
                    },
                ],
                "isError": False,
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))

            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True,
            }


async def _list_cluster_profiles(
    ctx: Context, project_id: Optional[str] = None, api_key: Optional[str] = None
) -> MCPResult:
    """Internal helper: Gets all cluster profiles in a project."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)

    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()

    if not api_key:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: No api_key provided and no default API key configured",
                }
            ],
            "isError": True,
        }

    with create_span("_list_cluster_profiles") as span:
        safe_set_tool(
            span,
            name="_list_cluster_profiles",
            description="Queries Palette API for all cluster profiles in a project, returning profile metadata with pack values removed",
            parameters={
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)",
                },
                "api_key": {
                    "type": "string",
                    "description": "The API key for the Palette API (optional, uses default if not provided)",
                },
            },
        )

        safe_set_input(span, mask_sensitive_data({"api_key": api_key}))

        try:
            headers = {"Accept": "application/json", "apiKey": api_key}

            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers["ProjectUid"] = project_id

            all_profiles = []
            continue_token = None

            async with httpx.AsyncClient(
                base_url=f"https://{palette_host}", timeout=30
            ) as client:
                while True:
                    if continue_token:
                        headers["Continue"] = continue_token

                    res = await client.get("/v1/clusterprofiles/", headers=headers)

                    if res.status_code == 422:
                        raise Exception(
                            f"Validation error (422): The request was well-formed but contains semantic errors. Details: {res.json()}"
                        )

                    if res.status_code == 429:
                        raise Exception(
                            f"Rate limit error (429): Too many requests. Please wait before retrying. Response: {res.text}"
                        )

                    if res.status_code >= 400:
                        raise Exception(
                            f"API request failed with status {res.status_code}: {res.text}"
                        )

                    json_data = res.json()
                    all_profiles.extend(json_data.get("items", []))

                    continue_token = json_data.get("listmeta", {}).get("continue")
                    if not continue_token:
                        break

            # Clean up pack values from cluster profiles
            for profile in all_profiles:
                if "spec" in profile:
                    # Handle published packs
                    if (
                        "published" in profile["spec"]
                        and "packs" in profile["spec"]["published"]
                    ):
                        for pack in profile["spec"]["published"]["packs"]:
                            if "values" in pack:
                                del pack["values"]

                    # Handle draft packs
                    if (
                        "draft" in profile["spec"]
                        and "packs" in profile["spec"]["draft"]
                    ):
                        for pack in profile["spec"]["draft"]["packs"]:
                            if "values" in pack:
                                del pack["values"]

            result = {"clusterProfiles": {"items": all_profiles}}
            safe_set_output(span, result)
            safe_set_span_status(span, "OK")

            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False,
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))

            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True,
            }


async def _get_cluster_profile_by_uid(
    ctx: Context,
    clusterprofile_uid: str,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> MCPResult:
    """Internal helper: Gets a specific cluster profile by its UID. Returns all data including pack values."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)

    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()

    if not api_key:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: No api_key provided and no default API key configured",
                }
            ],
            "isError": True,
        }

    with create_span("_get_cluster_profile_by_uid") as span:
        safe_set_tool(
            span,
            name="_get_cluster_profile_by_uid",
            description="Queries Palette API for a specific cluster profile by UID, returning complete profile data including pack values",
            parameters={
                "clusterprofile_uid": {
                    "type": "string",
                    "description": "The UID of the cluster profile to retrieve",
                },
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)",
                },
                "api_key": {
                    "type": "string",
                    "description": "The API key for the Palette API (optional, uses default if not provided)",
                },
            },
        )

        safe_set_input(
            span,
            mask_sensitive_data(
                {"api_key": api_key, "clusterprofile_uid": clusterprofile_uid}
            ),
        )

        try:
            headers = {"Accept": "application/json", "apiKey": api_key}

            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers["ProjectUid"] = project_id

            url = f"/v1/clusterprofiles/{clusterprofile_uid}"

            async with httpx.AsyncClient(
                base_url=f"https://{palette_host}", timeout=30
            ) as client:
                res = await client.get(url, headers=headers)

            if res.status_code == 422:
                raise Exception(
                    f"Validation error (422): The request was well-formed but contains semantic errors. Details: {res.json()}"
                )

            if res.status_code == 429:
                raise Exception(
                    f"Rate limit error (429): Too many requests. Please wait before retrying. Response: {res.text}"
                )

            if res.status_code >= 400:
                raise Exception(
                    f"API request failed with status {res.status_code}: {res.text}"
                )

            result = {"clusterProfile": res.json()}
            safe_set_output(span, result)
            safe_set_span_status(span, "OK")

            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False,
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))

            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True,
            }


async def _delete_cluster_profile_by_uid(
    ctx: Context,
    clusterprofile_uid: str,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> MCPResult:
    """Internal helper: Deletes a specific cluster profile using its UID."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)

    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()

    if not api_key:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: No api_key provided and no default API key configured",
                }
            ],
            "isError": True,
        }

    with create_span("_delete_cluster_profile_by_uid") as span:
        safe_set_tool(
            span,
            name="_delete_cluster_profile_by_uid",
            description="Deletes a specific cluster profile from Palette using its UID",
            parameters={
                "clusterprofile_uid": {
                    "type": "string",
                    "description": "The UID of the cluster profile to delete",
                },
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)",
                },
                "api_key": {
                    "type": "string",
                    "description": "The API key for the Palette API (optional, uses default if not provided)",
                },
            },
        )

        safe_set_input(
            span,
            mask_sensitive_data(
                {"api_key": api_key, "clusterprofile_uid": clusterprofile_uid}
            ),
        )

        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "apiKey": api_key,
            }

            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers["ProjectUid"] = project_id

            url = f"/v1/clusterprofiles/{clusterprofile_uid}"

            async with httpx.AsyncClient(
                base_url=f"https://{palette_host}", timeout=30
            ) as client:
                res = await client.delete(url, headers=headers)

            if res.status_code == 422:
                raise Exception(
                    f"Validation error (422): The request was well-formed but contains semantic errors. Details: {res.json()}"
                )

            if res.status_code == 429:
                raise Exception(
                    f"Rate limit error (429): Too many requests. Please wait before retrying. Response: {res.text}"
                )

            if res.status_code >= 400:
                raise Exception(
                    f"API request failed with status {res.status_code}: {res.text}"
                )

            # Handle successful DELETE response (typically 204 No Content)
            if res.status_code == 204 or not res.content:
                result = {
                    "status": "success",
                    "message": f"Cluster profile {clusterprofile_uid} deleted successfully",
                    "http_status": res.status_code,
                }
            else:
                try:
                    result = {"status": res.json()}
                except Exception:
                    result = {
                        "status": "success",
                        "message": f"Cluster profile {clusterprofile_uid} deleted successfully",
                        "response": res.text,
                        "http_status": res.status_code,
                    }

            safe_set_output(span, result)
            safe_set_span_status(span, "OK")

            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False,
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))

            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True,
            }


async def gather_or_delete_clusterprofiles(
    ctx: Context,
    action: str,
    uid: Optional[str] = None,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> MCPResult:
    """Gather information about cluster profiles in Palette or delete a cluster profile in Palette.

    Args:
        action: The operation to perform. Must be one of:
            - "list": Get all cluster profiles in the project
            - "get": Get detailed information about a specific cluster profile (requires uid)
            - "delete": Delete a cluster profile (requires uid, requires ALLOW_DANGEROUS_ACTIONS=1)
        uid: The UID of the cluster profile. Required for "get" and "delete" actions.
        project_id: Optional project ID override.
        api_key: Optional API key override.
    """
    session_ctx = get_session_context(ctx)

    with create_span("gather_or_delete_clusterprofiles") as span:
        safe_set_tool(
            span,
            name="gather_or_delete_clusterprofiles",
            description="Gather information about cluster profiles or delete a cluster profile in Palette",
            parameters={
                "action": {
                    "type": "string",
                    "description": "The operation: 'list', 'get', or 'delete'",
                },
                "uid": {
                    "type": "string",
                    "description": "The UID of the cluster profile (required for get/delete)",
                },
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project (optional)",
                },
                "api_key": {"type": "string", "description": "The API key (optional)"},
            },
        )

        safe_set_input(span, {"action": action, "uid": uid})

        # Validate action - only get, list, delete are allowed.
        if action not in ["list", "get", "delete"]:
            error_msg = f"Error: Invalid action '{action}'. Only 'get', 'list', and 'delete' are allowed actions."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Validate uid requirement for get.
        if action == "get" and not uid:
            error_msg = "Error: The 'get' action requires a cluster profile UID. Use action='list' first to retrieve all cluster profiles and identify the UID of the profile you are interested in."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Validate uid requirement for delete.
        if action == "delete" and not uid:
            error_msg = "Error: The 'delete' action requires a cluster profile UID. Use action='list' to retrieve all cluster profiles and identify the UID of the profile you want to delete."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Check dangerous action permission for delete.
        if action == "delete" and not session_ctx.is_dangerous_actions_allowed():
            error_msg = "Error: The 'delete' action is not allowed. The ALLOW_DANGEROUS_ACTIONS environment variable must be set to '1' to enable dangerous operations like delete."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Route to appropriate helper.
        if action == "list":
            result = await _list_cluster_profiles(ctx, project_id, api_key)
        elif action == "get":
            result = await _get_cluster_profile_by_uid(ctx, uid, project_id, api_key)
        elif action == "delete":
            result = await _delete_cluster_profile_by_uid(ctx, uid, project_id, api_key)

        if not result.get("isError", False):
            safe_set_span_status(span, "OK")
        else:
            safe_set_span_status(span, "ERROR")

        return result
