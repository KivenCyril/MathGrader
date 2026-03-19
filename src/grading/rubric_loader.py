import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class RubricLoader:
    def __init__(self, config: Optional[Dict[str, Any]] = None, rubric_root: str = "rubrics"):
        self.config = config or {}
        self.rubric_root = Path(rubric_root)

    def load(self, question_type: str) -> Dict[str, Any]:
        normalized_type = str(question_type or "").strip().lower() or "complex"
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
