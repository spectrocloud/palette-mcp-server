# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from fastmcp import Context
from pydantic import BaseModel

from context import MCPSessionContext
from tracing import safe_set_span_status


def get_session_context(ctx: Context) -> MCPSessionContext:
    """Helper function to get our custom MCP session context from FastMCP context."""
    return ctx.fastmcp.session_context


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
    """Type definition for MCP tool results."""

    content: list[dict]
    isError: bool


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects."""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def mask_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Masks sensitive data by only showing the last 8 characters."""
    masked = data.copy()
    if "api_key" in masked:
        api_key = masked["api_key"]
        masked["api_key"] = (
            f"{'*' * (len(api_key) - 8)}{api_key[-8:]}" if len(api_key) > 8 else api_key
        )
    return masked
