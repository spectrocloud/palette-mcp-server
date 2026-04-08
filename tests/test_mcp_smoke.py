import asyncio
import importlib
import json

import tools.clusters as clusters
import tools.tags as tags
from fastmcp import Client


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _load_runtime_server(monkeypatch):
    monkeypatch.setenv("SPECTROCLOUD_APIKEY", "test-api-key")
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    import server

    return importlib.reload(server)


def test_inmemory_mcp_smoke_clusters_dispatch(monkeypatch):
    async def fake_list_clusters(
        ctx, project_id=None, api_key=None, limit=25, continue_token=None, compact=True
    ):
        payload = {
            "clusters": {
                "items": [{"uid": "c-1", "name": "demo-cluster"}],
                "returned_count": 1,
                "limit": limit,
                "next_continue_token": None,
                "compact": compact,
            }
        }
        return {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "isError": False,
        }

    monkeypatch.setattr(clusters, "_list_clusters", fake_list_clusters, raising=True)
    server = _load_runtime_server(monkeypatch)

    async def run_call():
        mcp = server.create_mcp()
        async with Client(mcp) as client:
            return await client.call_tool(
                "gather_or_delete_clusters",
                {"action": "list", "limit": 5, "compact": True},
            )

    result = asyncio.run(run_call())
    outer_payload = json.loads(result.content[0].text)
    inner_payload = json.loads(outer_payload["content"][0]["text"])

    assert outer_payload["isError"] is False
    assert inner_payload["clusters"]["returned_count"] == 1
    assert inner_payload["clusters"]["items"][0]["uid"] == "c-1"


def test_inmemory_mcp_smoke_tags_dispatch(monkeypatch):
    async def fake_palette_api_request(
        palette_host,
        method,
        path,
        headers,
        params=None,
        body=None,
        allowed_status_codes=None,
    ):
        assert method == "GET"
        assert path == "/v1/spectroclusters/tags"
        return FakeResponse({"tags": ["env:prod", "team:platform"]})

    monkeypatch.setattr(
        tags, "palette_api_request", fake_palette_api_request, raising=True
    )
    server = _load_runtime_server(monkeypatch)

    async def run_call():
        mcp = server.create_mcp()
        async with Client(mcp) as client:
            return await client.call_tool(
                "search_and_manage_resource_tags",
                {"action": "list", "resource_type": "spectroclusters"},
            )

    result = asyncio.run(run_call())
    outer_payload = json.loads(result.content[0].text)
    inner_payload = json.loads(outer_payload["content"][0]["text"])

    assert outer_payload["isError"] is False
    assert inner_payload["data"]["tags"] == ["env:prod", "team:platform"]
