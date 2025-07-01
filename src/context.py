from dataclasses import dataclass
from typing import Optional

@dataclass
class PaletteConfig:
    """Configuration for Palette Cloud API"""
    host: str
    apikey: str
    default_project_id: Optional[str] = None

class PaletteContext:
    """Custom context object for Palette MCP Server"""
    
    def __init__(self, host: str, apikey: str, default_project_id: Optional[str] = None):
        self.config = PaletteConfig(
            host=host,
            apikey=apikey,
            default_project_id=default_project_id
        )
    
    def get_api_key(self, override: Optional[str] = None) -> str:
        """Get API key with optional override"""
        return override or self.config.apikey
    
    def get_project_id(self, override: Optional[str] = None) -> Optional[str]:
        """Get project ID with optional override"""
        return override or self.config.default_project_id
    
    def get_host(self) -> str:
        """Get Palette host"""
        return self.config.host 