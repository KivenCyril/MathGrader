import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class RubricLoader:
    def __init__(self, config: Optional[Dict[str, Any]] = None, rubric_root: str = "rubrics"):
        self.config = config or {}
        self.rubric_root = Path(rubric_root)

    def load(
        self,
        question_type: str,
        *,
        rubric_override: Optional[Any] = None,
        rubric_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_type = str(question_type or "").strip().lower() or "complex"
        runtime_rubric = self._resolve_runtime_rubric(
            question_type=normalized_type,
            rubric_override=rubric_override,
            rubric_text=rubric_text,
        )
        if runtime_rubric:
            return runtime_rubric

        candidate_names = [
            f"{normalized_type}.json",
            "complex.json" if normalized_type not in {"choice", "judgment", "arithmetic"} else "binary.json",
            "default.json",
        ]
        for name in candidate_names:
            path = self.rubric_root / name
            if path.exists():
                data = self._read_json(path)
                if isinstance(data, dict):
                    data.setdefault("id", path.stem)
                    data.setdefault("questionType", normalized_type)
                    data.setdefault("source", str(path).replace("\\", "/"))
                    return data
        return self._fallback(normalized_type)

    def prompt_text(self, rubric: Dict[str, Any]) -> str:
        if not isinstance(rubric, dict):
            return ""
        lines: List[str] = []
        rubric_id = str(rubric.get("id") or "").strip()
        if rubric_id:
            lines.append(f"Rubric ID: {rubric_id}")
        strategy = str(rubric.get("strategy") or "").strip()
        if strategy:
            lines.append(f"Scoring Strategy: {strategy}")
        summary = str(rubric.get("summary") or "").strip()
        if summary:
            lines.append(f"Summary: {summary}")
        dimensions = rubric.get("dimensions")
        if isinstance(dimensions, list):
            lines.append("Dimensions:")
            for item in dimensions[:5]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("name") or "").strip()
                weight = item.get("weight")
                criteria = str(item.get("criteria") or "").strip()
                if label:
                    row = f"- {label}"
                    if weight is not None:
                        row += f" ({weight})"
                    if criteria:
                        row += f": {criteria}"
                    lines.append(row)
        penalties = rubric.get("penalties")
        if isinstance(penalties, list) and penalties:
            lines.append("Penalties:")
            for item in penalties[:5]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("name") or "").strip()
                deduction = item.get("deduction")
                criteria = str(item.get("criteria") or "").strip()
                if label:
                    row = f"- {label}"
                    if deduction is not None:
                        row += f" (-{deduction})"
                    if criteria:
                        row += f": {criteria}"
                    lines.append(row)
        return "\n".join(lines).strip()

    def notes(self, rubric: Dict[str, Any]) -> List[str]:
        if not isinstance(rubric, dict):
            return []
        out: List[str] = []
        rubric_id = str(rubric.get("id") or "default").strip()
        strategy = str(rubric.get("strategy") or "").strip()
        out.append(f"已加载评分规则 {rubric_id}。")
        if strategy:
            out.append(f"评分策略：{strategy}。")
        summary = str(rubric.get("summary") or "").strip()
        if summary:
            out.append(summary)
        dimensions = rubric.get("dimensions")
        if isinstance(dimensions, list):
            for item in dimensions[:3]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("name") or "").strip()
                weight = item.get("weight")
                if label:
                    msg = f"评分维度：{label}"
                    if weight is not None:
                        msg += f"（权重 {weight}）"
                    out.append(msg)
        return out

    def _read_json(self, path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _resolve_runtime_rubric(
        self,
        *,
        question_type: str,
        rubric_override: Optional[Any],
        rubric_text: Optional[str],
    ) -> Dict[str, Any]:
        normalized_type = str(question_type or "").strip().lower() or "complex"
        normalized = self._normalize_rubric(
            rubric_override,
            question_type=normalized_type,
            source="runtime_json",
        )
        if normalized:
            return normalized

        parsed_text = self._parse_rubric_text(str(rubric_text or "").strip(), question_type=normalized_type)
        normalized = self._normalize_rubric(
            parsed_text,
            question_type=normalized_type,
            source="runtime_text",
        )
        if normalized:
            return normalized
        return {}

    def _normalize_rubric(
        self,
        rubric: Optional[Any],
        *,
        question_type: str,
        source: str,
    ) -> Dict[str, Any]:
        if isinstance(rubric, str):
            text = rubric.strip()
            if not text:
                return {}
            try:
                rubric = json.loads(text)
            except Exception:
                rubric = self._parse_rubric_text(text, question_type=question_type)

        if not isinstance(rubric, dict):
            return {}

        strategy = str(rubric.get("strategy") or "").strip().lower()
        if strategy not in {"binary", "analytic", "none"}:
            strategy = "binary" if question_type in {"choice", "judgment", "arithmetic"} else "analytic"

        normalized: Dict[str, Any] = {
            "id": str(rubric.get("id") or "runtime").strip() or "runtime",
            "questionType": str(rubric.get("questionType") or question_type).strip().lower() or question_type,
            "strategy": strategy,
            "summary": str(rubric.get("summary") or "").strip(),
            "dimensions": [],
            "penalties": [],
            "source": source,
        }

        dimensions = rubric.get("dimensions")
        if isinstance(dimensions, list):
            normalized["dimensions"] = self._normalize_dimensions(dimensions)

        penalties = rubric.get("penalties")
        if isinstance(penalties, list):
            normalized["penalties"] = self._normalize_penalties(penalties)

        if not normalized["summary"]:
            normalized["summary"] = self._build_summary_from_rubric(normalized)

        if strategy == "binary" and not normalized["dimensions"]:
            normalized["dimensions"] = [
                {
                    "name": "final_answer",
                    "label": "最终答案",
                    "weight": 1.0,
                    "criteria": "答案正确则满分，否则零分。",
                }
            ]

        return normalized if normalized["summary"] or normalized["dimensions"] or normalized["penalties"] else {}

    def _normalize_dimensions(self, dimensions: List[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(dimensions, start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("name") or "").strip()
            if not label:
                continue
            weight = self._safe_float(item.get("weight"))
            if weight is None:
                continue
            normalized.append(
                {
                    "name": str(item.get("name") or f"dimension_{idx}").strip() or f"dimension_{idx}",
                    "label": label,
                    "weight": weight,
                    "criteria": str(item.get("criteria") or "").strip(),
                }
            )
        weights = [float(item["weight"]) for item in normalized if float(item["weight"]) > 0]
        total = sum(weights)
        if total > 0:
            for item in normalized:
                item["weight"] = round(float(item["weight"]) / total, 6)
        return normalized

    def _normalize_penalties(self, penalties: List[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(penalties, start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("name") or "").strip()
            if not label:
                continue
            deduction = self._safe_float(item.get("deduction"))
            if deduction is None:
                continue
            normalized.append(
                {
                    "name": str(item.get("name") or f"penalty_{idx}").strip() or f"penalty_{idx}",
                    "label": label,
                    "deduction": max(0.0, min(1.0, deduction)),
                    "criteria": str(item.get("criteria") or "").strip(),
                }
            )
        return normalized

    def _parse_rubric_text(self, text: str, *, question_type: str) -> Dict[str, Any]:
        content = str(text or "").strip()
        if not content:
            return {}

        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        lines = []
        for chunk in re.split(r"[\r\n]+", content):
            parts = [part.strip(" \t-") for part in re.split(r"[；;]+", chunk) if part.strip()]
            lines.extend(parts)

        strategy = "binary" if question_type in {"choice", "judgment", "arithmetic"} else "analytic"
        summary_lines: List[str] = []
        dimensions: List[Dict[str, Any]] = []
        penalties: List[Dict[str, Any]] = []

        for line in lines:
            lowered = line.lower()
            if any(token in lowered for token in ["strategy", "模式", "策略"]):
                if any(token in lowered for token in ["binary", "客观", "二值"]):
                    strategy = "binary"
                elif any(token in lowered for token in ["analytic", "分析", "步骤", "部分分"]):
                    strategy = "analytic"
                continue

            penalty = self._parse_penalty_line(line)
            if penalty:
                penalties.append(penalty)
                continue

            dimension = self._parse_dimension_line(line, index=len(dimensions) + 1)
            if dimension:
                dimensions.append(dimension)
                continue

            summary_lines.append(line)

        summary = "\n".join(summary_lines).strip()
        if not summary:
            summary = content

        return {
            "id": "runtime_text",
            "questionType": question_type,
            "strategy": strategy,
            "summary": summary,
            "dimensions": dimensions,
            "penalties": penalties,
        }

    def _parse_dimension_line(self, line: str, *, index: int) -> Dict[str, Any]:
        text = str(line or "").strip()
        if not text:
            return {}
        match = re.match(
            r"^(?P<label>[^:：,，(（)）]{1,30}?)\s*(?:[:：]\s*)?(?P<weight>\d+(?:\.\d+)?)\s*(?P<percent>%|％)?(?:\s*[-,，:：]\s*(?P<criteria>.+))?$",
            text,
        )
        if not match:
            return {}
        label = str(match.group("label") or "").strip()
        weight = self._weight_value(match.group("weight"), match.group("percent"))
        if not label or weight is None:
            return {}
        return {
            "name": f"dimension_{index}",
            "label": label,
            "weight": weight,
            "criteria": str(match.group("criteria") or "").strip(),
        }

    def _parse_penalty_line(self, line: str) -> Dict[str, Any]:
        text = str(line or "").strip()
        if not text:
            return {}
        match = re.match(
            r"^(?P<label>[^:：,，]{1,30}?)\s*(?:扣|减|扣分|罚|deduct(?:ion)?|penalty)\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<percent>%|％)?(?:\s*[-,，:：]\s*(?P<criteria>.+))?$",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return {}
        label = str(match.group("label") or "").strip()
        deduction = self._weight_value(match.group("value"), match.group("percent"))
        if not label or deduction is None:
            return {}
        return {
            "name": f"penalty_{re.sub(r'[^a-zA-Z0-9]+', '_', label).strip('_') or 'runtime'}",
            "label": label,
            "deduction": deduction,
            "criteria": str(match.group("criteria") or "").strip(),
        }

    def _weight_value(self, raw_value: Any, percent_mark: Any = "") -> Optional[float]:
        value = self._safe_float(raw_value)
        if value is None:
            return None
        if str(percent_mark or "").strip():
            value = value / 100.0
        elif value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    def _safe_float(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    def _build_summary_from_rubric(self, rubric: Dict[str, Any]) -> str:
        strategy = str(rubric.get("strategy") or "").strip()
        dimensions = rubric.get("dimensions") if isinstance(rubric.get("dimensions"), list) else []
        penalties = rubric.get("penalties") if isinstance(rubric.get("penalties"), list) else []
        fragments = []
        if strategy:
            fragments.append(f"评分策略：{strategy}")
        if dimensions:
            labels = [str(item.get("label") or "").strip() for item in dimensions if str(item.get("label") or "").strip()]
            if labels:
                fragments.append("评分维度：" + "、".join(labels))
        if penalties:
            labels = [str(item.get("label") or "").strip() for item in penalties if str(item.get("label") or "").strip()]
            if labels:
                fragments.append("扣分项：" + "、".join(labels))
        return "；".join(fragments)

    def _fallback(self, question_type: str) -> Dict[str, Any]:
        if question_type in {"choice", "judgment", "arithmetic"}:
            return {
                "id": "binary",
                "questionType": question_type,
                "strategy": "binary",
                "summary": "客观题与简单计算题采用二值评分：答对即满分，答错即零分。",
                "dimensions": [
                    {"label": "最终答案", "weight": 1.0, "criteria": "答案正确则满分，否则零分。"}
                ],
                "penalties": [],
                "source": "builtin",
            }
        return {
            "id": "complex",
            "questionType": question_type,
            "strategy": "analytic",
            "summary": "复杂题默认按解题思路、关键步骤和最终结论综合评分；若列式或方程设立正确但未完成求解，应判为部分正确。",
            "dimensions": [
                {
                    "label": "解题思路",
                    "weight": 0.4,
                    "criteria": "是否正确建立数量关系、列式、方程或推理框架；方程设立正确但未完成求解时，本维度应保留主要得分。",
                },
                {
                    "label": "关键步骤",
                    "weight": 0.35,
                    "criteria": "关键计算或推导是否基本正确；对单个方程或列式，应先验证其是否可解、是否与标准答案一致。",
                },
                {
                    "label": "最终结论",
                    "weight": 0.25,
                    "criteria": "最终结果、单位和表达是否准确；未给出最终答案时，本维度不得判满分。",
                },
            ],
            "penalties": [
                {"label": "单位或条件遗漏", "deduction": 0.1, "criteria": "结论缺少单位，或忽略关键条件。"},
                {"label": "结果与过程矛盾", "deduction": 0.15, "criteria": "过程部分正确，但最终结论与过程不一致。"},
            ],
            "source": "builtin",
        }
