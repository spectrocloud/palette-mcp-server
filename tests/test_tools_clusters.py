# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json
from types import SimpleNamespace

from context import MCPSessionContext
from tools import clusters


def _ctx(allow_dangerous_actions: bool = False):
    session = MCPSessionContext(
        host="api.spectrocloud.com",
        apikey="test-api-key",
        default_project_id="project-1",
        allow_dangerous_actions=allow_dangerous_actions,
    )
    return SimpleNamespace(fastmcp=SimpleNamespace(session_context=session))


def test_clusters_invalid_action_returns_error():
    result = asyncio.run(clusters.gather_or_delete_clusters(_ctx(), action="oops"))
    assert result["isError"] is True
    assert "Invalid action" in result["content"][0]["text"]


def test_clusters_get_requires_uid():
    result = asyncio.run(clusters.gather_or_delete_clusters(_ctx(), action="get"))
    assert result["isError"] is True
    assert "requires a cluster UID" in result["content"][0]["text"]


def test_clusters_delete_requires_dangerous_actions_enabled():
    result = asyncio.run(
        clusters.gather_or_delete_clusters(_ctx(False), action="delete", uid="c-1")
    )
    assert result["isError"] is True
    assert "not allowed" in result["content"][0]["text"]


def test_clusters_list_caps_limit_to_fifty(monkeypatch):
    seen = {}

    async def fake_list(ctx, project_id, api_key, limit, continue_token, compact):
        seen["limit"] = limit
        return {"content": [{"type": "text", "text": '{"ok":true}'}], "isError": False}

    monkeypatch.setattr(clusters, "_list_clusters", fake_list, raising=True)

    result = asyncio.run(
        clusters.gather_or_delete_clusters(_ctx(), action="list", limit=999)
    )
    assert result["isError"] is False
    assert seen["limit"] == 50


def test_clusters_list_routes_to_active_list_helper(monkeypatch):
    called = {"active": False}

    async def fake_active(ctx, project_id, api_key, limit, continue_token, compact):
        called["active"] = True
        payload = {"clusters": {"returned_count": 1}}
        return {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "isError": False,
        }

    async def fail_regular(*_args, **_kwargs):
        raise AssertionError("_list_clusters should not be called")

    monkeypatch.setattr(clusters, "_list_active_clusters", fake_active, raising=True)
    monkeypatch.setattr(clusters, "_list_clusters", fail_regular, raising=True)

    result = asyncio.run(
        clusters.gather_or_delete_clusters(_ctx(), action="list", active_only=True)
    )
    assert called["active"] is True
    assert result["isError"] is False


def test_clusters_delete_routes_to_internal_delete_helper(monkeypatch):
    seen = {}

    async def fake_delete(ctx, uid, project_id, api_key, force_delete):
        seen["uid"] = uid
        seen["force_delete"] = force_delete
        return {
            "content": [{"type": "text", "text": '{"deleted":true}'}],
            "isError": False,
        }

    monkeypatch.setattr(clusters, "_delete_cluster_by_uid", fake_delete, raising=True)

    result = asyncio.run(
        clusters.gather_or_delete_clusters(
            _ctx(True), action="delete", uid="cluster-uid", force_delete=True
        )
    )
    assert result["isError"] is False
    assert seen == {"uid": "cluster-uid", "force_delete": True}
