import base64
import json
import os
import random
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

import requests


def _json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _normalize_expr(expr: str) -> str:
    s = str(expr or "").strip()
    return s.replace("^", "**").replace("×", "*").replace("÷", "/")


def _sympy_parse(expr: str):
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    transformations = standard_transformations + (implicit_multiplication_application,)
    return parse_expr(_normalize_expr(expr), transformations=transformations, evaluate=True)


def ocr_math(image_path: str, use_mathpix: bool = False) -> str:
    path = Path(str(image_path or "").strip())
    if not path.exists():
        return _json({"ok": False, "error": f"image not found: {path}"})

    text = ""
    paddle_error = ""
    try:
        from paddleocr import PaddleOCR

        ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        rows = ocr.ocr(str(path), cls=True) or []
        parts = []
        for row in rows:
            for item in row or []:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    info = item[1]
                    if isinstance(info, (list, tuple)) and info:
                        parts.append(str(info[0]))
        text = "\n".join([p for p in parts if p.strip()]).strip()
    except Exception as e:
        paddle_error = str(e)

    if text:
        return _json({"ok": True, "engine": "paddleocr", "text": text})

    if not use_mathpix:
        return _json({"ok": False, "error": f"paddleocr failed: {paddle_error or 'no text'}"})

    app_id = os.getenv("MATHPIX_APP_ID", "").strip()
    app_key = os.getenv("MATHPIX_APP_KEY", "").strip()
    if not app_id or not app_key:
        return _json({"ok": False, "error": "mathpix key not configured"})

    try:
        b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        payload = {
            "src": f"data:image/png;base64,{b64}",
            "formats": ["text", "data"],
            "math_inline_delimiters": ["$", "$"],
        }
        headers = {
            "app_id": app_id,
            "app_key": app_key,
            "Content-type": "application/json",
        }
        resp = requests.post("https://api.mathpix.com/v3/text", json=payload, headers=headers, timeout=30)
        data = resp.json()
        if resp.status_code != 200:
            return _json({"ok": False, "error": f"mathpix status {resp.status_code}", "detail": data})
        text = str(data.get("text") or "").strip()
        if text:
            return _json({"ok": True, "engine": "mathpix", "text": text})
        return _json({"ok": False, "error": "mathpix returned empty text"})
    except Exception as e:
        return _json({"ok": False, "error": f"mathpix failed: {e}"})


def img2latex(image_path: str) -> str:
    path = Path(str(image_path or "").strip())
    if not path.exists():
        return _json({"ok": False, "error": f"image not found: {path}"})

    try:
        from pix2tex.cli import LatexOCR

        model = LatexOCR()
        latex = str(model(str(path)) or "").strip()
        if latex:
            return _json({"ok": True, "latex": latex})
        return _json({"ok": False, "error": "pix2tex returned empty latex"})
    except Exception as e:
        return _json({"ok": False, "error": f"pix2tex failed: {e}"})


def eval_expr(expression: str) -> str:
    expr = str(expression or "").strip()
    if not expr:
        return _json({"ok": False, "error": "expression is empty"})
    try:
        from sympy import N, simplify

        parsed = _sympy_parse(expr)
        simplified = simplify(parsed)
        out = {"ok": True, "simplified": str(simplified), "is_numeric": len(getattr(simplified, "free_symbols", [])) == 0}
        if out["is_numeric"]:
            out["value"] = str(N(simplified, 20))
        return _json(out)
    except Exception as e:
        return _json({"ok": False, "error": f"eval failed: {e}"})


def verify_step(steps: str) -> str:
    text = str(steps or "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    checked = 0
    invalid = []

    from sympy import N, simplify

    for idx, line in enumerate(lines, start=1):
        if "=" not in line:
            continue
        parts = [p.strip() for p in line.split("=") if p.strip()]
        if len(parts) < 2:
            continue
        for i in range(len(parts) - 1):
            checked += 1
            left_text = parts[i]
            right_text = parts[i + 1]
            try:
                left = _sympy_parse(left_text)
                right = _sympy_parse(right_text)
                diff = simplify(left - right)
                same = bool(diff == 0)
                if not same and not (left.free_symbols or right.free_symbols):
                    same = abs(float(N(diff))) <= 1e-9
                if not same:
                    invalid.append(
                        {
                            "line": idx,
                            "left": left_text,
                            "right": right_text,
                            "reason": f"not equal, diff={diff}",
                        }
                    )
            except Exception as e:
                invalid.append(
                    {
                        "line": idx,
                        "left": left_text,
                        "right": right_text,
                        "reason": f"parse error: {e}",
                    }
                )

    if checked == 0:
        return _json({"ok": False, "valid": False, "checked": 0, "invalid": [], "reason": "no equation lines found"})
    return _json({"ok": True, "valid": len(invalid) == 0, "checked": checked, "invalid": invalid})


def verify_equation_setup(equation: str, expected_answer: str = "") -> str:
    text = str(equation or "").strip()
    expected_text = str(expected_answer or "").strip()
    if "=" not in text:
        return _json({"ok": False, "valid": False, "reason": "equation must contain '='"})

    lhs_text, rhs_text = text.split("=", 1)
    lhs_text = lhs_text.strip()
    rhs_text = rhs_text.strip()
    if not lhs_text or not rhs_text:
        return _json({"ok": False, "valid": False, "reason": "both lhs and rhs are required"})

    try:
        from sympy import Eq, simplify, solve

        lhs = _sympy_parse(lhs_text)
        rhs = _sympy_parse(rhs_text)
        symbols = sorted(list(lhs.free_symbols | rhs.free_symbols), key=lambda item: str(item))
        result: Dict[str, Any] = {
            "ok": True,
            "valid": True,
            "equation": text,
            "symbols": [str(s) for s in symbols],
            "simplified_difference": str(simplify(lhs - rhs)),
        }

        if not symbols:
            is_identity = bool(simplify(lhs - rhs) == 0)
            result["is_identity"] = is_identity
            result["solutions"] = []
            if expected_text:
                try:
                    expected_expr = _sympy_parse(expected_text)
                    result["expected_matches"] = bool(simplify(lhs - rhs) == 0 and simplify(lhs - expected_expr) == 0)
                except Exception:
                    result["expected_matches"] = False
            return _json(result)

        equation_obj = Eq(lhs, rhs)
        solved = solve(equation_obj, *symbols, dict=True)
        solutions = []
        for item in solved:
            if isinstance(item, dict):
                solutions.append({str(k): str(v) for k, v in item.items()})
        result["solutions"] = solutions
        result["has_solution"] = len(solutions) > 0

        if expected_text and len(symbols) == 1:
            symbol = symbols[0]
            try:
                expected_expr = _sympy_parse(expected_text)
                satisfies = bool(simplify(lhs.subs(symbol, expected_expr) - rhs.subs(symbol, expected_expr)) == 0)
                result["expected_matches"] = satisfies
            except Exception as e:
                result["expected_matches"] = False
                result["expected_parse_error"] = str(e)
        return _json(result)
    except Exception as e:
        return _json({"ok": False, "valid": False, "reason": f"equation verify failed: {e}"})


def find_counterexample(statement: str, trials: int = 30) -> str:
    content = str(statement or "").strip()
    if "=" not in content:
        return _json({"ok": False, "error": "statement must contain '='"})

    lhs_text, rhs_text = content.split("=", 1)
    lhs_text = lhs_text.strip()
    rhs_text = rhs_text.strip()
    if not lhs_text or not rhs_text:
        return _json({"ok": False, "error": "both lhs and rhs are required"})

    from sympy import N, simplify

    try:
        lhs = _sympy_parse(lhs_text)
        rhs = _sympy_parse(rhs_text)
    except Exception as e:
        return _json({"ok": False, "error": f"parse failed: {e}"})

    symbols = sorted([str(s) for s in (lhs.free_symbols | rhs.free_symbols)])
    if not symbols:
        diff = simplify(lhs - rhs)
        wrong = bool(diff != 0 and abs(float(N(diff))) > 1e-9)
        if wrong:
            return _json({"ok": True, "found": True, "counterexample": {}, "diff": str(diff)})
        return _json({"ok": True, "found": False, "reason": "constant identity"})

    for _ in range(max(5, int(trials))):
        assignment = {name: random.randint(-9, 9) for name in symbols}
        try:
            lv = lhs.subs(assignment)
            rv = rhs.subs(assignment)
            diff = simplify(lv - rv)
            if diff != 0 and abs(float(N(diff))) > 1e-9:
                return _json(
                    {
                        "ok": True,
                        "found": True,
                        "counterexample": assignment,
                        "lhs_value": str(N(lv, 12)),
                        "rhs_value": str(N(rv, 12)),
                        "diff": str(N(diff, 12)),
                    }
                )
        except Exception:
            continue

    return _json({"ok": True, "found": False, "reason": "no counterexample found in random trials"})


LOCAL_LANGCHAIN_TOOL_DEFS: Dict[str, Dict[str, Any]] = {
    "ocr_math": {
        "type": "function",
        "function": {
            "name": "ocr_math",
            "description": "Recognize math text from image using PaddleOCR, with optional Mathpix fallback.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "Local image path."},
                    "use_mathpix": {"type": "boolean", "description": "Use Mathpix fallback when PaddleOCR fails."},
                },
                "required": ["image_path"],
            },
        },
    },
    "img2latex": {
        "type": "function",
        "function": {
            "name": "img2latex",
            "description": "Convert math formula image to LaTeX via pix2tex.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "Local image path."},
                },
                "required": ["image_path"],
            },
        },
    },
    "eval_expr": {
        "type": "function",
        "function": {
            "name": "eval_expr",
            "description": "Evaluate or simplify a math expression with SymPy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression to evaluate."},
                },
                "required": ["expression"],
            },
        },
    },
    "verify_step": {
        "type": "function",
        "function": {
            "name": "verify_step",
            "description": "Verify a multi-line chain of equalities or solving steps. Use this for step-by-step work, not for a single unfinished equation setup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {"type": "string", "description": "Multi-line solving steps."},
                },
                "required": ["steps"],
            },
        },
    },
    "verify_equation_setup": {
        "type": "function",
        "function": {
            "name": "verify_equation_setup",
            "description": "Verify whether a single equation or setup is mathematically valid and solvable. Use this first when the student's answer is an equation like '5(x-10)=3x' rather than a final numeric answer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "equation": {"type": "string", "description": "A single equation or setup containing '='."},
                    "expected_answer": {"type": "string", "description": "Optional standard answer to test against the equation's solution."},
                },
                "required": ["equation"],
            },
        },
    },
    "find_counterexample": {
        "type": "function",
        "function": {
            "name": "find_counterexample",
            "description": "Search random numeric counterexamples for equation claims.",
            "parameters": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string", "description": "Equation claim, e.g. 'x+1=x'."},
                    "trials": {"type": "integer", "description": "Random trials for search."},
                },
                "required": ["statement"],
            },
        },
    },
}


LOCAL_LANGCHAIN_TOOL_HANDLERS: Dict[str, Callable[..., Any]] = {
    "ocr_math": ocr_math,
    "img2latex": img2latex,
    "eval_expr": eval_expr,
    "verify_step": verify_step,
    "verify_equation_setup": verify_equation_setup,
    "find_counterexample": find_counterexample,
}


def build_local_langchain_tools() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Callable[..., Any]]]:
    return dict(LOCAL_LANGCHAIN_TOOL_DEFS), dict(LOCAL_LANGCHAIN_TOOL_HANDLERS)
