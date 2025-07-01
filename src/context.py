from dataclasses import dataclass
from typing import Optional, Dict



@dataclass
class PaletteConfig:
    """Configuration for Palette Cloud API"""
    host: str
    apikey: str
    default_project_id: Optional[str] = None
    allow_dangerous_actions: bool = False

@dataclass
class Kubeconfig:
    """Kubeconfig path information"""
    path: Optional[str] = None
    
    def set_path(self, path: str) -> None:
        """Set the kubeconfig path"""
        self.path = path
    
    def clear(self) -> None:
        """Clear the kubeconfig path"""
        self.path = None
    
    def is_set(self) -> bool:
        """Check if kubeconfig path is set"""
        return self.path is not None

class MCPSessionContext:
    """Custom session context object for Palette MCP Server
    
    JSON Structure for developers:
    {
        "config": {
            "host": "api.spectrocloud.com",
            "apikey": "palette_***************abc123",
            "default_project_id": "6356fc6e381bfda21b2859c6",
            "allow_dangerous_actions": true
        },
        "kubeconfig": {
            "path": "/tmp/kubeconfig_cluster_abc123.yaml"
        }
    }
    
    Access patterns:
    - session_ctx.config.host
    - session_ctx.config.apikey
    - session_ctx.config.default_project_id
    - session_ctx.config.allow_dangerous_actions
    - session_ctx.kubeconfig.path
    - session_ctx.kubeconfig.set_path(path)
    - session_ctx.kubeconfig.is_set()
    """
    
    def __init__(self, host: str, apikey: str, default_project_id: Optional[str] = None, allow_dangerous_actions: bool = False):
        self.config = PaletteConfig(
            host=host,
            apikey=apikey,
            default_project_id=default_project_id,
            allow_dangerous_actions=allow_dangerous_actions
        )
        self.kubeconfig = Kubeconfig()
    
    def get_api_key(self, override: Optional[str] = None) -> str:
        """Get API key with optional override"""
        return override or self.config.apikey
    
    def get_project_id(self, override: Optional[str] = None) -> Optional[str]:
        """Get project ID with optional override"""
        return override or self.config.default_project_id
    
    def get_host(self) -> str:
        """Get Palette host"""
        return self.config.host 
    
    def is_dangerous_actions_allowed(self) -> bool:
        """Check if dangerous actions are allowed"""
        return self.config.allow_dangerous_actions 