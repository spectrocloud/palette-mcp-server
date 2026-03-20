# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import json
from typing import Any, Dict, Optional

from fastmcp import Context

from helpers import (
    build_headers,
    extract_cluster_profile_tags,
    palette_api_request,
)
from tracing import create_span, safe_set_input, safe_set_output, safe_set_tool
from tools.common import (
    MCPResult,
    get_session_context,
    mask_sensitive_data,
    safe_set_span_status,
)


async def _list_cluster_profiles(
    ctx: Context,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
    limit: Optional[int] = 25,
    continue_token: Optional[str] = None,
    compact: bool = True,
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

                cleaned_items = []
                for profile in items:
                    if "spec" in profile:
                        if (
                            "published" in profile["spec"]
                            and "packs" in profile["spec"]["published"]
                        ):
                            for pack in profile["spec"]["published"]["packs"]:
                                if "values" in pack:
                                    del pack["values"]
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
            return {"content": [{"type": "text", "text": error_message}], "isError": True}


async def _get_cluster_profile_by_uid(
    ctx: Context,
    clusterprofile_uid: str,
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
    with create_span("_get_cluster_profile_by_uid") as span:
        safe_set_tool(
            span,
            name="_get_cluster_profile_by_uid",
            description="Queries Palette API for a specific cluster profile by UID, returning complete profile data including pack values",
            parameters={
                "clusterprofile_uid": {"type": "string", "description": "The UID of the cluster profile to retrieve"},
                "project_id": {"type": "string", "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)"},
                "api_key": {"type": "string", "description": "The API key for the Palette API (optional, uses default if not provided)"},
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
            if project_id:
                headers["ProjectUid"] = project_id
            res = await palette_api_request(
                palette_host=palette_host,
                method="GET",
                path=f"/v1/clusterprofiles/{clusterprofile_uid}",
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
            return {"content": [{"type": "text", "text": error_message}], "isError": True}


async def _delete_cluster_profile_by_uid(
    ctx: Context,
    clusterprofile_uid: str,
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
    with create_span("_delete_cluster_profile_by_uid") as span:
        safe_set_tool(
            span,
            name="_delete_cluster_profile_by_uid",
            description="Deletes a specific cluster profile from Palette using its UID",
            parameters={
                "clusterprofile_uid": {"type": "string", "description": "The UID of the cluster profile to delete"},
                "project_id": {"type": "string", "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)"},
                "api_key": {"type": "string", "description": "The API key for the Palette API (optional, uses default if not provided)"},
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
            res = await palette_api_request(
                palette_host=palette_host,
                method="DELETE",
                path=f"/v1/clusterprofiles/{clusterprofile_uid}",
                headers=headers,
            )
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
            return {"content": [{"type": "text", "text": error_message}], "isError": True}


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
    session_ctx = get_session_context(ctx)
    with create_span("gather_or_delete_clusterprofiles") as span:
        safe_set_tool(
            span,
            name="gather_or_delete_clusterprofiles",
            description="Gather information about cluster profiles or delete a cluster profile in Palette",
            parameters={
                "action": {"type": "string", "description": "The operation: 'list', 'get', or 'delete'"},
                "uid": {"type": "string", "description": "The UID of the cluster profile (required for get/delete)"},
                "limit": {"type": "integer", "description": "Maximum number of profiles to return for list action. Default is 25."},
                "continue_token": {"type": "string", "description": "Continuation token from a previous list response."},
                "compact": {"type": "boolean", "description": "If True, return a compact list payload for profile listings. Default is True."},
                "project_id": {"type": "string", "description": "The ID of the project (optional)"},
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

        if action not in ["list", "get", "delete"]:
            error_msg = f"Error: Invalid action '{action}'. Only 'get', 'list', and 'delete' are allowed actions."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}
        if action == "get" and not uid:
            error_msg = "Error: The 'get' action requires a cluster profile UID. Use action='list' first to retrieve all cluster profiles and identify the UID of the profile you are interested in."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}
        if action == "delete" and not uid:
            error_msg = "Error: The 'delete' action requires a cluster profile UID. Use action='list' to retrieve all cluster profiles and identify the UID of the profile you want to delete."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}
        if action == "delete" and not session_ctx.is_dangerous_actions_allowed():
            error_msg = "Error: The 'delete' action is not allowed. The ALLOW_DANGEROUS_ACTIONS environment variable must be set to '1' to enable dangerous operations like delete."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}
        if action == "list" and limit is not None and limit <= 0:
            error_msg = "Error: The 'limit' parameter must be greater than 0 for list action."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

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
        else:
            result = await _delete_cluster_profile_by_uid(ctx, uid, project_id, api_key)

        safe_set_span_status(span, "OK" if not result.get("isError", False) else "ERROR")
        return result


__all__ = ["gather_or_delete_clusterprofiles", "_list_cluster_profiles"]
