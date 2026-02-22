from typing import Dict, List, Callable, Any


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._handlers: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, tool_def: Dict[str, Any], handler: Callable[..., Any]):
        self._tools[name] = tool_def
        self._handlers[name] = handler

    def get_tools(self, names: List[str]) -> List[Dict[str, Any]]:
        return [self._tools[n] for n in names if n in self._tools]

    def get_tool_map(self, names: List[str]) -> Dict[str, Callable[..., Any]]:
        return {n: self._handlers[n] for n in names if n in self._handlers}
