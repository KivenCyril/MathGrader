import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests


@dataclass
class MCPServerConfig:
    name: str
    url: str
    timeout_sec: int = 20
    enabled: bool = True
    name_prefix: str = ""
    headers: Optional[Dict[str, str]] = None

    @classmethod
    def from_dict(cls, cfg: Dict[str, Any]) -> "MCPServerConfig":
        name = str(cfg.get("name") or "").strip()
        url = str(cfg.get("url") or "").strip()
        timeout_sec = int(cfg.get("timeout_sec", 20))
        enabled = bool(cfg.get("enabled", True))
        name_prefix = str(cfg.get("name_prefix") or name).strip()
        headers = cfg.get("headers")
        if not isinstance(headers, dict):
            headers = {}
        return cls(
            name=name,
            url=url,
            timeout_sec=max(3, timeout_sec),
            enabled=enabled,
            name_prefix=name_prefix,
            headers={str(k): str(v) for k, v in headers.items()},
        )


class MCPToolManager:
    """
    Minimal MCP tool adapter over JSON-RPC HTTP.
    Expected methods:
    - tools/list
    - tools/call
    """

    def __init__(self, servers: List[MCPServerConfig], refresh_sec: int = 90):
        self.servers = [s for s in servers if s.enabled and s.url]
        self.refresh_sec = max(10, int(refresh_sec))
        self._last_refresh_ts = 0.0
        self._tool_defs: Dict[str, Dict[str, Any]] = {}
        self._tool_handlers: Dict[str, Callable[..., Any]] = {}

    def _rpc(self, server: MCPServerConfig, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": method,
            "params": params or {},
        }
        headers = {"Content-Type": "application/json"}
        headers.update(server.headers or {})
        resp = requests.post(server.url, json=payload, headers=headers, timeout=server.timeout_sec)
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict) and body.get("error"):
            raise RuntimeError(f"MCP error from {server.name}: {body.get('error')}")
        if isinstance(body, dict):
            return body.get("result")
        return body

    def _normalize_list_result(self, result: Any) -> List[Dict[str, Any]]:
        if isinstance(result, dict):
            if isinstance(result.get("tools"), list):
                return [x for x in result["tools"] if isinstance(x, dict)]
            if isinstance(result.get("result"), list):
                return [x for x in result["result"] if isinstance(x, dict)]
            return []
        if isinstance(result, list):
            return [x for x in result if isinstance(x, dict)]
        return []

    def _to_openai_tool(self, alias_name: str, raw_tool: Dict[str, Any]) -> Dict[str, Any]:
        description = str(raw_tool.get("description") or f"MCP tool: {alias_name}")
        schema = (
            raw_tool.get("inputSchema")
            or raw_tool.get("input_schema")
            or raw_tool.get("parameters")
            or {"type": "object", "properties": {}}
        )
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": alias_name,
                "description": description,
                "parameters": schema,
            },
        }

    def _format_call_result(self, result: Any) -> str:
        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, list):
                parts: List[str] = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if text is not None:
                            parts.append(str(text))
                        else:
                            parts.append(json.dumps(item, ensure_ascii=False))
                    else:
                        parts.append(str(item))
                if parts:
                    return "\n".join(parts)
            structured = result.get("structuredContent")
            if structured is not None:
                return json.dumps(structured, ensure_ascii=False)
            return json.dumps(result, ensure_ascii=False)
        if isinstance(result, list):
            return json.dumps(result, ensure_ascii=False)
        return str(result)

    def _build_handler(self, server: MCPServerConfig, remote_name: str) -> Callable[..., Any]:
        def _handler(**kwargs):
            result = self._rpc(
                server,
                "tools/call",
                {"name": remote_name, "arguments": kwargs or {}},
            )
            return self._format_call_result(result)

        return _handler

    def refresh(self, force: bool = False):
        now = time.time()
        if (not force) and (now - self._last_refresh_ts < self.refresh_sec):
            return

        new_defs: Dict[str, Dict[str, Any]] = {}
        new_handlers: Dict[str, Callable[..., Any]] = {}

        for server in self.servers:
            try:
                list_result = self._rpc(server, "tools/list", {})
                remote_tools = self._normalize_list_result(list_result)
                for raw_tool in remote_tools:
                    remote_name = str(raw_tool.get("name") or "").strip()
                    if not remote_name:
                        continue
                    alias_name = (
                        f"{server.name_prefix}.{remote_name}" if server.name_prefix else remote_name
                    )
                    new_defs[alias_name] = self._to_openai_tool(alias_name, raw_tool)
                    new_handlers[alias_name] = self._build_handler(server, remote_name)
            except Exception as e:
                print(f"[MCP] Skip server {server.name}: {e}")

        self._tool_defs = new_defs
        self._tool_handlers = new_handlers
        self._last_refresh_ts = now

    def list_names(self) -> List[str]:
        self.refresh()
        return list(self._tool_defs.keys())

    def get_tools(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        self.refresh()
        if not names:
            return list(self._tool_defs.values())
        include_all = any(n in {"*", "mcp:*", "all"} for n in names)
        if include_all:
            return list(self._tool_defs.values())
        return [self._tool_defs[n] for n in names if n in self._tool_defs]

    def get_tool_map(self, names: Optional[List[str]] = None) -> Dict[str, Callable[..., Any]]:
        self.refresh()
        if not names:
            return dict(self._tool_handlers)
        include_all = any(n in {"*", "mcp:*", "all"} for n in names)
        if include_all:
            return dict(self._tool_handlers)
        return {n: self._tool_handlers[n] for n in names if n in self._tool_handlers}


def parse_mcp_servers(config: Dict[str, Any]) -> Tuple[List[MCPServerConfig], int]:
    mcp_cfg = config.get("mcp") or {}
    refresh_sec = int(mcp_cfg.get("refresh_sec", 90))
    servers_cfg = mcp_cfg.get("servers") or []
    if not isinstance(servers_cfg, list):
        servers_cfg = []
    servers = []
    for item in servers_cfg:
        if not isinstance(item, dict):
            continue
        server = MCPServerConfig.from_dict(item)
        if server.name and server.url and server.enabled:
            servers.append(server)
    return servers, max(10, refresh_sec)
