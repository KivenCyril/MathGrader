from typing import Any, Dict, Optional


class MCPRubricResolver:
    def __init__(self, engine: Any):
        self.engine = engine

    def resolve(
        self,
        *,
        question_type: str,
        rubric_override: Optional[Any],
        rubric_text: Optional[str],
    ) -> Dict[str, Any]:
        grade_cfg = (self.engine.config.get("langchain", {}) or {}).get("grade", {}) or {}
        mcp_cfg = (grade_cfg.get("rubric_mcp") or {}) if isinstance(grade_cfg.get("rubric_mcp"), dict) else {}
        enabled = bool(mcp_cfg.get("enabled", False))
        parse_tool_name = str(mcp_cfg.get("parse_tool_name") or "").strip()
        validate_tool_name = str(mcp_cfg.get("validate_tool_name") or "").strip()
        normalized_type = str(question_type or "").strip().lower() or "complex"

        has_runtime_rubric = bool(
            (isinstance(rubric_override, dict) and rubric_override)
            or str(rubric_override or "").strip()
            or str(rubric_text or "").strip()
        )
        if not has_runtime_rubric:
            return {"enabled": enabled, "used": False, "reason": "no_runtime_rubric"}
        if not enabled:
            return {"enabled": False, "used": False, "reason": "rubric_mcp_disabled"}

        notes = []
        resolved_rubric = None
        parse_result: Dict[str, Any] = {}
        validate_result: Dict[str, Any] = {}

        try:
            if rubric_text and parse_tool_name:
                parse_handler = self._get_handler(parse_tool_name)
                parse_result = self._parse_result(
                    parse_handler(
                        text=str(rubric_text or ""),
                        question_type=normalized_type,
                    )
                )
                resolved_rubric = parse_result.get("rubric") if isinstance(parse_result.get("rubric"), dict) else None
                summary = str(parse_result.get("summary") or "").strip()
                if summary:
                    notes.append(summary)
            elif rubric_override is not None and validate_tool_name:
                validate_handler = self._get_handler(validate_tool_name)
                validate_result = self._parse_result(
                    validate_handler(
                        rubric=rubric_override,
                        question_type=normalized_type,
                    )
                )
                resolved_rubric = validate_result.get("rubric") if isinstance(validate_result.get("rubric"), dict) else None
            elif rubric_override is not None:
                resolved_rubric = self.engine.rubric_loader._normalize_rubric(
                    rubric_override,
                    question_type=normalized_type,
                    source="runtime_json",
                )

            if resolved_rubric and validate_tool_name:
                validate_handler = self._get_handler(validate_tool_name)
                validate_result = self._parse_result(
                    validate_handler(
                        rubric=resolved_rubric,
                        question_type=normalized_type,
                    )
                )
                validated = validate_result.get("rubric") if isinstance(validate_result.get("rubric"), dict) else None
                if validated:
                    resolved_rubric = validated
                issues = validate_result.get("issues")
                if isinstance(issues, list):
                    notes.extend([str(item).strip() for item in issues if str(item).strip()])

            if resolved_rubric:
                return {
                    "enabled": True,
                    "used": True,
                    "reason": "ok",
                    "toolName": parse_tool_name or validate_tool_name,
                    "parseToolName": parse_tool_name,
                    "validateToolName": validate_tool_name,
                    "rubric": resolved_rubric,
                    "notes": notes,
                    "parse": parse_result,
                    "validate": validate_result,
                }
            return {
                "enabled": True,
                "used": False,
                "reason": "mcp_returned_empty_rubric",
                "toolName": parse_tool_name or validate_tool_name,
                "parseToolName": parse_tool_name,
                "validateToolName": validate_tool_name,
                "notes": notes,
                "parse": parse_result,
                "validate": validate_result,
            }
        except Exception as e:
            return {
                "enabled": True,
                "used": False,
                "reason": f"tool_call_failed: {e}",
                "toolName": parse_tool_name or validate_tool_name,
                "parseToolName": parse_tool_name,
                "validateToolName": validate_tool_name,
                "notes": notes,
            }

    def _get_handler(self, tool_name: str):
        tool_map = self.engine.tool_hub.get_tool_map([tool_name])
        handler = tool_map.get(tool_name)
        if handler is None:
            raise ValueError(f"MCP tool not found: {tool_name}")
        return handler

    def _parse_result(self, raw_result: Any) -> Dict[str, Any]:
        if isinstance(raw_result, dict):
            return raw_result
        if raw_result is None:
            return {}
        return self.engine._parse_json(str(raw_result))
