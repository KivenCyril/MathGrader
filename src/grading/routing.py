from typing import Optional

from src.grading.types import (
    OBJECTIVE_QUESTION_TYPES,
    SCORING_MODE_ANALYTIC,
    SCORING_MODE_AUTO,
    SCORING_MODE_BINARY,
    SCORING_MODE_NONE,
    normalize_scoring_mode,
)


def resolve_scoring_mode(
    *,
    question_type: str,
    need_score: bool,
    requested_mode: Optional[str] = None,
    rubric_strategy: Optional[str] = None,
) -> str:
    if not need_score:
        return SCORING_MODE_NONE

    normalized_type = str(question_type or "").strip().lower()
    normalized_mode = normalize_scoring_mode(requested_mode)
    normalized_strategy = normalize_scoring_mode(rubric_strategy)

    if normalized_mode in {SCORING_MODE_BINARY, SCORING_MODE_ANALYTIC}:
        return normalized_mode

    if normalized_mode == SCORING_MODE_NONE:
        return SCORING_MODE_NONE

    if normalized_strategy in {SCORING_MODE_BINARY, SCORING_MODE_ANALYTIC, SCORING_MODE_NONE}:
        return normalized_strategy

    if normalized_type in OBJECTIVE_QUESTION_TYPES:
        return SCORING_MODE_BINARY

    return SCORING_MODE_ANALYTIC if normalized_mode == SCORING_MODE_AUTO else normalized_mode
