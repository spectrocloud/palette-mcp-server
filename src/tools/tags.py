# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import json
from typing import Any, Dict, List, Optional

from fastmcp import Context

from helpers import (
    build_headers,
    extract_cluster_profile_tags,
    palette_api_request,
)
from tracing import create_span, safe_set_input, safe_set_output, safe_set_tool
from tools.clusterprofiles import _list_cluster_profiles
from tools.common import (
    MCPResult,
    get_session_context,
    mask_sensitive_data,
    safe_set_span_status,
)


TAG_LIST_ENDPOINTS = {
    "spectroclusters": "/v1/spectroclusters/tags",
    "clusterTemplates": "/v1/clusterTemplates/tags",
    "edgehosts": "/v1/edgehosts/tags",
    "spcPolicies": "/v1/spcPolicies/tags",
}


TAG_UPDATE_ENDPOINTS = {
    "spectroclusters": {
        "get_path": "/v1/spectroclusters/{uid}",
        "get_method": "GET",
        "update_path": "/v1/spectroclusters/{uid}/metadata",
        "update_method": "PATCH",
    },
    "clusterprofiles": {
        "get_path": "/v1/clusterprofiles/{uid}",
        "get_method": "GET",
        "update_path": "/v1/clusterprofiles/{uid}/metadata",
        "update_method": "PATCH",
    },
    "clusterTemplates": {
        "get_path": "/v1/clusterTemplates/{uid}",
        "get_method": "GET",
        "update_path": "/v1/clusterTemplates/{uid}/metadata",
        "update_method": "PATCH",
    },
    "edgehosts": {
        "get_path": "/v1/edgehosts/{uid}",
        "get_method": "GET",
        "update_path": "/v1/edgehosts/{uid}/meta",
        "update_method": "PUT",
    },
    "spcPolicies": {
        "get_path": "/v1/spcPolicies/{policy_type}/{uid}",
        "get_method": "GET",
        "update_path": "/v1/spcPolicies/{policy_type}/{uid}",
        "update_method": "PUT",
    },
}


def _normalize_tag_value(value: Any) -> List[str]:
    """Normalize common tag field formats into a string list."""

    def _strip_internal_marker(tag: str) -> str:
        text = (tag or "").strip()
        if not text:
            return ""
        if ":" in text:
            key, val = text.split(":", 1)
            if val.strip() == "spectro__tag":
                return key.strip()
        return text

    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if "," in text and ":" in text:
            return [
                cleaned
                for cleaned in (
                    _strip_internal_marker(part) for part in text.split(",")
                )
                if cleaned
            ]
        cleaned = _strip_internal_marker(text)
        return [cleaned] if cleaned else []

    if isinstance(value, list):
        normalized: List[str] = []
        for item in value:
            if item is None:
                continue
            cleaned = _strip_internal_marker(str(item))
            if cleaned:
                normalized.append(cleaned)
        return normalized

    if isinstance(value, dict):
        tags = []
        for key, val in value.items():
            if val is None or str(val).strip() == "":
                tags.append(str(key))
            elif str(val).strip() == "spectro__tag":
                tags.append(str(key))
            else:
                tags.append(f"{key}:{val}")
        return tags

    return []


def merge_tags(
    existing_tags: Any, requested_tags: List[str], operation: str
) -> tuple[List[str], List[str]]:
    """Merge tags for add/remove operations using list semantics."""
    current = set(_normalize_tag_value(existing_tags))
    requested = [tag.strip() for tag in requested_tags if tag and tag.strip()]

    def _tag_key(tag: str) -> str:
        if ":" in tag:
            key, _ = tag.split(":", 1)
            return key.strip()
        return tag.strip()

    if operation == "add":
        updated = set(current)
        # Upsert by tag key so create can replace stale values (env:dev -> env:prod).
        for requested_tag in requested:
            requested_key = _tag_key(requested_tag)
            updated = {tag for tag in updated if _tag_key(tag) != requested_key}
            updated.add(requested_tag)
    elif operation == "remove":
        updated = set(current)
        for requested_tag in requested:
            if ":" in requested_tag:
                updated.discard(requested_tag)
            else:
                requested_key = _tag_key(requested_tag)
                updated = {tag for tag in updated if _tag_key(tag) != requested_key}
    else:
        raise ValueError(
            "Invalid operation for merge_tags. Supported values are 'add' and 'remove'."
        )

    before = sorted(current)
    after = sorted(updated)
    return before, after


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

        if action not in {"list", "get", "create", "delete"}:
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
            if action == "list":
                headers = build_headers(api_key=api_key, project_id=project_id)
                if canonical_resource_type == "clusterprofiles":
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
                    all_profiles = (
                        json.loads(list_text)
                        .get("clusterProfiles", {})
                        .get("items", [])
                    )
                    extracted_tags: set[str] = set()
                    for profile in all_profiles:
                        if "tags" in profile and isinstance(profile["tags"], list):
                            extracted_tags.update(
                                tag for tag in profile["tags"] if isinstance(tag, str)
                            )
                        else:
                            extracted_tags.update(extract_cluster_profile_tags(profile))
                    result: Dict[str, Any] = {
                        "action": action,
                        "resource_type": resource_type,
                        "data": {"tags": sorted(extracted_tags)},
                    }
                else:
                    if canonical_resource_type not in TAG_LIST_ENDPOINTS:
                        raise ValueError(
                            f"Error: Unsupported resource_type '{resource_type}' for list."
                        )
                    response = await palette_api_request(
                        palette_host=palette_host,
                        method="GET",
                        path=TAG_LIST_ENDPOINTS[canonical_resource_type],
                        headers=headers,
                        params=None,
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
                    resolved_policy_type = (policy_type or "").strip()
                    candidate_policy_types = (
                        [resolved_policy_type]
                        if resolved_policy_type
                        else ["maintenance"]
                    )
                    for candidate in candidate_policy_types:
                        probe = await palette_api_request(
                            palette_host=palette_host,
                            method=endpoint_cfg["get_method"],
                            path=endpoint_cfg["get_path"].format(
                                uid=uid, policy_type=candidate
                            ),
                            headers=get_headers,
                            params=get_params,
                            allowed_status_codes={404},
                        )
                        if probe.status_code < 400:
                            resolved_policy_type = candidate
                            get_response = probe
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

                def _tag_key(tag_value: str) -> str:
                    if ":" in tag_value:
                        key, _ = tag_value.split(":", 1)
                        return key.strip()
                    return tag_value.strip()

                if canonical_resource_type == "spectroclusters":
                    current_tags, _ = merge_tags(metadata.get("labels"), [], "add")
                elif canonical_resource_type == "clusterprofiles":
                    current_tags = extract_cluster_profile_tags(resource_doc)
                elif canonical_resource_type in {
                    "clusterTemplates",
                    "spcPolicies",
                    "edgehosts",
                }:
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

                before_tags, after_tags = merge_tags(
                    current_tags
                    if canonical_resource_type != "other"
                    else metadata.get("tags"),
                    tags or [],
                    "add" if action == "create" else "remove",
                )

                update_metadata: Dict[str, Any] = {
                    "name": metadata.get("name"),
                    "annotations": metadata.get("annotations", {}),
                    "labels": metadata.get("labels", {}),
                    "tags": after_tags,
                }

                if canonical_resource_type in {
                    "spectroclusters",
                    "clusterprofiles",
                    "clusterTemplates",
                    "spcPolicies",
                    "edgehosts",
                }:
                    existing_labels = metadata.get("labels", {}) or {}
                    updated_labels = dict(existing_labels)
                    previous_tag_keys = {
                        _tag_key(tag_value)
                        for tag_value in before_tags
                        if _tag_key(tag_value)
                    }
                    for key in previous_tag_keys:
                        updated_labels.pop(key, None)
                    value_backed_tags: List[str] = []
                    for tag_value in after_tags:
                        if ":" in tag_value:
                            key, val = tag_value.split(":", 1)
                            key = key.strip()
                            val = val.strip()
                            if key and val:
                                updated_labels[key] = val
                                if (
                                    canonical_resource_type == "clusterprofiles"
                                    and val != "spectro__tag"
                                ):
                                    value_backed_tags.append(f"{key}:{val}")
                            elif key:
                                updated_labels[key] = "spectro__tag"
                        else:
                            key = tag_value.strip()
                            if key:
                                updated_labels[key] = "spectro__tag"
                    if canonical_resource_type == "edgehosts":
                        update_metadata = {
                            "name": metadata.get("name"),
                            "uid": metadata.get("uid", uid),
                            "labels": updated_labels,
                        }
                    else:
                        update_metadata["labels"] = updated_labels
                    if canonical_resource_type == "clusterprofiles":
                        update_metadata["tags"] = sorted(set(value_backed_tags))
                    elif canonical_resource_type in {"clusterTemplates", "spcPolicies"}:
                        update_metadata.pop("tags", None)

                update_body = {"metadata": update_metadata}
                if canonical_resource_type == "clusterprofiles":
                    version = (resource_doc.get("spec", {}) or {}).get("version")
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
                    "data": {"tags_before": before_tags, "tags_after": after_tags},
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


__all__ = ["manage_resource_tags"]
