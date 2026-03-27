from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

# Load the module from file to avoid package import side effects and editor path warnings.
context_module_path = Path(__file__).resolve().parents[1] / "src" / "context.py"
context_spec = spec_from_file_location("palette_context", context_module_path)
assert context_spec and context_spec.loader is not None
context_module = module_from_spec(context_spec)
context_spec.loader.exec_module(context_module)

Kubeconfig = context_module.Kubeconfig
MCPSessionContext = context_module.MCPSessionContext
PaletteConfig = context_module.PaletteConfig


def test_palette_config_defaults():
    cfg = PaletteConfig(host="api.spectrocloud.com", apikey="key")
    assert cfg.host == "api.spectrocloud.com"
    assert cfg.apikey == "key"
    assert cfg.default_project_id is None
    assert cfg.allow_dangerous_actions is False


def test_kubeconfig_set_and_clear():
    kubeconfig = Kubeconfig()
    assert kubeconfig.is_set() is False

    kubeconfig.set_path("/tmp/test.kubeconfig")
    assert kubeconfig.is_set() is True
    assert kubeconfig.path == "/tmp/test.kubeconfig"

    kubeconfig.clear()
    assert kubeconfig.is_set() is False
    assert kubeconfig.path is None


def test_session_context_accessors_and_overrides():
    session = MCPSessionContext(
        host="api.spectrocloud.com",
        apikey="default-key",
        default_project_id="project-1",
        allow_dangerous_actions=True,
    )

    assert session.get_host() == "api.spectrocloud.com"
    assert session.get_api_key() == "default-key"
    assert session.get_api_key("override-key") == "override-key"
    assert session.get_project_id() == "project-1"
    assert session.get_project_id("project-2") == "project-2"
    assert session.is_dangerous_actions_allowed() is True


def test_session_context_contains_kubeconfig_object():
    session = MCPSessionContext(host="api.spectrocloud.com", apikey="key")
    assert session.kubeconfig.is_set() is False
    session.kubeconfig.set_path("/tmp/cluster.kubeconfig")
    assert session.kubeconfig.path == "/tmp/cluster.kubeconfig"
