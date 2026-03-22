from typing import Any, Optional


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def coerce_positive_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default
