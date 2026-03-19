from typing import Any, Dict, Optional

from src.grading.routing import resolve_scoring_mode
from src.grading.scoring_rules import (
    average_credit,
    build_binary_scoring,
    clamp_ratio,
    extract_breakdown,
    extract_recommended_ratio,
    round_score,
)


class ScoringEngine:
    def score(
        self,
        *,
        verdict_result: Dict[str, Any],
        safe_max: float,
        question_type: str,
        need_score: bool,
        scoring_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_mode = resolve_scoring_mode(
            question_type=question_type,
            need_score=need_score,
            requested_mode=scoring_mode,
        )
        correct = bool(verdict_result.get("correct", False))

        if resolved_mode == "none":
            return {
                "applied": False,
                "mode": "none",
                "source": "disabled",
                "score": 0.0,
                "maxScore": round_score(safe_max),
                "scoreRatio": None,
                "breakdown": [],
                "summary": "本次请求未计算得分，仅返回对错判定。",
                "notes": ["本次请求关闭了得分计算。"],
            }

        if resolved_mode == "binary":
            result = build_binary_scoring(correct, safe_max)
            result["source"] = "rule"
            result["notes"] = [str(result.get("summary") or "").strip()]
            return result

        details = verdict_result.get("details") if isinstance(verdict_result.get("details"), dict) else {}
        analysis_meta = details.get("scoring_analysis") if isinstance(details.get("scoring_analysis"), dict) else {}
        analysis_scoring = analysis_meta.get("scoring") if isinstance(analysis_meta.get("scoring"), dict) else {}
        supervisor_output = details.get("supervisor_output") if isinstance(details.get("supervisor_output"), dict) else {}
        rubric = details.get("rubric") if isinstance(details.get("rubric"), dict) else {}

        scoring_source = analysis_scoring if analysis_meta.get("used") else supervisor_output
        ratio = extract_recommended_ratio(scoring_source, correct=correct)
        breakdown = extract_breakdown(scoring_source, safe_max)
        if ratio is None:
            ratio = average_credit(breakdown)
        ratio = clamp_ratio(ratio, default=(1.0 if correct else 0.0))
        if correct:
            ratio = 1.0
        elif ratio >= 1.0:
            ratio = 0.9

        score = round_score(safe_max * ratio)
        source_name = "supervisor"
        summary = ""
        if analysis_meta.get("used"):
            source_name = str(analysis_meta.get("toolName") or "mcp").strip() or "mcp"
            summary = str(analysis_scoring.get("summary") or "").strip()
        elif isinstance(supervisor_output.get("scoring"), dict):
            summary = str((supervisor_output.get("scoring") or {}).get("summary") or "").strip()

        if not summary:
            summary = "按分析式评分计算得分。" if breakdown else "分析式评分缺少细项，已按综合比例计分。"
        if not breakdown:
            breakdown = self._build_breakdown_from_rubric(rubric, safe_max, ratio, summary)

        return {
            "applied": True,
            "mode": "analytic",
            "source": source_name,
            "score": score,
            "maxScore": round_score(safe_max),
            "scoreRatio": ratio,
            "breakdown": breakdown,
            "summary": summary,
            "notes": self._build_notes(summary, breakdown, source_name, analysis_meta),
        }

    def _build_notes(
        self,
        summary: str,
        breakdown: list,
        source_name: str,
        analysis_meta: Dict[str, Any],
    ) -> list:
        notes = []
        if analysis_meta.get("used"):
            notes.append(f"已调用 MCP 工具 {source_name} 进行评分分析。")
        elif analysis_meta.get("enabled"):
            notes.append(f"MCP 评分分析未生效：{analysis_meta.get('reason')}")
        if summary:
            notes.append(summary)
        for item in breakdown[:3]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("item") or "").strip() or "评分维度"
            line = label
            credit = item.get("credit")
            if credit is not None:
                try:
                    line += f"：{round(float(credit) * 100)}%"
                except Exception:
                    pass
            reason = str(item.get("reason") or "").strip()
            if reason:
                line += f"，{reason}"
            notes.append(line)
        return notes

    def _build_breakdown_from_rubric(
        self,
        rubric: Dict[str, Any],
        safe_max: float,
        ratio: float,
        summary: str,
    ) -> list:
        dimensions = rubric.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            return [
                {
                    "item": "analytic_total",
                    "label": "综合评分",
                    "earned": round_score(safe_max * ratio),
                    "full": round_score(safe_max),
                    "credit": ratio,
                    "reason": summary,
                }
            ]

        breakdown = []
        for idx, item in enumerate(dimensions, start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("name") or f"维度{idx}").strip()
            try:
                weight = float(item.get("weight", 0.0) or 0.0)
            except Exception:
                weight = 0.0
            if weight <= 0:
                continue
            full = round_score(safe_max * weight)
            earned = round_score(full * ratio)
            breakdown.append(
                {
                    "item": str(item.get("name") or f"dimension_{idx}"),
                    "label": label,
                    "earned": earned,
                    "full": full,
                    "credit": ratio,
                    "reason": str(item.get("criteria") or summary).strip(),
                }
            )
        if breakdown:
            return breakdown
        return [
            {
                "item": "analytic_total",
                "label": "综合评分",
                "earned": round_score(safe_max * ratio),
                "full": round_score(safe_max),
                "credit": ratio,
                "reason": summary,
            }
        ]
