from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types


def _load_server_module(monkeypatch, *, host=None, apikey="test-api-key", default_project_id=None, allow_dangerous=None):
    for key in [
        "SPECTROCLOUD_HOST",
        "SPECTROCLOUD_APIKEY",
        "SPECTROCLOUD_DEFAULT_PROJECT_ID",
        "ALLOW_DANGEROUS_ACTIONS",
        "PHOENIX_COLLECTOR_ENDPOINT",
    ]:
        monkeypatch.delenv(key, raising=False)

    if host is not None:
        monkeypatch.setenv("SPECTROCLOUD_HOST", host)
    if apikey is not None:
        monkeypatch.setenv("SPECTROCLOUD_APIKEY", apikey)
    if default_project_id is not None:
        monkeypatch.setenv("SPECTROCLOUD_DEFAULT_PROJECT_ID", default_project_id)
    if allow_dangerous is not None:
        monkeypatch.setenv("ALLOW_DANGEROUS_ACTIONS", allow_dangerous)

    class DummyLogger:
        def info(self, *_args, **_kwargs):
            pass

        def warning(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

    class FakeFastMCP:
        def __init__(self, name, version=None):
            self.name = name
            self.version = version
            self.registered_tools = []
            self.session_context = None

        def tool(self):
            def register(func):
                self.registered_tools.append(func)
                return func

            return register

    fastmcp_mod = types.ModuleType("fastmcp")
    fastmcp_mod.FastMCP = FakeFastMCP
    fastmcp_mod.Context = type("Context", (), {})
    fastmcp_util_mod = types.ModuleType("fastmcp.utilities")
    fastmcp_logging_mod = types.ModuleType("fastmcp.utilities.logging")
    fastmcp_logging_mod.get_logger = lambda _name: DummyLogger()

    monkeypatch.setitem(sys.modules, "fastmcp", fastmcp_mod)
    monkeypatch.setitem(sys.modules, "fastmcp.utilities", fastmcp_util_mod)
    monkeypatch.setitem(sys.modules, "fastmcp.utilities.logging", fastmcp_logging_mod)

    module_path = Path(__file__).resolve().parents[1] / "src" / "server.py"
    spec = spec_from_file_location("palette_server_wiring_under_test", module_path)
    assert spec and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_server_uses_default_host_when_env_is_missing(monkeypatch):
    server = _load_server_module(monkeypatch, host=None, apikey="key")
    assert server.palette_host == "api.spectrocloud.com"


def test_server_reads_allow_dangerous_actions_flag(monkeypatch):
    server = _load_server_module(monkeypatch, allow_dangerous="1", apikey="key")
    assert server.allow_dangerous_actions is True


def test_create_mcp_registers_safe_tools_and_sets_session_context(monkeypatch):
    server = _load_server_module(
        monkeypatch,
        host="palette.example.com",
        apikey="my-key",
        default_project_id="project-abc",
        allow_dangerous="0",
    )

    mcp = server.create_mcp()

    assert [tool.__name__ for tool in mcp.registered_tools] == [
        "gather_or_delete_clusterprofiles",
        "gather_or_delete_clusters",
        "getKubeconfig",
        "search_and_manage_resource_tags",
    ]
    assert mcp.session_context.get_host() == "palette.example.com"
    assert mcp.session_context.get_api_key() == "my-key"
    assert mcp.session_context.get_project_id() == "project-abc"
