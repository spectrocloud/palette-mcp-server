# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import json
from typing import Dict, TypedDict, Any, List, Optional, Union
from pydantic import BaseModel
from datetime import datetime
from fastmcp import FastMCP, Context
from context import MCPSessionContext
from helpers import (
    write_kubeconfig_to_temp,
    create_span,
    build_headers,
    extract_cluster_profile_tags,
    merge_tags,
    palette_api_request,
    TAG_LIST_ENDPOINTS,
    TAG_UPDATE_ENDPOINTS,
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
    ctx: Context,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
    limit: Optional[int] = 25,
    continue_token: Optional[str] = None,
    compact: bool = True,
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
            headers = build_headers(api_key=api_key, project_id=project_id)

            def _compact_cluster(cluster: Dict[str, Any]) -> Dict[str, Any]:
                """Return a lightweight view of a cluster."""
                metadata = cluster.get("metadata", {}) or {}
                spec = cluster.get("spec", {}) or {}
                cloud_config = spec.get("cloudConfig", {}) or {}
                status = cluster.get("status", {}) or {}
                return {
                    "uid": metadata.get("uid"),
                    "name": metadata.get("name"),
                    "state": status.get("state"),
                    "cloud_type": cloud_config.get("type"),
                    "location": cloud_config.get("region")
                    or cloud_config.get("location"),
                }

            all_clusters = []
            next_request_continue = continue_token

            while True:
                request_headers = dict(headers)
                if next_request_continue:
                    request_headers["Continue"] = next_request_continue

                res = await palette_api_request(
                    palette_host=palette_host,
                    method="GET",
                    path="/v1/spectroclusters/",
                    headers=request_headers,
                )
                json_data = res.json()
                items = json_data.get("items") or []
                cleaned_items = []
                for cluster in items:
                    # Clean up values.yaml from cluster profile templates.
                    if "spec" in cluster:
                        spec = cluster["spec"]
                        if "clusterProfileTemplates" in spec:
                            for template in spec["clusterProfileTemplates"]:
                                if "packs" in template:
                                    for pack in template["packs"]:
                                        if "values" in pack:
                                            del pack["values"]
                    cleaned_items.append(
                        _compact_cluster(cluster) if compact else cluster
                    )

                page_continue = json_data.get("listmeta", {}).get("continue")

                if (
                    all_clusters
                    and limit is not None
                    and (len(all_clusters) + len(cleaned_items)) > limit
                ):
                    next_request_continue = page_continue
                    break

                all_clusters.extend(cleaned_items)

                if not page_continue:
                    next_request_continue = None
                    break
                if limit is not None and len(all_clusters) >= limit:
                    next_request_continue = page_continue
                    break
                next_request_continue = page_continue

            result = {
                "clusters": {
                    "items": all_clusters,
                    "returned_count": len(all_clusters),
                    "limit": limit,
                    "next_continue_token": next_request_continue,
                    "compact": compact,
                }
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


async def _list_active_clusters(
    ctx: Context,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
    limit: Optional[int] = 25,
    continue_token: Optional[str] = None,
    compact: bool = True,
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
            headers = build_headers(
                api_key=api_key, project_id=project_id, include_content_type=True
            )

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

            def _compact_cluster(cluster: Dict[str, Any]) -> Dict[str, Any]:
                """Return a lightweight view of a cluster."""
                metadata = cluster.get("metadata", {}) or {}
                spec = cluster.get("spec", {}) or {}
                cloud_config = spec.get("cloudConfig", {}) or {}
                status = cluster.get("status", {}) or {}
                return {
                    "uid": metadata.get("uid"),
                    "name": metadata.get("name"),
                    "state": status.get("state"),
                    "cloud_type": cloud_config.get("type"),
                    "location": cloud_config.get("region")
                    or cloud_config.get("location"),
                }

            active_clusters = []
            next_request_continue = continue_token

            while True:
                request_headers = dict(headers)
                if next_request_continue:
                    request_headers["Continue"] = next_request_continue

                res = await palette_api_request(
                    palette_host=palette_host,
                    method="POST",
                    path="/v1/dashboard/spectroclusters/search",
                    headers=request_headers,
                    body=payload,
                )
                json_data = res.json()
                items = json_data.get("items", [])
                cleaned_items = [
                    _compact_cluster(item) if compact else item for item in items
                ]
                page_continue = json_data.get("listmeta", {}).get("continue")

                if (
                    active_clusters
                    and limit is not None
                    and (len(active_clusters) + len(cleaned_items)) > limit
                ):
                    next_request_continue = page_continue
                    break

                active_clusters.extend(cleaned_items)

                if not page_continue:
                    next_request_continue = None
                    break
                if limit is not None and len(active_clusters) >= limit:
                    next_request_continue = page_continue
                    break
                next_request_continue = page_continue

            result = {
                "clusters": {
                    "items": active_clusters,
                    "returned_count": len(active_clusters),
                    "limit": limit,
                    "next_continue_token": next_request_continue,
                    "compact": compact,
                }
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
            headers = build_headers(
                api_key=api_key, project_id=project_id, include_content_type=True
            )

            url = f"/v1/spectroclusters/{cluster_uid}"
            params = {
                "includeTags": "true",
                "resolvePackValues": "true",
                "includePackMeta": "false",
                "profileType": "<string>",
                "includeNonSpectroLabels": "false",
            }

            res = await palette_api_request(
                palette_host=palette_host,
                method="GET",
                path=url,
                headers=headers,
                params=params,
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
            headers = build_headers(
                api_key=api_key, project_id=project_id, include_content_type=True
            )

            url = f"/v1/spectroclusters/{cluster_uid}"
            params = {"forceDelete": str(force_delete).lower()}

            res = await palette_api_request(
                palette_host=palette_host,
                method="DELETE",
                path=url,
                headers=headers,
                params=params,
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
    limit: Optional[int] = 25,
    continue_token: Optional[str] = None,
    compact: bool = True,
    force_delete: bool = False,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> MCPResult:
    """Gather information about clusters or delete a cluster in Palette.
    Results are automatically compacted to avoid oversized responses and improve performance. To retrieve all results, use the pagination continue_token parameter in subsequent calls until no continue_token is returned.

    Args:
        action: The operation to perform. Must be one of:
            - "list": Get all clusters in the project (use active_only=True to filter to active clusters only)
            - "get": Get detailed information about a specific cluster (requires uid)
            - "delete": Delete a cluster (requires uid, requires ALLOW_DANGEROUS_ACTIONS=1)
        uid: The UID of the cluster. Required for "get" and "delete" actions.
        active_only: If True and action="list", only return active clusters. Default is False.
        limit: Maximum number of clusters to return for list action. Default is 25.
        continue_token: Continuation token from previous list response to fetch the next page.
        compact: If True (default), list returns a compact cluster shape to avoid oversized responses. When False, the full cluster object is returned that contains the machine spec, metadata, and status.
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
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of clusters to return for list action. Default is 25.",
                },
                "continue_token": {
                    "type": "string",
                    "description": "Continuation token from a previous list response.",
                },
                "compact": {
                    "type": "boolean",
                    "description": "If True, return a compact list payload for cluster listings. Default is True.",
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
                "limit": limit,
                "continue_token": continue_token,
                "compact": compact,
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

        if action == "list" and limit is not None and limit <= 0:
            error_msg = (
                "Error: The 'limit' parameter must be greater than 0 for list action."
            )
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Route to appropriate helper.
        if action == "list":
            if active_only:
                result = await _list_active_clusters(
                    ctx,
                    project_id,
                    api_key,
                    limit=limit,
                    continue_token=continue_token,
                    compact=compact,
                )
            else:
                result = await _list_clusters(
                    ctx,
                    project_id,
                    api_key,
                    limit=limit,
                    continue_token=continue_token,
                    compact=compact,
                )
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
            headers = build_headers(
                api_key=api_key,
                project_id=project_id,
                accept="application/octet-stream",
            )

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
            res = await palette_api_request(
                palette_host=palette_host,
                method="GET",
                path=url,
                headers=headers,
                allowed_status_codes={404} if admin_config else None,
            )

            if admin_config and res.status_code == 404:
                actual_admin_config = False
                res = await palette_api_request(
                    palette_host=palette_host,
                    method="GET",
                    path=f"/v1/spectroclusters/{cluster_uid}/assets/kubeconfig",
                    headers=headers,
                    params={"frp": "true"},
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
    ctx: Context,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
    limit: Optional[int] = 25,
    continue_token: Optional[str] = None,
    compact: bool = True,
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
            headers = build_headers(api_key=api_key, project_id=project_id)

            def _compact_cluster_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
                """Return a lightweight view of a cluster profile."""
                metadata = profile.get("metadata", {}) or {}
                spec = profile.get("spec", {}) or {}
                return {
                    "uid": metadata.get("uid"),
                    "name": metadata.get("name"),
                    "version": spec.get("version"),
                    "tags": extract_cluster_profile_tags(profile),
                }

            all_profiles = []
            next_request_continue = continue_token

            while True:
                request_headers = dict(headers)
                if next_request_continue:
                    request_headers["Continue"] = next_request_continue

                res = await palette_api_request(
                    palette_host=palette_host,
                    method="GET",
                    path="/v1/clusterprofiles/",
                    headers=request_headers,
                )
                json_data = res.json()
                items = json_data.get("items", [])

                # Clean up pack values from cluster profiles.
                cleaned_items = []
                for profile in items:
                    if "spec" in profile:
                        # Handle published packs.
                        if (
                            "published" in profile["spec"]
                            and "packs" in profile["spec"]["published"]
                        ):
                            for pack in profile["spec"]["published"]["packs"]:
                                if "values" in pack:
                                    del pack["values"]

                        # Handle draft packs.
                        if (
                            "draft" in profile["spec"]
                            and "packs" in profile["spec"]["draft"]
                        ):
                            for pack in profile["spec"]["draft"]["packs"]:
                                if "values" in pack:
                                    del pack["values"]

                    cleaned_items.append(
                        _compact_cluster_profile(profile) if compact else profile
                    )

                page_continue = json_data.get("listmeta", {}).get("continue")

                # Keep page boundaries intact for stable pagination.
                if (
                    all_profiles
                    and limit is not None
                    and (len(all_profiles) + len(cleaned_items)) > limit
                ):
                    next_request_continue = page_continue
                    break

                all_profiles.extend(cleaned_items)

                if not page_continue:
                    next_request_continue = None
                    break
                if limit is not None and len(all_profiles) >= limit:
                    next_request_continue = page_continue
                    break
                next_request_continue = page_continue

            result = {
                "clusterProfiles": {
                    "items": all_profiles,
                    "returned_count": len(all_profiles),
                    "limit": limit,
                    "next_continue_token": next_request_continue,
                    "compact": compact,
                }
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
            res = await palette_api_request(
                palette_host=palette_host,
                method="GET",
                path=url,
                headers=headers,
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
            headers = build_headers(
                api_key=api_key, project_id=project_id, include_content_type=True
            )

            url = f"/v1/clusterprofiles/{clusterprofile_uid}"

            res = await palette_api_request(
                palette_host=palette_host,
                method="DELETE",
                path=url,
                headers=headers,
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
    limit: Optional[int] = 25,
    continue_token: Optional[str] = None,
    compact: bool = True,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> MCPResult:
    """Gather information about cluster profiles in Palette or delete a cluster profile in Palette.
    Results are automatically compacted to avoid oversized responses and improve performance. To retrieve all results, use the pagination continue_token parameter in subsequent calls until no continue_token is returned.

    Args:
        action: The operation to perform. Must be one of:
            - "list": Get all cluster profiles in the project
            - "get": Get detailed information about a specific cluster profile (requires uid)
            - "delete": Delete a cluster profile (requires uid, requires ALLOW_DANGEROUS_ACTIONS=1)
        uid: The UID of the cluster profile. Required for "get" and "delete" actions.
        limit: Maximum number of cluster profiles to return for list action. Default is 25.
        continue_token: Continuation token from previous list response to fetch the next page.
        compact: If True (default), list returns a compact cluster profile object to avoid oversized responses. When False, the full clusterprofile object is returned that contains the cluster profile spec, packs, versions, metadata, and status.
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
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of profiles to return for list action. Default is 25.",
                },
                "continue_token": {
                    "type": "string",
                    "description": "Continuation token from a previous list response.",
                },
                "compact": {
                    "type": "boolean",
                    "description": "If True, return a compact list payload for profile listings. Default is True.",
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
                "limit": limit,
                "continue_token": continue_token,
                "compact": compact,
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

        if action == "list" and limit is not None and limit <= 0:
            error_msg = (
                "Error: The 'limit' parameter must be greater than 0 for list action."
            )
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Route to appropriate helper.
        if action == "list":
            result = await _list_cluster_profiles(
                ctx,
                project_id,
                api_key,
                limit=limit,
                continue_token=continue_token,
                compact=compact,
            )
        elif action == "get":
            result = await _get_cluster_profile_by_uid(ctx, uid, project_id, api_key)
        elif action == "delete":
            result = await _delete_cluster_profile_by_uid(ctx, uid, project_id, api_key)

        if not result.get("isError", False):
            safe_set_span_status(span, "OK")
        else:
            safe_set_span_status(span, "ERROR")

        return result


async def manage_resource_tags(
    ctx: Context,
    action: str,
    resource_type: Optional[str] = None,
    uid: Optional[str] = None,
    policy_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> MCPResult:
    """Manage Palette resource tags through one action-based tool.

    Args:
        action: One of list, get, create, or delete.
        resource_type: Resource type for tag operations. Supports spectroclusters, clusterprofiles, clusterTemplates, edgehosts, and policy.
        uid: A resource UID is required by get, create, and delete.
        policy_type: Optional policy family for policy/spcPolicies actions (for example, maintenance). If omitted, the tool tries maintenance automatically.
        tags: Tag values used by create and delete. You can pass in a list of tags. Each tag should be a string in the format "key:value" or a single key.
        project_id: Optional project ID override.
        api_key: Optional API key override.
    """
    session_ctx = get_session_context(ctx)
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

    with create_span("manage_resource_tags") as span:
        safe_set_tool(
            span,
            name="manage_resource_tags",
            description="Manage tag lifecycle in Palette, including list/get/create/delete tag actions",
            parameters={
                "action": {
                    "type": "string",
                    "description": "One of: list, get, create, delete",
                },
                "resource_type": {
                    "type": "string",
                    "description": "Resource type for tag operations. One of: spectroclusters, clusterprofiles, clusterTemplates, edgehosts, policy (alias: spcPolicies)",
                },
                "uid": {
                    "type": "string",
                    "description": "Resource uid for get, create, and delete",
                },
                "policy_type": {
                    "type": "string",
                    "description": "Optional policy family for policy/spcPolicies actions. If omitted, the tool tries maintenance.",
                },
                "tags": {
                    "type": "array",
                    "description": "Tags used by create and delete",
                },
                "project_id": {
                    "type": "string",
                    "description": "The project ID override",
                },
                "api_key": {"type": "string", "description": "The API key override"},
            },
        )

        safe_set_input(
            span,
            mask_sensitive_data(
                {
                    "action": action,
                    "resource_type": resource_type,
                    "uid": uid,
                    "policy_type": policy_type,
                    "tags": tags,
                    "project_id": project_id,
                    "api_key": api_key,
                }
            ),
        )

        valid_actions = {
            "list",
            "get",
            "create",
            "delete",
        }
        if action not in valid_actions:
            error_msg = f"Error: Invalid action '{action}'. Supported actions are 'list', 'get', 'create', and 'delete'."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        if action == "list" and not resource_type:
            error_msg = (
                f"Error: The '{action}' action requires 'resource_type' to be provided."
            )
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        if action in {"get", "create", "delete"} and (not resource_type or not uid):
            error_msg = (
                f"Error: The '{action}' action requires both 'resource_type' and 'uid'."
            )
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        if action in {"create", "delete"} and not tags:
            error_msg = f"Error: The '{action}' action requires 'tags' to be provided."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        if action == "delete" and not session_ctx.is_dangerous_actions_allowed():
            error_msg = (
                "Error: The 'delete' action is not allowed. The "
                "ALLOW_DANGEROUS_ACTIONS environment variable must be set to '1' "
                "to enable dangerous operations like delete."
            )
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        canonical_resource_type = (
            "spcPolicies" if resource_type == "policy" else resource_type
        )

        try:
            result: Dict[str, Any]

            if action == "list":
                headers = build_headers(api_key=api_key, project_id=project_id)
                params: Optional[Dict[str, str]] = None

                if canonical_resource_type == "clusterprofiles":
                    # Reuse the same list behavior as gather_or_delete_clusterprofiles
                    # so tag extraction reflects the currently working MCP tool.
                    list_result = await _list_cluster_profiles(
                        ctx,
                        project_id=project_id,
                        api_key=api_key,
                        limit=None,
                        compact=True,
                    )
                    if list_result.get("isError", False):
                        return list_result

                    list_text = (
                        list_result.get("content", [{}])[0].get("text", "{}")
                        if list_result.get("content")
                        else "{}"
                    )
                    list_payload = json.loads(list_text)
                    all_profiles = list_payload.get("clusterProfiles", {}).get(
                        "items", []
                    )

                    extracted_tags: set[str] = set()
                    for profile in all_profiles:
                        if "tags" in profile and isinstance(profile["tags"], list):
                            extracted_tags.update(
                                tag for tag in profile["tags"] if isinstance(tag, str)
                            )
                        else:
                            extracted_tags.update(extract_cluster_profile_tags(profile))

                    result = {
                        "action": action,
                        "resource_type": resource_type,
                        "data": {"tags": sorted(extracted_tags)},
                    }
                else:
                    if canonical_resource_type not in TAG_LIST_ENDPOINTS:
                        raise ValueError(
                            f"Error: Unsupported resource_type '{resource_type}' for list."
                        )
                    path = TAG_LIST_ENDPOINTS[canonical_resource_type]
                    response = await palette_api_request(
                        palette_host=palette_host,
                        method="GET",
                        path=path,
                        headers=headers,
                        params=params,
                    )
                    result = {
                        "action": action,
                        "resource_type": resource_type,
                        "data": response.json(),
                    }

            else:
                if canonical_resource_type not in TAG_UPDATE_ENDPOINTS:
                    raise ValueError(
                        f"Error: Unsupported resource_type '{resource_type}' for {action}."
                    )

                endpoint_cfg = TAG_UPDATE_ENDPOINTS[canonical_resource_type]
                path_kwargs: Dict[str, Any] = {"uid": uid}

                get_headers = {"Accept": "application/json", "apiKey": api_key}
                if project_id:
                    get_headers["ProjectUid"] = project_id
                get_params = (
                    {"includeTags": "true"}
                    if canonical_resource_type == "spectroclusters"
                    else None
                )

                get_response = None
                if canonical_resource_type == "spcPolicies":
                    # If type is omitted, try maintenance as the default policy family.
                    resolved_policy_type = (policy_type or "").strip()
                    candidate_policy_types = (
                        [resolved_policy_type]
                        if resolved_policy_type
                        else ["maintenance"]
                    )
                    for candidate in candidate_policy_types:
                        probe_response = await palette_api_request(
                            palette_host=palette_host,
                            method=endpoint_cfg["get_method"],
                            path=endpoint_cfg["get_path"].format(
                                uid=uid, policy_type=candidate
                            ),
                            headers=get_headers,
                            params=get_params,
                            allowed_status_codes={404},
                        )
                        if probe_response.status_code < 400:
                            resolved_policy_type = candidate
                            get_response = probe_response
                            break

                    if not resolved_policy_type:
                        raise ValueError(
                            "Error: Could not resolve policy type from this UID. "
                            "Provide 'policy_type' explicitly if it is not maintenance."
                        )

                    path_kwargs["policy_type"] = resolved_policy_type

                if get_response is None:
                    get_response = await palette_api_request(
                        palette_host=palette_host,
                        method=endpoint_cfg["get_method"],
                        path=endpoint_cfg["get_path"].format(**path_kwargs),
                        headers=get_headers,
                        params=get_params,
                    )

                resource_doc = get_response.json()
                metadata = resource_doc.get("metadata", {})
                labels = metadata.get("labels", {}) or {}

                def _tag_key(tag_value: str) -> str:
                    if ":" in tag_value:
                        key, _ = tag_value.split(":", 1)
                        return key.strip()
                    return tag_value.strip()

                if canonical_resource_type == "spectroclusters":
                    current_tags, _ = merge_tags(metadata.get("labels"), [], "add")
                elif canonical_resource_type == "clusterprofiles":
                    current_tags = extract_cluster_profile_tags(resource_doc)
                elif canonical_resource_type == "clusterTemplates":
                    current_tags, _ = merge_tags(metadata.get("labels"), [], "add")
                elif canonical_resource_type == "spcPolicies":
                    current_tags, _ = merge_tags(metadata.get("labels"), [], "add")
                elif canonical_resource_type == "edgehosts":
                    current_tags, _ = merge_tags(metadata.get("labels"), [], "add")
                else:
                    current_tags, _ = merge_tags(metadata.get("tags"), [], "add")

                if action == "get":
                    result = {
                        "action": action,
                        "resource_type": resource_type,
                        "uid": uid,
                        "data": {"tags": current_tags},
                    }
                    if canonical_resource_type == "spcPolicies":
                        result["policy_type"] = path_kwargs.get("policy_type")
                    safe_set_output(span, result)
                    safe_set_span_status(span, "OK")
                    return {
                        "content": [
                            {"type": "text", "text": json.dumps(result, indent=2)}
                        ],
                        "isError": False,
                    }

                if canonical_resource_type == "spectroclusters":
                    before_tags, after_tags = merge_tags(
                        current_tags,
                        tags or [],
                        "add" if action == "create" else "remove",
                    )
                elif canonical_resource_type == "clusterprofiles":
                    before_tags, after_tags = merge_tags(
                        current_tags,
                        tags or [],
                        "add" if action == "create" else "remove",
                    )
                elif canonical_resource_type == "clusterTemplates":
                    before_tags, after_tags = merge_tags(
                        current_tags,
                        tags or [],
                        "add" if action == "create" else "remove",
                    )
                elif canonical_resource_type == "spcPolicies":
                    before_tags, after_tags = merge_tags(
                        current_tags,
                        tags or [],
                        "add" if action == "create" else "remove",
                    )
                elif canonical_resource_type == "edgehosts":
                    before_tags, after_tags = merge_tags(
                        current_tags,
                        tags or [],
                        "add" if action == "create" else "remove",
                    )
                else:
                    before_tags, after_tags = merge_tags(
                        metadata.get("tags"),
                        tags or [],
                        "add" if action == "create" else "remove",
                    )

                update_metadata: Dict[str, Any] = {
                    "name": metadata.get("name"),
                    "annotations": metadata.get("annotations", {}),
                    "labels": metadata.get("labels", {}),
                    "tags": after_tags,
                }

                if canonical_resource_type == "spectroclusters":
                    existing_labels = metadata.get("labels", {}) or {}
                    updated_labels = dict(existing_labels)

                    # Replace tag keys while preserving unrelated labels.
                    previous_tag_keys = {
                        _tag_key(tag_value)
                        for tag_value in before_tags
                        if _tag_key(tag_value)
                    }
                    for key in previous_tag_keys:
                        updated_labels.pop(key, None)

                    for tag_value in after_tags:
                        if ":" in tag_value:
                            key, val = tag_value.split(":", 1)
                            key = key.strip()
                            val = val.strip()
                            if key and val:
                                updated_labels[key] = val
                            elif key:
                                updated_labels[key] = "spectro__tag"
                        else:
                            key = tag_value.strip()
                            if key:
                                updated_labels[key] = "spectro__tag"

                    update_metadata["labels"] = updated_labels
                elif canonical_resource_type == "clusterprofiles":
                    existing_labels = metadata.get("labels", {}) or {}
                    updated_labels = dict(existing_labels)
                    value_backed_tags: List[str] = []

                    # Remove any keys that were part of the previous tag set, then rebuild.
                    # This ensures delete removes key:value tags as well as key-only tags.
                    previous_tag_keys = {
                        _tag_key(tag_value)
                        for tag_value in before_tags
                        if _tag_key(tag_value)
                    }
                    for key in previous_tag_keys:
                        updated_labels.pop(key, None)

                    for tag_value in after_tags:
                        if ":" in tag_value:
                            key, val = tag_value.split(":", 1)
                            key = key.strip()
                            val = val.strip()
                            if key and val:
                                updated_labels[key] = val
                                if val != "spectro__tag":
                                    value_backed_tags.append(f"{key}:{val}")
                            elif key:
                                updated_labels[key] = "spectro__tag"
                        else:
                            key = tag_value.strip()
                            if key:
                                updated_labels[key] = "spectro__tag"

                    update_metadata["labels"] = updated_labels
                    # Keep explicit key:value tags in metadata.tags for APIs that surface tags directly.
                    update_metadata["tags"] = sorted(set(value_backed_tags))
                elif canonical_resource_type == "clusterTemplates":
                    existing_labels = metadata.get("labels", {}) or {}
                    updated_labels = dict(existing_labels)
                    previous_tag_keys = {
                        _tag_key(tag_value)
                        for tag_value in before_tags
                        if _tag_key(tag_value)
                    }
                    for key in previous_tag_keys:
                        updated_labels.pop(key, None)

                    for tag_value in after_tags:
                        if ":" in tag_value:
                            key, val = tag_value.split(":", 1)
                            key = key.strip()
                            val = val.strip()
                            if key and val:
                                updated_labels[key] = val
                            elif key:
                                updated_labels[key] = "spectro__tag"
                        else:
                            key = tag_value.strip()
                            if key:
                                updated_labels[key] = "spectro__tag"

                    update_metadata["labels"] = updated_labels
                    update_metadata.pop("tags", None)
                elif canonical_resource_type == "spcPolicies":
                    existing_labels = metadata.get("labels", {}) or {}
                    updated_labels = dict(existing_labels)
                    previous_tag_keys = {
                        _tag_key(tag_value)
                        for tag_value in before_tags
                        if _tag_key(tag_value)
                    }
                    for key in previous_tag_keys:
                        updated_labels.pop(key, None)

                    for tag_value in after_tags:
                        if ":" in tag_value:
                            key, val = tag_value.split(":", 1)
                            key = key.strip()
                            val = val.strip()
                            if key and val:
                                updated_labels[key] = val
                            elif key:
                                updated_labels[key] = "spectro__tag"
                        else:
                            key = tag_value.strip()
                            if key:
                                updated_labels[key] = "spectro__tag"

                    update_metadata["labels"] = updated_labels
                    update_metadata.pop("tags", None)
                elif canonical_resource_type == "edgehosts":
                    existing_labels = metadata.get("labels", {}) or {}
                    updated_labels = dict(existing_labels)
                    previous_tag_keys = {
                        _tag_key(tag_value)
                        for tag_value in before_tags
                        if _tag_key(tag_value)
                    }
                    for key in previous_tag_keys:
                        updated_labels.pop(key, None)

                    for tag_value in after_tags:
                        if ":" in tag_value:
                            key, val = tag_value.split(":", 1)
                            key = key.strip()
                            val = val.strip()
                            if key and val:
                                updated_labels[key] = val
                            elif key:
                                updated_labels[key] = "spectro__tag"
                        else:
                            key = tag_value.strip()
                            if key:
                                updated_labels[key] = "spectro__tag"

                    # Edgehost meta updates follow metadata.labels + name + uid shape.
                    update_metadata = {
                        "name": metadata.get("name"),
                        "uid": metadata.get("uid", uid),
                        "labels": updated_labels,
                    }

                update_body = {"metadata": update_metadata}
                if canonical_resource_type == "clusterprofiles":
                    spec = resource_doc.get("spec", {})
                    version = spec.get("version")
                    if version:
                        update_body["spec"] = {"version": version}
                elif canonical_resource_type == "spcPolicies":
                    update_body["spec"] = resource_doc.get("spec", {})

                update_headers = build_headers(
                    api_key=api_key,
                    project_id=project_id,
                    include_content_type=True,
                )

                update_response = await palette_api_request(
                    palette_host=palette_host,
                    method=endpoint_cfg["update_method"],
                    path=endpoint_cfg["update_path"].format(**path_kwargs),
                    headers=update_headers,
                    body=update_body,
                )

                result = {
                    "action": action,
                    "resource_type": resource_type,
                    "uid": uid,
                    "data": {
                        "tags_before": before_tags,
                        "tags_after": after_tags,
                    },
                    "http_status": update_response.status_code,
                }
                if canonical_resource_type == "spcPolicies":
                    result["policy_type"] = path_kwargs.get("policy_type")

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
