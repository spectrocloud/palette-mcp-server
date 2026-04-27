# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import json
from typing import Annotated, Any, Dict, List, Optional

from fastmcp import Context
from pydantic import Field

from helpers import build_headers, palette_api_request
from tracing import create_span, safe_set_input, safe_set_output, safe_set_tool
from tools.common import (
    MCPResult,
    get_session_context,
    mask_sensitive_data,
    safe_set_span_status,
)


def _compact_pack_list(pack: Dict[str, Any]) -> Dict[str, Any]:
    """Compact view for items returned by POST /v1/packs/search (spec-wrapped)."""
    spec = pack.get("spec", {}) or {}
    registries: List[Dict[str, Any]] = spec.get("registries", []) or []
    return {
        "name": spec.get("name"),
        "displayName": spec.get("displayName"),
        "layer": spec.get("layer"),
        "type": spec.get("type"),
        "cloudTypes": spec.get("cloudTypes", []),
        "registries": [
            {
                "registryUid": r.get("uid"),
                "latestPackUid": r.get("latestPackUid"),
                "latestVersion": r.get("latestVersion"),
            }
            for r in registries
        ],
    }


def _compact_pack_get(pack: Dict[str, Any]) -> Dict[str, Any]:
    """Compact view for GET /v1/packs/{uid} — full response with packValues omitted."""
    return {k: v for k, v in pack.items() if k != "packValues"}


async def _search_packs(
    palette_host: str,
    headers: Dict[str, Any],
    pack_name: Optional[str],
    compact: bool,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "sort": [{"field": "layer", "order": "asc"}],
    }

    if pack_name:
        body["filter"] = {
            "displayName": {"contains": pack_name, "ignoreCase": True},
        }

    res = await palette_api_request(
        palette_host=palette_host,
        method="POST",
        path="/v1/packs/search",
        headers=headers,
        body=body,
    )

    json_data = res.json()
    items = json_data.get("items") or []
    listmeta = json_data.get("listmeta") or {}

    processed = [_compact_pack_list(p) if compact else p for p in items]

    return {
        "packs": {
            "items": processed,
            "returned_count": len(processed),
            "total_count": listmeta.get("count"),
            "compact": compact,
        }
    }


async def _get_pack_by_uid(
    palette_host: str,
    headers: Dict[str, Any],
    pack_uid: str,
    compact: bool,
) -> Dict[str, Any]:
    res = await palette_api_request(
        palette_host=palette_host,
        method="GET",
        path=f"/v1/packs/{pack_uid}",
        headers=headers,
    )

    pack = res.json()
    return {
        "pack": _compact_pack_get(pack) if compact else pack,
        "compact": compact,
    }


async def search_gather_packs(
    ctx: Context,
    action: Annotated[
        str,
        Field(
            description="The operation to perform: 'list' to search packs, 'get' to retrieve a specific pack by UID. Required."
        ),
    ],
    pack_uid: Annotated[
        Optional[str],
        Field(
            description="The UID of the pack to retrieve. Required when action is 'get'."
        ),
    ] = None,
    pack_name: Annotated[
        Optional[str],
        Field(
            description="Filter packs by display name. Case-insensitive contains match. Used only for 'list' action. Optional."
        ),
    ] = None,
    compact: Annotated[
        Optional[bool],
        Field(
            description="If True, return a compact payload. For 'list': name, displayName, cloudTypes, layer, type, registry uid/latestVersion. For 'get': all fields except YAML values. Default is True. Optional."
        ),
    ] = True,
    project_id: Annotated[
        Optional[str], Field(description="The ID of the project. Optional.")
    ] = None,
    api_key: Annotated[
        Optional[str], Field(description="The API key. Optional.")
    ] = None,
) -> MCPResult:
    """Search for packs or retrieve a specific pack in Palette. Use action='list' to search packs by display name, action='get' to fetch a specific pack by UID. List results are sorted by layer ascending. Get returns full pack detail; compact=True strips YAML values."""
    session_ctx = get_session_context(ctx)

    with create_span("search_gather_packs") as span:
        safe_set_tool(
            span,
            name="search_gather_packs",
            description="Search for packs or retrieve a specific pack in Palette. Start with list to search packs by display name, then use get to retrieve a specific pack by UID.",
            parameters={
                "action": {
                    "type": "string",
                    "description": "The operation: 'list' or 'get'",
                },
                "pack_uid": {
                    "type": "string",
                    "description": "The UID of the pack (required for get)",
                },
                "pack_name": {
                    "type": "string",
                    "description": "Filter packs by display name (list only)",
                },
                "compact": {
                    "type": "boolean",
                    "description": "If True, return compact payload. If False, return full detail. In list, this returns only name, displayName, cloudTypes, layer, type, registry uid/latestVersion. In get, this returns all fields except pack YAML values, including the YAML presets and readme.",
                },
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project (optional)",
                },
                "api_key": {"type": "string", "description": "The API key (optional)"},
            },
        )

        if compact is None:
            compact = True

        resolved_api_key = session_ctx.get_api_key(api_key)
        resolved_project_id = session_ctx.get_project_id(project_id)
        palette_host = session_ctx.get_host()

        safe_set_input(
            span,
            {
                "action": action,
                "pack_uid": pack_uid,
                "pack_name": pack_name,
                "compact": compact,
                **mask_sensitive_data({"api_key": resolved_api_key}),
            },
        )

        if action not in ["list", "get"]:
            error_msg = f"Error: Invalid action '{action}'. Only 'list' and 'get' are allowed. Start with list to search packs by display name, then use get to retrieve a specific pack by UID."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        if action == "get" and not pack_uid:
            error_msg = "Error: The 'get' action requires a pack_uid. Use action='list' first to find the pack UID."
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        if not resolved_api_key:
            error_msg = "Error: No api_key provided and no default API key configured"
            safe_set_output(span, {"error": error_msg})
            safe_set_span_status(span, "ERROR", error_msg)
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        try:
            headers = build_headers(
                api_key=resolved_api_key,
                project_id=resolved_project_id,
                include_content_type=True,
            )

            if action == "list":
                data = await _search_packs(palette_host, headers, pack_name, compact)
            else:
                assert pack_uid is not None
                data = await _get_pack_by_uid(palette_host, headers, pack_uid, compact)

            safe_set_output(span, data)
            safe_set_span_status(span, "OK")
            return {
                "content": [{"type": "text", "text": json.dumps(data, indent=2)}],
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


__all__ = ["search_gather_packs"]
