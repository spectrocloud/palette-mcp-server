# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import json
from typing import Any, Dict, Optional

from fastmcp import Context

from helpers import (
    build_headers,
    palette_api_request,
)
from tracing import create_span, safe_set_input, safe_set_output, safe_set_tool
from tools.common import (
    MCPResult,
    get_session_context,
    mask_sensitive_data,
    safe_set_span_status,
)


async def _list_clusters(
    ctx: Context,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
    limit: Optional[int] = 25,
    continue_token: Optional[str] = None,
    compact: bool = True,
) -> MCPResult:
    """Internal helper: Queries the Palette API to find all clusters in a given project, regardless of state."""
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
        safe_set_input(span, mask_sensitive_data({"api_key": api_key}))

        try:
            headers = build_headers(api_key=api_key, project_id=project_id)

            def _compact_cluster(cluster: Dict[str, Any]) -> Dict[str, Any]:
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
                query_params: Dict[str, str] = {}
                if limit is not None:
                    query_params["limit"] = str(limit)
                if next_request_continue:
                    query_params["continue"] = next_request_continue

                res = await palette_api_request(
                    palette_host=palette_host,
                    method="GET",
                    path="/v1/spectroclusters/",
                    headers=headers,
                    params=query_params,
                )
                json_data = res.json()
                items = json_data.get("items") or []
                cleaned_items = []
                for cluster in items:
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
                if limit is not None and (len(all_clusters) + len(cleaned_items)) > limit:
                    remaining = limit - len(all_clusters)
                    all_clusters.extend(cleaned_items[:remaining])
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
                query_params: Dict[str, str] = {}
                if limit is not None:
                    query_params["limit"] = str(limit)
                if next_request_continue:
                    query_params["continue"] = next_request_continue

                res = await palette_api_request(
                    palette_host=palette_host,
                    method="POST",
                    path="/v1/dashboard/spectroclusters/search",
                    headers=headers,
                    params=query_params,
                    body=payload,
                )
                json_data = res.json()
                items = json_data.get("items", [])
                cleaned_items = [
                    _compact_cluster(item) if compact else item for item in items
                ]
                page_continue = json_data.get("listmeta", {}).get("continue")
                if limit is not None and (len(active_clusters) + len(cleaned_items)) > limit:
                    remaining = limit - len(active_clusters)
                    active_clusters.extend(cleaned_items[:remaining])
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
            res = await palette_api_request(
                palette_host=palette_host,
                method="GET",
                path=f"/v1/spectroclusters/{cluster_uid}",
                headers=headers,
                params={
                    "includeTags": "true",
                    "resolvePackValues": "true",
                    "includePackMeta": "false",
                    "includeNonSpectroLabels": "false",
                },
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
            res = await palette_api_request(
                palette_host=palette_host,
                method="DELETE",
                path=f"/v1/spectroclusters/{cluster_uid}",
                headers=headers,
                params={"forceDelete": str(force_delete).lower()},
            )
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

        if action not in ["list", "get", "delete"]:
            error_msg = f"Error: Invalid action '{action}'. Only 'get', 'list', and 'delete' are allowed actions."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}
        if action == "get" and not uid:
            error_msg = "Error: The 'get' action requires a cluster UID. Use action='list' first to retrieve all clusters and identify the UID of the cluster you are interested in."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}
        if action == "delete" and not uid:
            error_msg = "Error: The 'delete' action requires a cluster UID. Use action='list' to retrieve all clusters and identify the UID of the cluster you want to delete."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}
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
        else:
            result = await _delete_cluster_by_uid(
                ctx, uid, project_id, api_key, force_delete
            )

        safe_set_span_status(
            span, "OK" if not result.get("isError", False) else "ERROR"
        )
        return result


__all__ = ["gather_or_delete_clusters"]
