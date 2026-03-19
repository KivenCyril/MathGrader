from typing import Any, Dict, List, Optional


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def clamp_ratio(value: Optional[float], default: float = 0.0) -> float:
    if value is None:
        return max(0.0, min(1.0, float(default)))
    return max(0.0, min(1.0, float(value)))


def round_score(value: float) -> float:
    return round(float(value), 2)


def build_binary_scoring(correct: bool, safe_max: float) -> Dict[str, Any]:
    score_ratio = 1.0 if correct else 0.0
    score = round_score(safe_max * score_ratio)
    breakdown = [
        {
            "item": "final_verdict",
            "label": "最终结论",
            "earned": score,
            "full": round_score(safe_max),
            "credit": score_ratio,
            "reason": "判定正确，计满分。" if correct else "判定错误，不计分。",
        }
    ]
    return {
        "applied": True,
        "mode": "binary",
        "score": score,
        "maxScore": round_score(safe_max),
        "scoreRatio": score_ratio,
        "breakdown": breakdown,
        "summary": breakdown[0]["reason"],
    }


def _normalize_breakdown_row(item: Dict[str, Any], safe_max: float) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    label = str(item.get("label") or item.get("item") or "").strip()
    if not label:
        return None
    credit = _safe_float(item.get("credit"))
    earned = _safe_float(item.get("earned"))
    full = _safe_float(item.get("full"))
    if credit is None and earned is not None and full and full > 0:
        credit = earned / full
    credit = clamp_ratio(credit, default=0.0)
    full_value = round_score(full if full is not None else safe_max)
    earned_value = round_score(earned if earned is not None else (full_value * credit))
    return {
        "item": str(item.get("item") or label),
        "label": label,
        "earned": earned_value,
        "full": full_value,
        "credit": credit,
        "reason": str(item.get("reason") or "").strip(),
    }


def extract_recommended_ratio(
    supervisor_output: Dict[str, Any],
    *,
    correct: bool,
) -> Optional[float]:
    if not isinstance(supervisor_output, dict):
        return 1.0 if correct else None
    scoring = supervisor_output.get("scoring")
    if not isinstance(scoring, dict):
        return 1.0 if correct else None
    ratio = _safe_float(scoring.get("score_ratio"))
    if ratio is None:
        ratio = _safe_float(scoring.get("scoreRatio"))
    if ratio is not None:
        return clamp_ratio(ratio)
    return 1.0 if correct else None


def extract_breakdown(supervisor_output: Dict[str, Any], safe_max: float) -> List[Dict[str, Any]]:
    if not isinstance(supervisor_output, dict):
        return []
    scoring = supervisor_output.get("scoring")
    if not isinstance(scoring, dict):
        return []
    rows = scoring.get("breakdown")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        normalized = _normalize_breakdown_row(row, safe_max)
        if normalized:
            out.append(normalized)
    return out


def average_credit(breakdown: List[Dict[str, Any]]) -> Optional[float]:
    credits = [float(item.get("credit")) for item in breakdown if item.get("credit") is not None]
    if not credits:
        return None
    return clamp_ratio(sum(credits) / len(credits))
