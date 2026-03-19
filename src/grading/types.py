from typing import Optional


SCORING_MODE_AUTO = "auto"
SCORING_MODE_NONE = "none"
SCORING_MODE_BINARY = "binary"
SCORING_MODE_ANALYTIC = "analytic"

OBJECTIVE_QUESTION_TYPES = {"choice", "judgment", "arithmetic"}


def normalize_scoring_mode(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "": SCORING_MODE_AUTO,
        "auto": SCORING_MODE_AUTO,
        "off": SCORING_MODE_NONE,
        "none": SCORING_MODE_NONE,
        "disabled": SCORING_MODE_NONE,
        "binary": SCORING_MODE_BINARY,
        "objective": SCORING_MODE_BINARY,
        "analytic": SCORING_MODE_ANALYTIC,
        "analysis": SCORING_MODE_ANALYTIC,
        "rubric": SCORING_MODE_ANALYTIC,
    }
    return aliases.get(text, SCORING_MODE_AUTO)
