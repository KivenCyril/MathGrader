import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.grading.rubric_loader import RubricLoader
from src.grading.scoring_rules import average_credit, clamp_ratio, extract_breakdown, extract_recommended_ratio, round_score


app = Flask(__name__)
rubric_loader = RubricLoader({})


def _jsonrpc_result(request_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _normalize_question_type(value: Any) -> str:
    return str(value or "").strip().lower() or "complex"


def _build_tool_list() -> List[Dict[str, Any]]:
    return [
        {
            "name": "parse_text",
            "description": "Parse teacher-provided rubric text into a normalized rubric JSON object.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "question_type": {"type": "string"},
                },
                "required": ["text"],
            },
        },
        {
            "name": "validate",
            "description": "Validate and normalize a rubric JSON object.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "rubric": {"type": "object"},
                    "question_type": {"type": "string"},
                },
                "required": ["rubric"],
            },
        },
        {
            "name": "score_analysis",
            "description": "Generate rubric-aware analytic scoring suggestions from grading evidence.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "truth": {"type": "string"},
                    "student": {"type": "string"},
                    "question_type": {"type": "string"},
                    "max_score": {"type": "number"},
                    "correct": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "rubric": {"type": "object"},
                    "solver_output": {"type": "object"},
                    "supervisor_output": {"type": "object"},
                },
            },
        },
    ]


def _parse_text(arguments: Dict[str, Any]) -> Dict[str, Any]:
    question_type = _normalize_question_type(arguments.get("question_type"))
    text = str(arguments.get("text") or "").strip()
    parsed = rubric_loader._parse_rubric_text(text, question_type=question_type)
    rubric = rubric_loader._normalize_rubric(parsed, question_type=question_type, source="mcp_parse_text")
    return {
        "valid": bool(rubric),
        "rubric": rubric,
        "summary": str(rubric.get("summary") or "").strip(),
        "notes": rubric_loader.notes(rubric),
    }


def _validate(arguments: Dict[str, Any]) -> Dict[str, Any]:
    question_type = _normalize_question_type(arguments.get("question_type"))
    rubric = rubric_loader._normalize_rubric(arguments.get("rubric"), question_type=question_type, source="mcp_validate")
    issues: List[str] = []
    if not rubric:
        issues.append("rubric_empty_or_invalid")
    dimensions = rubric.get("dimensions") if isinstance(rubric.get("dimensions"), list) else []
    if rubric and rubric.get("strategy") == "analytic" and not dimensions:
        issues.append("analytic_rubric_has_no_dimensions")
    return {
        "valid": bool(rubric) and not issues,
        "rubric": rubric,
        "issues": issues,
        "summary": str(rubric.get("summary") or "").strip(),
        "notes": rubric_loader.notes(rubric),
    }


def _detect_dimension_credit(label: str, base_ratio: float, correct: bool, reason: str, evidence_text: str) -> float:
    lowered = f"{label} {reason} {evidence_text}".lower()
    if correct:
        return 1.0
    if any(token in lowered for token in ["最终", "结论", "答案", "final", "result"]):
        if any(token in lowered for token in ["未给出最终答案", "最终错误", "答案错误", "incorrect final", "wrong answer"]):
            return min(base_ratio, 0.2)
        return min(max(base_ratio, 0.3), 0.6)
    if any(token in lowered for token in ["思路", "建模", "方程", "idea", "setup", "equation"]):
        if any(token in lowered for token in ["方程正确", "思路正确", "建模正确", "setup correct", "equation correct"]):
            return max(base_ratio, 0.7)
        return max(base_ratio, 0.45)
    if any(token in lowered for token in ["步骤", "推导", "计算", "step", "derivation"]):
        if any(token in lowered for token in ["过程正确", "步骤正确", "calculation mostly correct", "step mostly correct"]):
            return max(base_ratio, 0.6)
        return max(base_ratio, 0.35)
    return base_ratio


def _score_analysis(arguments: Dict[str, Any]) -> Dict[str, Any]:
    question_type = _normalize_question_type(arguments.get("question_type"))
    safe_max = float(arguments.get("max_score") or 1.0)
    correct = bool(arguments.get("correct", False))
    reason = str(arguments.get("reason") or "").strip()
    rubric = rubric_loader._normalize_rubric(arguments.get("rubric"), question_type=question_type, source="mcp_score_analysis")
    if not rubric:
        rubric = rubric_loader._fallback(question_type)

    supervisor_output = arguments.get("supervisor_output") if isinstance(arguments.get("supervisor_output"), dict) else {}
    ratio = extract_recommended_ratio(supervisor_output, correct=correct)
    breakdown = extract_breakdown(supervisor_output, safe_max)

    evidence_text = json.dumps(
        {
            "solver_output": arguments.get("solver_output"),
            "supervisor_output": supervisor_output,
        },
        ensure_ascii=False,
    )
    if not breakdown:
        dimensions = rubric.get("dimensions") if isinstance(rubric.get("dimensions"), list) else []
        if ratio is None:
            if correct:
                ratio = 1.0
            elif any(token in f"{reason} {evidence_text}".lower() for token in ["部分", "partial", "思路正确", "方程正确", "步骤部分正确"]):
                ratio = 0.6
            else:
                ratio = 0.0
        ratio = clamp_ratio(ratio, default=(1.0 if correct else 0.0))
        if dimensions:
            breakdown = []
            for idx, item in enumerate(dimensions, start=1):
                if not isinstance(item, dict):
                    continue
                weight = clamp_ratio(item.get("weight"), default=0.0)
                if weight <= 0:
                    continue
                label = str(item.get("label") or item.get("name") or f"dimension_{idx}").strip()
                credit = _detect_dimension_credit(label, ratio, correct, reason, evidence_text)
                full = round_score(safe_max * weight)
                breakdown.append(
                    {
                        "item": str(item.get("name") or f"dimension_{idx}"),
                        "label": label,
                        "full": full,
                        "earned": round_score(full * credit),
                        "credit": clamp_ratio(credit, default=0.0),
                        "reason": str(item.get("criteria") or reason or "rubric-guided scoring").strip(),
                    }
                )
    if ratio is None:
        ratio = average_credit(breakdown)
    ratio = clamp_ratio(ratio, default=(1.0 if correct else 0.0))
    summary = "已通过 rubric MCP 根据评分细则生成维度化评分建议。"
    if reason:
        summary += f" 判卷结论：{reason}"

    return {
        "scoring": {
            "scoreRatio": ratio,
            "summary": summary,
            "breakdown": breakdown,
        },
        "summary": summary,
        "rubricId": str(rubric.get("id") or "").strip(),
    }


TOOL_HANDLERS = {
    "parse_text": _parse_text,
    "validate": _validate,
    "score_analysis": _score_analysis,
}


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.post("/mcp")
def mcp():
    payload = request.get_json(silent=True) or {}
    request_id = payload.get("id")
    method = str(payload.get("method") or "").strip()
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    try:
        if method == "initialize":
            return jsonify(
                _jsonrpc_result(
                    request_id,
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "rubric-mcp", "version": "0.1.0"},
                    },
                )
            )

        if method == "notifications/initialized":
            return ("", 204)

        if method == "tools/list":
            return jsonify(_jsonrpc_result(request_id, {"tools": _build_tool_list()}))

        if method == "tools/call":
            tool_name = str(params.get("name") or "").strip()
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            handler = TOOL_HANDLERS.get(tool_name)
            if handler is None:
                return jsonify(_jsonrpc_error(request_id, -32601, f"Unknown tool: {tool_name}")), 404
            result = handler(arguments)
            return jsonify(
                _jsonrpc_result(
                    request_id,
                    {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                        "structuredContent": result,
                    },
                )
            )

        return jsonify(_jsonrpc_error(request_id, -32601, f"Unknown method: {method}")), 404
    except Exception as e:
        return jsonify(_jsonrpc_error(request_id, -32000, str(e))), 500


if __name__ == "__main__":
    port = int(os.getenv("MATH_GRADER_RUBRIC_MCP_PORT", "3020"))
    app.run(host="127.0.0.1", port=port, debug=False)
