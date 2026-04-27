# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import asyncio
from types import SimpleNamespace

from context import MCPSessionContext
from tools import clusterprofiles


def _ctx(allow_dangerous_actions: bool = False):
    session = MCPSessionContext(
        host="api.spectrocloud.com",
        apikey="test-api-key",
        default_project_id="project-1",
        allow_dangerous_actions=allow_dangerous_actions,
    )
    return SimpleNamespace(fastmcp=SimpleNamespace(session_context=session))


def test_clusterprofiles_invalid_action_returns_error():
    result = asyncio.run(
        clusterprofiles.gather_or_delete_clusterprofiles(_ctx(), action="invalid")
    )
    assert result["isError"] is True
    assert "Invalid action" in result["content"][0]["text"]


def test_clusterprofiles_get_requires_uid():
    result = asyncio.run(
        clusterprofiles.gather_or_delete_clusterprofiles(_ctx(), action="get")
    )
    assert result["isError"] is True
    assert "requires a cluster profile UID" in result["content"][0]["text"]


def test_clusterprofiles_delete_requires_dangerous_actions_enabled():
    result = asyncio.run(
        clusterprofiles.gather_or_delete_clusterprofiles(
            _ctx(False), action="delete", uid="cp-1"
        )
    )
    assert result["isError"] is True
    assert "not allowed" in result["content"][0]["text"]


def test_clusterprofiles_list_caps_limit_to_fifty(monkeypatch):
    seen = {}

    async def fake_list(ctx, project_id, api_key, limit, continue_token, compact):
        seen["limit"] = limit
        return {"content": [{"type": "text", "text": '{"ok":true}'}], "isError": False}

    monkeypatch.setattr(
        clusterprofiles, "_list_cluster_profiles", fake_list, raising=True
    )

    result = asyncio.run(
        clusterprofiles.gather_or_delete_clusterprofiles(
            _ctx(), action="list", limit=200
        )
    )
    assert result["isError"] is False
    assert seen["limit"] == 50


def test_clusterprofiles_list_normalizes_none_compact_to_true(monkeypatch):
    seen = {}

    async def fake_list(ctx, project_id, api_key, limit, continue_token, compact):
        seen["compact"] = compact
        return {"content": [{"type": "text", "text": '{"ok":true}'}], "isError": False}

    monkeypatch.setattr(
        clusterprofiles, "_list_cluster_profiles", fake_list, raising=True
    )

    result = asyncio.run(
        clusterprofiles.gather_or_delete_clusterprofiles(
            _ctx(), action="list", compact=None
        )
    )
    assert result["isError"] is False
    assert seen["compact"] is True


def test_clusterprofiles_delete_routes_to_internal_delete_helper(monkeypatch):
    seen = {}

    async def fake_delete(ctx, uid, project_id, api_key):
        seen["uid"] = uid
        return {
            "content": [{"type": "text", "text": '{"deleted":true}'}],
            "isError": False,
        }

    monkeypatch.setattr(
        clusterprofiles, "_delete_cluster_profile_by_uid", fake_delete, raising=True
    )

    result = asyncio.run(
        clusterprofiles.gather_or_delete_clusterprofiles(
            _ctx(True), action="delete", uid="cp-uid"
        )
    )
    assert result["isError"] is False
    assert seen["uid"] == "cp-uid"
