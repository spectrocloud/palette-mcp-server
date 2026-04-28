# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import asyncio
from types import SimpleNamespace

from context import MCPSessionContext
from tools import packs
from tools.packs import _compact_pack_get, _compact_pack_list


def _ctx(api_key: str = "test-api-key"):
    session = MCPSessionContext(
        host="api.spectrocloud.com",
        apikey=api_key,
        default_project_id="project-1",
        allow_dangerous_actions=False,
    )
    return SimpleNamespace(fastmcp=SimpleNamespace(session_context=session))


# ---------------------------------------------------------------------------
# Validation.
# ---------------------------------------------------------------------------


def test_invalid_action_returns_error():
    result = asyncio.run(packs.search_gather_packs(_ctx(), action="delete"))
    assert result["isError"] is True
    assert "Invalid action" in result["content"][0]["text"]


def test_get_without_pack_uid_returns_error():
    result = asyncio.run(packs.search_gather_packs(_ctx(), action="get"))
    assert result["isError"] is True
    assert "pack_uid" in result["content"][0]["text"]


def test_compact_none_normalized_to_true(monkeypatch):
    seen = {}

    async def fake_search(palette_host, headers, pack_name, compact):
        seen["compact"] = compact
        return {
            "packs": {
                "items": [],
                "returned_count": 0,
                "total_count": 0,
                "compact": compact,
            }
        }

    monkeypatch.setattr(packs, "_search_packs", fake_search, raising=True)

    result = asyncio.run(packs.search_gather_packs(_ctx(), action="list", compact=None))
    assert result["isError"] is False
    assert seen["compact"] is True


# ---------------------------------------------------------------------------
# Routing.
# ---------------------------------------------------------------------------


def test_list_routes_to_search_packs(monkeypatch):
    seen = {}

    async def fake_search(palette_host, headers, pack_name, compact):
        seen["pack_name"] = pack_name
        seen["compact"] = compact
        return {
            "packs": {
                "items": [],
                "returned_count": 0,
                "total_count": 0,
                "compact": compact,
            }
        }

    monkeypatch.setattr(packs, "_search_packs", fake_search, raising=True)

    result = asyncio.run(
        packs.search_gather_packs(
            _ctx(), action="list", pack_name="nginx", compact=True
        )
    )
    assert result["isError"] is False
    assert seen["pack_name"] == "nginx"
    assert seen["compact"] is True


def test_get_routes_to_get_pack_by_uid(monkeypatch):
    seen = {}

    async def fake_get(palette_host, headers, pack_uid, compact):
        seen["pack_uid"] = pack_uid
        seen["compact"] = compact
        return {"pack": {"name": "nginx"}, "compact": compact}

    monkeypatch.setattr(packs, "_get_pack_by_uid", fake_get, raising=True)

    result = asyncio.run(
        packs.search_gather_packs(
            _ctx(), action="get", pack_uid="abc-123", compact=False
        )
    )
    assert result["isError"] is False
    assert seen["pack_uid"] == "abc-123"
    assert seen["compact"] is False


# ---------------------------------------------------------------------------
# _compact_pack_list.
# ---------------------------------------------------------------------------


def test_compact_pack_list_extracts_spec_fields():
    pack = {
        "spec": {
            "name": "nginx",
            "displayName": "Nginx",
            "layer": "addon",
            "type": "oci",
            "cloudTypes": ["all"],
            "addonType": "ingress",
            "registries": [
                {
                    "uid": "reg-uid-1",
                    "latestPackUid": "pack-uid-1",
                    "latestVersion": "1.15.1",
                    "name": "Public Repo",
                    "scope": "system",
                },
            ],
        }
    }
    result = _compact_pack_list(pack)
    assert result["name"] == "nginx"
    assert result["displayName"] == "Nginx"
    assert result["layer"] == "addon"
    assert result["type"] == "oci"
    assert result["cloudTypes"] == ["all"]
    assert result["registries"] == [
        {
            "registryUid": "reg-uid-1",
            "latestPackUid": "pack-uid-1",
            "latestVersion": "1.15.1",
        }
    ]
    assert "addonType" not in result


def test_compact_pack_list_handles_missing_spec():
    result = _compact_pack_list({})
    assert result["name"] is None
    assert result["registries"] == []


def test_compact_pack_list_handles_null_registries():
    pack = {"spec": {"name": "test", "registries": None}}
    result = _compact_pack_list(pack)
    assert result["registries"] == []


# ---------------------------------------------------------------------------
# _compact_pack_get.
# ---------------------------------------------------------------------------


def test_compact_pack_get_omits_pack_values():
    pack = {
        "name": "nginx",
        "layer": "addon",
        "packValues": [
            {"packUid": "uid-1", "values": "pack:\n  namespace: ingress", "schema": []},
        ],
    }
    result = _compact_pack_get(pack)
    assert result["name"] == "nginx"
    assert result["layer"] == "addon"
    assert "packValues" not in result


def test_compact_pack_get_preserves_all_other_top_level_fields():
    pack = {
        "name": "nginx",
        "displayName": "Nginx",
        "layer": "addon",
        "type": "oci",
        "addonType": "ingress",
        "cloudTypes": ["all"],
        "registryUid": "reg-uid-1",
        "logoUrl": "https://example.com/logo.png",
        "tags": [
            {"tag": "1.x", "version": "1.15.1", "packUid": "uid-1", "parentTags": []}
        ],
        "packValues": [],
    }
    result = _compact_pack_get(pack)
    assert result["registryUid"] == "reg-uid-1"
    assert result["logoUrl"] == "https://example.com/logo.png"
    assert result["tags"] == pack["tags"]
    assert "packValues" not in result


def test_compact_pack_get_handles_missing_pack_values():
    pack = {"name": "nginx"}
    result = _compact_pack_get(pack)
    assert result["name"] == "nginx"
    assert "packValues" not in result
