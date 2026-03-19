from typing import Any, Dict, List


def _clip_text(value: Any, limit: int = 120) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def extract_lines(value: Any, limit: int = 3, clip: int = 120) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    out = []
    for line in lines[:limit]:
        clipped = _clip_text(line, clip)
        if clipped:
            out.append(clipped)
    return out


def summarize_tool_trace(tool_trace: List[Dict[str, Any]], limit: int = 2) -> List[str]:
    out: List[str] = []
    for item in (tool_trace or [])[:limit]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "tool").strip() or "tool"
        result = _clip_text(item.get("result") or "", 80)
        timing_ms = item.get("timing_ms")
        note = f"调用工具 {name}"
        if result:
            note += f"：{result}"
        if timing_ms is not None:
            note += f"（{timing_ms} ms）"
        out.append(note)
    return out


def append_notes(stage: Dict[str, Any], *notes: str) -> None:
    current = stage.get("notes")
    if not isinstance(current, list):
        current = []
        stage["notes"] = current
    for note in notes:
        text = str(note or "").strip()
        if text:
            current.append(text)

