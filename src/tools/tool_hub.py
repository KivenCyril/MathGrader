from typing import Any, Callable, Dict, List, Optional

from src.tools.default_tools import build_default_registry
from src.tools.mcp_tool_manager import MCPToolManager, parse_mcp_servers
from src.tools.tool_registry import ToolRegistry


class ToolHub:
    """
    Unified tool provider:
    - local tools (ToolRegistry)
    - remote MCP tools (optional)
    """

    def __init__(self, local_registry: ToolRegistry, mcp_manager: Optional[MCPToolManager] = None):
        self.local_registry = local_registry
        self.mcp_manager = mcp_manager

    @classmethod
    def from_runtime_config(cls, runtime_config: Optional[Dict[str, Any]] = None) -> "ToolHub":
        local_registry = build_default_registry()
        runtime_config = runtime_config or {}
        servers, refresh_sec = parse_mcp_servers(runtime_config)
        mcp_manager = MCPToolManager(servers, refresh_sec=refresh_sec) if servers else None
        return cls(local_registry=local_registry, mcp_manager=mcp_manager)

    def list_names(self) -> List[str]:
        names = self.local_registry.list_names()
        if self.mcp_manager:
            names.extend(self.mcp_manager.list_names())
        return names

    def get_tools(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not names:
            out = self.local_registry.get_all_tools()
            if self.mcp_manager:
                out.extend(self.mcp_manager.get_tools())
            return out

        out = self.local_registry.get_tools(names)
        if self.mcp_manager:
            out.extend(self.mcp_manager.get_tools(names))
        return out

    def get_tool_map(self, names: Optional[List[str]] = None) -> Dict[str, Callable[..., Any]]:
        if not names:
            out = self.local_registry.get_all_tool_map()
            if self.mcp_manager:
                out.update(self.mcp_manager.get_tool_map())
            return out

        out = self.local_registry.get_tool_map(names)
        if self.mcp_manager:
            out.update(self.mcp_manager.get_tool_map(names))
        return out
