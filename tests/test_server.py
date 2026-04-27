# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import os
import sys
import types


def test_server_disables_tracing_on_malformed_phoenix_endpoint(monkeypatch):
    src_dir = Path(__file__).resolve().parents[1] / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    class DummyLogger:
        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

    fastmcp_mod = types.ModuleType("fastmcp")
    fastmcp_mod.FastMCP = type("FastMCP", (), {})
    fastmcp_mod.Context = type("Context", (), {})
    fastmcp_util_mod = types.ModuleType("fastmcp.utilities")
    fastmcp_logging_mod = types.ModuleType("fastmcp.utilities.logging")
    fastmcp_logging_mod.get_logger = lambda _name: DummyLogger()

    context_mod = types.ModuleType("context")
    context_mod.MCPSessionContext = type("MCPSessionContext", (), {})

    tools_mod = types.ModuleType("tools")
    tools_mod.gather_or_delete_clusters = lambda *args, **kwargs: None
    tools_mod.gather_or_delete_clusterprofiles = lambda *args, **kwargs: None
    tools_mod.getKubeconfig = lambda *args, **kwargs: None
    tools_mod.search_and_manage_resource_tags = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "fastmcp", fastmcp_mod)
    monkeypatch.setitem(sys.modules, "fastmcp.utilities", fastmcp_util_mod)
    monkeypatch.setitem(sys.modules, "fastmcp.utilities.logging", fastmcp_logging_mod)
    monkeypatch.setitem(sys.modules, "context", context_mod)
    monkeypatch.setitem(sys.modules, "tools", tools_mod)

    helpers_module_path = src_dir / "helpers.py"
    helpers_spec = spec_from_file_location("helpers", helpers_module_path)
    assert helpers_spec and helpers_spec.loader is not None
    helpers_module = module_from_spec(helpers_spec)
    helpers_spec.loader.exec_module(helpers_module)
    monkeypatch.setitem(sys.modules, "helpers", helpers_module)

    monkeypatch.setattr(
        helpers_module.os.path,
        "exists",
        lambda path: path == "/.dockerenv",
        raising=True,
    )
    monkeypatch.setenv("SPECTROCLOUD_APIKEY", "test-api-key")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:not-a-port")

    server_module_path = src_dir / "server.py"
    server_spec = spec_from_file_location(
        "palette_server_under_test", server_module_path
    )
    assert server_spec and server_spec.loader is not None
    server_module = module_from_spec(server_spec)
    server_spec.loader.exec_module(server_module)

    assert os.environ.get("PHOENIX_COLLECTOR_ENDPOINT") is None
