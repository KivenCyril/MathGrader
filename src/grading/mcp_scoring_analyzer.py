import time
from typing import Any, Dict, Optional


class MCPScoringAnalyzer:
    def __init__(self, engine: Any):
        self.engine = engine

    def analyze(
        self,
        *,
        verdict_result: Dict[str, Any],
        question: str,
        truth: str,
        student: str,
        safe_max: float,
        question_type: str,
    ) -> Dict[str, Any]:
        grade_cfg = (self.engine.config.get("langchain", {}) or {}).get("grade", {}) or {}
        analysis_cfg = (grade_cfg.get("scoring_analysis") or {}) if isinstance(grade_cfg.get("scoring_analysis"), dict) else {}
        enabled = bool(analysis_cfg.get("enabled", False))
        tool_name = str(analysis_cfg.get("tool_name") or "").strip()
        if not enabled:
            return {"enabled": False, "used": False, "reason": "mcp_scoring_disabled"}
        if not tool_name:
            return {"enabled": True, "used": False, "reason": "missing_tool_name"}

        tool_map = self.engine.tool_hub.get_tool_map([tool_name])
        handler = tool_map.get(tool_name)
        if handler is None:
            return {"enabled": True, "used": False, "toolName": tool_name, "reason": "tool_not_found"}

        details = verdict_result.get("details") if isinstance(verdict_result.get("details"), dict) else {}
        solver_output = details.get("solver_output") if isinstance(details.get("solver_output"), dict) else {}
        supervisor_output = details.get("supervisor_output") if isinstance(details.get("supervisor_output"), dict) else {}
        payload = {
            "question": str(question or ""),
            "truth": str(truth or ""),
            "student": str(student or ""),
            "question_type": str(question_type or ""),
            "max_score": float(safe_max),
            "correct": bool(verdict_result.get("correct", False)),
            "reason": str(verdict_result.get("reason") or ""),
            "solver_output": solver_output,
            "supervisor_output": supervisor_output,
        }

        started_at = time.perf_counter()
        try:
            raw_result = handler(**payload)
            parsed = self._parse_result(raw_result)
            scoring = parsed.get("scoring") if isinstance(parsed.get("scoring"), dict) else parsed
            if not isinstance(scoring, dict):
                return {
                    "enabled": True,
                    "used": False,
                    "toolName": tool_name,
                    "reason": "invalid_result_format",
                    "rawResult": str(raw_result)[:400],
                    "timingMs": self.engine._elapsed_ms(started_at),
                }
            return {
                "enabled": True,
                "used": True,
                "toolName": tool_name,
                "reason": "ok",
                "rawResult": str(raw_result)[:400],
                "scoring": scoring,
                "timingMs": self.engine._elapsed_ms(started_at),
            }
        except Exception as e:
            return {
                "enabled": True,
                "used": False,
                "toolName": tool_name,
                "reason": f"tool_call_failed: {e}",
                "timingMs": self.engine._elapsed_ms(started_at),
            }

    def _parse_result(self, raw_result: Any) -> Dict[str, Any]:
        if isinstance(raw_result, dict):
            return raw_result
        if raw_result is None:
            return {}
        return self.engine._parse_json(str(raw_result))
