import json
import time
from typing import Any, Dict, List, Optional, Tuple

from src.common.coercion import coerce_positive_int
from src.llm_clients.base_client import LLMClient

try:
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
except Exception:
    HumanMessage = None
    SystemMessage = None
    ToolMessage = None
    ChatOpenAI = None

def _system_msg(self, content: str):
    if SystemMessage is not None:
        return SystemMessage(content=content)
    return {"role": "system", "content": str(content)}

def _human_msg(self, content: str):
    if HumanMessage is not None:
        return HumanMessage(content=content)
    return {"role": "user", "content": str(content)}

def _tool_msg(self, content: str, tool_call_id: str):
    if ToolMessage is not None:
        return ToolMessage(content=str(content), tool_call_id=str(tool_call_id))
    return {"role": "tool", "content": str(content), "tool_call_id": str(tool_call_id)}

def _normalize_answer(self, value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    s = s.translate(
        str.maketrans(
            {
                "\uFF08": "(",
                "\uFF09": ")",
                "\uFF0C": ",",
                "\u3002": ".",
            }
        )
    )
    return "".join(s.split()).lower()

def _parse_json(self, content: str) -> Dict[str, Any]:
    text = str(content or "").strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end >= start:
        text = text[start : end + 1]
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return {}
    return {}

def _safe_prompt(self, key: str, **kwargs) -> str:
    name = self.prompt_keys[key]
    try:
        return self.prompt_loader.load(name, **kwargs)
    except Exception as e:
        return f"[PromptMissing:{name}] {e}\n{json.dumps(kwargs, ensure_ascii=False)}"

def _get_model_alias(self, section: str, key: str, fallback_role: str, override: Optional[str] = None) -> str:
    if override:
        return str(override).strip()
    lc_cfg = self.config.get("langchain", {}) or {}
    sec = lc_cfg.get(section, {}) or {}
    alias = str(sec.get(key) or "").strip()
    if alias:
        return alias
    role_alias = str((self.config.get("roles", {}) or {}).get(fallback_role) or "").strip()
    if role_alias:
        return role_alias
    models = list((self.config.get("models", {}) or {}).keys())
    return models[0] if models else ""

def _get_model_config(self, alias: str) -> Dict[str, Any]:
    return dict((self.config.get("models", {}) or {}).get(alias, {}) or {})

def _collect_tools(self, names: Optional[List[str]] = None) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    defs = {}
    handlers = {}

    hub_defs = self.tool_hub.get_tools(names)
    hub_map = self.tool_hub.get_tool_map(names)
    for item in hub_defs:
        name = ((item.get("function") or {}).get("name") or "").strip()
        if name:
            defs[name] = item
    handlers.update(hub_map)

    if names:
        defs.update({name: self.local_tool_defs[name] for name in names if name in self.local_tool_defs})
        handlers.update({name: self.local_tool_handlers[name] for name in names if name in self.local_tool_handlers})
    else:
        defs.update(self.local_tool_defs)
        handlers.update(self.local_tool_handlers)
    return defs, handlers

def _expand_tool_names(self, names: List[str], all_names: List[str]) -> List[str]:
    out = []
    seen = set()
    for name in names:
        n = str(name).strip()
        if not n:
            continue
        if n in {"*", "all"}:
            for item in all_names:
                if item not in seen:
                    seen.add(item)
                    out.append(item)
            continue
        if n == "mcp:*":
            for item in all_names:
                if item in {"calculate", "ocr_math", "img2latex", "eval_expr", "verify_step", "find_counterexample"}:
                    continue
                if item not in seen:
                    seen.add(item)
                    out.append(item)
            continue
        if n in all_names and n not in seen:
            seen.add(n)
            out.append(n)
    return out

def _resolve_tool_names(self, section: str) -> List[str]:
    lc_cfg = self.config.get("langchain", {}) or {}
    sec_cfg = lc_cfg.get(section, {}) or {}
    default_names = [
            "calculate",
            "ocr_math",
            "img2latex",
            "eval_expr",
            "verify_step",
            "verify_equation_setup",
            "find_counterexample",
      ]
    names = sec_cfg.get("tools") or default_names
    if not isinstance(names, list):
        names = default_names
    resolved = [str(x).strip() for x in names if str(x).strip()]
    # Rubric MCP tools are invoked explicitly by the rubric/scoring pipeline.
    # Keep regular solve/grade tool resolution local-first to avoid probing MCP
    # servers on every request.
    if section in {"solve", "grade"}:
        resolved = [name for name in resolved if name != "mcp:*"]
    return resolved

def _coerce_positive_int(self, value: Any, default: Optional[int] = None) -> Optional[int]:
    return coerce_positive_int(value, default)

def _build_langchain_model(self, cfg: Dict[str, Any], temperature: float, max_tokens: Optional[int] = None):
    if ChatOpenAI is None:
        return None
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        return None
    base_url = str(cfg.get("base_url") or "https://api.openai.com/v1").strip()
    model_name = str(cfg.get("model_name") or "gpt-4o-mini").strip()
    kwargs = {
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "timeout": 60,
        "max_retries": 1,
    }
    safe_max_tokens = self._coerce_positive_int(max_tokens)
    if safe_max_tokens is not None:
        kwargs["max_tokens"] = safe_max_tokens
    return ChatOpenAI(**kwargs)

def _lc_content_to_text(self, content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                txt = item.get("text")
                if txt is not None:
                    parts.append(str(txt))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content or "")

def _to_openai_messages(self, messages: List[Any]) -> List[Dict[str, Any]]:
    out = []
    for msg in messages:
        if isinstance(msg, dict):
            role = str(msg.get("role") or "user")
            payload = {"role": role, "content": str(msg.get("content") or "")}
            if role == "tool":
                payload["tool_call_id"] = str(msg.get("tool_call_id") or "")
            if role == "assistant" and msg.get("tool_calls"):
                payload["tool_calls"] = msg.get("tool_calls")
            out.append(payload)
            continue
        mtype = getattr(msg, "type", "")
        content = self._lc_content_to_text(getattr(msg, "content", ""))
        if mtype == "system":
            out.append({"role": "system", "content": content})
        elif mtype == "human":
            out.append({"role": "user", "content": content})
        elif mtype == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": getattr(msg, "tool_call_id", ""),
                    "content": content,
                }
            )
        else:
            extra = {}
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                extra["tool_calls"] = tool_calls
            out.append({"role": "assistant", "content": content, **extra})
    return out

def _elapsed_ms(self, started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 2)

def _invoke_with_tools(
    self,
    model_alias: str,
    messages: List[Any],
    tool_names: List[str],
    enable_tools: bool,
    temperature: float,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    started_at = time.perf_counter()
    cfg = self._get_model_config(model_alias)
    llm = self._build_langchain_model(cfg, temperature, max_tokens=max_tokens)
    metadata = {
        "timing_ms": 0.0,
        "tool_rounds": 0,
        "tool_call_count": 0,
        "selected_tool_count": 0,
        "selected_tools": [],
        "used_langchain_runtime": llm is not None,
        "llm_round_timings_ms": [],
        "max_tokens": self._coerce_positive_int(max_tokens, default=0),
    }

    if not enable_tools:
        if llm is None:
            fallback_client = LLMClient(cfg)
            data = fallback_client.chat_completion(
                self._to_openai_messages(messages),
                temperature=temperature,
                tools=None,
                tool_map=None,
                max_tool_rounds=0,
                max_tokens=max_tokens,
            )
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            metadata["timing_ms"] = self._elapsed_ms(started_at)
            perf = dict((data.get("_perf") or {}))
            if perf:
                metadata["tool_rounds"] = perf.get("tool_rounds", 0)
                metadata["tool_call_count"] = perf.get("tool_call_count", 0)
                metadata["llm_round_timings_ms"] = perf.get("llm_round_timings_ms", metadata["llm_round_timings_ms"])
                metadata["timing_ms"] = perf.get("timing_ms", metadata["timing_ms"])
            return {"content": str(content), "tool_trace": [], "model_alias": model_alias, "perf": metadata}

        llm_started_at = time.perf_counter()
        ai = llm.invoke(messages)
        metadata["llm_round_timings_ms"] = [self._elapsed_ms(llm_started_at)]
        metadata["timing_ms"] = self._elapsed_ms(started_at)
        return {
            "content": self._lc_content_to_text(getattr(ai, "content", "")),
            "tool_trace": [],
            "model_alias": model_alias,
            "perf": metadata,
        }

    all_defs, all_handlers = self._collect_tools(tool_names)
    all_names = list(all_defs.keys())
    selected_names = self._expand_tool_names(tool_names, all_names)
    selected_defs = [all_defs[n] for n in selected_names if n in all_defs]
    selected_handlers = {n: all_handlers[n] for n in selected_names if n in all_handlers}
    metadata["selected_tool_count"] = len(selected_names)
    metadata["selected_tools"] = selected_names

    if llm is None:
        fallback_client = LLMClient(cfg)
        data = fallback_client.chat_completion(
            self._to_openai_messages(messages),
            temperature=temperature,
            tools=selected_defs if enable_tools else None,
            tool_map=selected_handlers if enable_tools else None,
            max_tool_rounds=self.max_tool_rounds,
            max_tokens=max_tokens,
        )
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        metadata["timing_ms"] = self._elapsed_ms(started_at)
        perf = dict((data.get("_perf") or {}))
        if perf:
            metadata["tool_rounds"] = perf.get("tool_rounds", metadata["tool_rounds"])
            metadata["tool_call_count"] = perf.get("tool_call_count", metadata["tool_call_count"])
            metadata["llm_round_timings_ms"] = perf.get("llm_round_timings_ms", metadata["llm_round_timings_ms"])
            metadata["timing_ms"] = perf.get("timing_ms", metadata["timing_ms"])
        tool_trace = list(data.get("_tool_trace") or [])
        return {"content": str(content), "tool_trace": tool_trace, "model_alias": model_alias, "perf": metadata}

    if not selected_defs:
        llm_started_at = time.perf_counter()
        ai = llm.invoke(messages)
        metadata["llm_round_timings_ms"] = [self._elapsed_ms(llm_started_at)]
        metadata["timing_ms"] = self._elapsed_ms(started_at)
        return {
            "content": self._lc_content_to_text(getattr(ai, "content", "")),
            "tool_trace": [],
            "model_alias": model_alias,
            "perf": metadata,
        }

    runner = llm.bind_tools(selected_defs)
    convo = list(messages)
    trace = []
    final_ai = None

    for round_idx in range(self.max_tool_rounds + 1):
        llm_started_at = time.perf_counter()
        ai = runner.invoke(convo)
        metadata["llm_round_timings_ms"].append(self._elapsed_ms(llm_started_at))
        final_ai = ai
        convo.append(ai)
        tool_calls = getattr(ai, "tool_calls", []) or []
        if not tool_calls:
            break
        metadata["tool_rounds"] = round_idx + 1
        for tc in tool_calls:
            name = str(tc.get("name") or "").strip()
            args = tc.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if not isinstance(args, dict):
                args = {}

            handler = selected_handlers.get(name)
            tool_started_at = time.perf_counter()
            if handler is None:
                result = f"Error: tool {name} not found"
            else:
                try:
                    result = handler(**args)
                except Exception as e:
                    result = f"Error: tool {name} failed: {e}"

            metadata["tool_call_count"] = int(metadata["tool_call_count"]) + 1
            trace.append(
                {
                    "name": name,
                    "args": args,
                    "result": str(result)[:300],
                    "timing_ms": self._elapsed_ms(tool_started_at),
                }
            )
            convo.append(self._tool_msg(str(result), str(tc.get("id") or "")))

    content = self._lc_content_to_text(getattr(final_ai, "content", "") if final_ai else "")
    metadata["timing_ms"] = self._elapsed_ms(started_at)
    return {"content": content, "tool_trace": trace, "model_alias": model_alias, "perf": metadata}
