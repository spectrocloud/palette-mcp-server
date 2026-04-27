# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json
from types import SimpleNamespace

from context import MCPSessionContext
from tools import tags


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _ctx(allow_dangerous_actions: bool = False):
    session = MCPSessionContext(
        host="api.spectrocloud.com",
        apikey="test-api-key",
        default_project_id="project-1",
        allow_dangerous_actions=allow_dangerous_actions,
    )
    return SimpleNamespace(fastmcp=SimpleNamespace(session_context=session))


def test_tags_invalid_action_returns_error():
    result = asyncio.run(tags.search_and_manage_resource_tags(_ctx(), action="oops"))
    assert result["isError"] is True
    assert "Invalid action" in result["content"][0]["text"]


def test_tags_list_requires_resource_type():
    result = asyncio.run(tags.search_and_manage_resource_tags(_ctx(), action="list"))
    assert result["isError"] is True
    assert "requires 'resource_type'" in result["content"][0]["text"]


def test_tags_get_requires_uid():
    result = asyncio.run(
        tags.search_and_manage_resource_tags(
            _ctx(), action="get", resource_type="spectroclusters"
        )
    )
    assert result["isError"] is True
    assert "requires both 'resource_type' and 'uid'" in result["content"][0]["text"]


def test_tags_create_requires_tags_list():
    result = asyncio.run(
        tags.search_and_manage_resource_tags(
            _ctx(), action="create", resource_type="spectroclusters", uid="c-1"
        )
    )
    assert result["isError"] is True
    assert "requires 'tags' to be provided" in result["content"][0]["text"]


def test_tags_delete_requires_dangerous_actions_enabled():
    result = asyncio.run(
        tags.search_and_manage_resource_tags(
            _ctx(False),
            action="delete",
            resource_type="spectroclusters",
            uid="c-1",
            tags=["env:prod"],
        )
    )
    assert result["isError"] is True
    assert "not allowed" in result["content"][0]["text"]


def test_tags_list_spectroclusters_routes_to_tag_endpoint(monkeypatch):
    seen = {}

    async def fake_palette_api_request(
        palette_host,
        method,
        path,
        headers,
        params=None,
        body=None,
        allowed_status_codes=None,
    ):
        seen["palette_host"] = palette_host
        seen["method"] = method
        seen["path"] = path
        return FakeResponse({"tags": ["env:prod", "team:sre"]})

    monkeypatch.setattr(
        tags, "palette_api_request", fake_palette_api_request, raising=True
    )

    result = asyncio.run(
        tags.search_and_manage_resource_tags(
            _ctx(), action="list", resource_type="spectroclusters"
        )
    )
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] is False
    assert seen["method"] == "GET"
    assert seen["path"] == "/v1/spectroclusters/tags"
    assert payload["data"]["tags"] == ["env:prod", "team:sre"]


def test_tags_list_clusterprofiles_uses_profile_list_helper(monkeypatch):
    async def fake_list_profiles(
        ctx,
        project_id=None,
        api_key=None,
        limit=None,
        continue_token=None,
        compact=True,
    ):
        profile_payload = {
            "clusterProfiles": {
                "items": [
                    {"tags": ["env:dev", "owner:sre"]},
                    {"tags": ["owner:sre", "team:platform"]},
                ]
            }
        }
        return {
            "content": [{"type": "text", "text": json.dumps(profile_payload)}],
            "isError": False,
        }

    monkeypatch.setattr(
        tags, "_list_cluster_profiles", fake_list_profiles, raising=True
    )

    result = asyncio.run(
        tags.search_and_manage_resource_tags(
            _ctx(), action="list", resource_type="clusterprofiles"
        )
    )
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] is False
    assert payload["data"]["tags"] == ["env:dev", "owner:sre", "team:platform"]


def test_merge_tags_add_upserts_by_tag_key():
    before, after = tags.merge_tags(
        existing_tags=["env:dev", "owner:sre"],
        requested_tags=["env:prod", "team:platform"],
        operation="add",
    )
    assert before == ["env:dev", "owner:sre"]
    assert after == ["env:prod", "owner:sre", "team:platform"]


def test_merge_tags_remove_by_key_and_exact_value():
    before, after = tags.merge_tags(
        existing_tags=["env:prod", "owner:sre", "team:platform"],
        requested_tags=["owner", "team:platform"],
        operation="remove",
    )
    assert before == ["env:prod", "owner:sre", "team:platform"]
    assert after == ["env:prod"]


def test_merge_tags_rejects_invalid_operation():
    with_exception = None
    try:
        tags.merge_tags(existing_tags=["a"], requested_tags=["b"], operation="replace")
    except ValueError as exc:
        with_exception = exc

    assert with_exception is not None
    assert "Invalid operation" in str(with_exception)
