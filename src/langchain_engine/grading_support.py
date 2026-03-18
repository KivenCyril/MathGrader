import re
from typing import Any, Callable, Dict, List, Optional


def normalize_arithmetic_text(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    s = s.translate(
        str.maketrans(
            {
                "\uFF08": "(",
                "\uFF09": ")",
                "\uFF0B": "+",
                "\uFF0D": "-",
                "\u00D7": "*",
                "\u00F7": "/",
                "\u2212": "-",
                "\u3002": ".",
            }
        )
    )
    s = s.replace("[", "(").replace("]", ")").replace("{", "(").replace("}", ")")
    s = s.replace(" ", "")
    s = re.sub(r"[=,.!?;:]+$", "", s)
    return s


def extract_arithmetic_expression(text: str) -> Optional[str]:
    s = normalize_arithmetic_text(text)
    if not s:
        return None
    if re.search(r"[A-Za-z\u4e00-\u9fff]", s):
        return None
    s = re.sub(r"(?<![\dA-Za-z_])(\d+)\((\d+\s*/\s*\d+)\)", r"(\1+\2)", s)
    s = s.replace("^", "**")
    if "=" in s:
        s = s.split("=", 1)[0].strip()
    if not s or not any(op in s for op in "+-*/"):
        return None
    if not re.fullmatch(r"[0-9\.\+\-\*/\(\)]*", s):
        return None
    return s


def extract_math_value_expression(text: str) -> Optional[str]:
    s = normalize_arithmetic_text(text)
    if not s:
        return None
    if re.search(r"[A-Za-z\u4e00-\u9fff]", s):
        return None
    s = re.sub(r"(?<![\dA-Za-z_])(\d+)\((\d+\s*/\s*\d+)\)", r"(\1+\2)", s)
    s = s.replace("^", "**")
    if "=" in s:
        s = s.split("=", 1)[0].strip()
    if not s:
        return None
    if not re.fullmatch(r"[0-9\.\+\-\*/\(\)]*", s):
        return None
    return s


def evaluate_arithmetic_expression(expr: str) -> Optional[str]:
    try:
        from sympy import simplify, sympify

        value = simplify(sympify(expr))
        return str(value)
    except Exception:
        return None


def build_mixed_fraction_notes(text: str) -> List[str]:
    notes = []
    raw = normalize_arithmetic_text(text)
    for whole, numerator, denominator in re.findall(r"(\d+)\((\d+)\s*/\s*(\d+)\)", raw):
        improper = (int(whole) * int(denominator)) + int(numerator)
        notes.append(f"{whole}({numerator}/{denominator}) = {improper}/{denominator}")
    return notes


def normalize_choice_answer(text: str) -> str:
    s = str(text or "").strip().upper()
    if not s:
        return ""
    s = s.translate(
        str.maketrans(
            {
                "\uFF21": "A",
                "\uFF22": "B",
                "\uFF23": "C",
                "\uFF24": "D",
                "\uFF25": "E",
                "\uFF26": "F",
            }
        )
    )
    m = re.fullmatch(r"[\(\[（\s]*([A-F])[\)\]）.\s]*", s)
    return m.group(1) if m else ""


def normalize_judgment_answer(text: str, normalize_answer: Callable[[Any], str]) -> str:
    s = normalize_answer(text)
    mapping = {
        "true": "true",
        "false": "false",
        "t": "true",
        "f": "false",
        "1": "true",
        "0": "false",
        "yes": "true",
        "no": "false",
        "对": "true",
        "错": "false",
        "正确": "true",
        "错误": "false",
        "√": "true",
        "×": "false",
    }
    return mapping.get(s, "")


def classify_question_type(
    question: str,
    truth: str,
    student: str,
    *,
    normalize_answer: Callable[[Any], str],
) -> str:
    truth_judgment = normalize_judgment_answer(truth, normalize_answer)
    student_judgment = normalize_judgment_answer(student, normalize_answer)
    if truth_judgment and student_judgment:
        return "judgment"

    truth_choice = normalize_choice_answer(truth)
    student_choice = normalize_choice_answer(student)
    if truth_choice and student_choice:
        return "choice"

    if extract_arithmetic_expression(question) and extract_math_value_expression(student):
        return "arithmetic"

    return "complex"


def normalize_question_type(value: Any) -> str:
    s = str(value or "").strip().lower()
    aliases = {
        "select": "choice",
        "single_choice": "choice",
        "multiple_choice": "choice",
        "choice": "choice",
        "judge": "judgment",
        "boolean": "judgment",
        "judgement": "judgment",
        "judgment": "judgment",
        "arithmetic": "arithmetic",
        "calculation": "arithmetic",
        "complex": "complex",
    }
    return aliases.get(s, "")


def question_type_label(question_type: str) -> str:
    labels = {
        "choice": "选择题",
        "judgment": "判断题",
        "arithmetic": "计算题",
        "complex": "复杂题",
    }
    return labels.get(question_type, "题目")


def has_usable_truth(truth: str) -> bool:
    text = str(truth or "").strip()
    if not text:
        return False
    masked = re.sub(r"[\s\*\-_=．。·…]+", "", text)
    if not masked:
        return False
    lowered = masked.lower()
    return lowered not in {"n/a", "na", "unknown", "null", "none"}


def try_rule_based_choice_grade(
    *,
    truth: str,
    student: str,
    safe_max: float,
    trace_id: Optional[str],
    total_started_at: float,
    equivalence_started_at: float,
    build_result: Callable[..., Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    truth_choice = normalize_choice_answer(truth)
    student_choice = normalize_choice_answer(student)
    if not truth_choice or not student_choice:
        return None
    return build_result(
        fast_path_kind="choice",
        expected_answer=truth_choice,
        student_answer_value=student_choice,
        safe_max=safe_max,
        correct=(truth_choice == student_choice),
        trace_id=trace_id,
        total_started_at=total_started_at,
        equivalence_started_at=equivalence_started_at,
        key_steps=[f"标准答案：{truth_choice}", f"学生答案：{student_choice}"],
        question_expr=f"choice:{truth_choice}",
        student_expr=f"choice:{student_choice}",
    )


def try_rule_based_judgment_grade(
    *,
    truth: str,
    student: str,
    safe_max: float,
    trace_id: Optional[str],
    total_started_at: float,
    equivalence_started_at: float,
    normalize_answer: Callable[[Any], str],
    build_result: Callable[..., Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    truth_value = normalize_judgment_answer(truth, normalize_answer)
    student_value = normalize_judgment_answer(student, normalize_answer)
    if not truth_value or not student_value:
        return None
    return build_result(
        fast_path_kind="judgment",
        expected_answer=truth_value,
        student_answer_value=student_value,
        safe_max=safe_max,
        correct=(truth_value == student_value),
        trace_id=trace_id,
        total_started_at=total_started_at,
        equivalence_started_at=equivalence_started_at,
        key_steps=[f"标准答案：{truth_value}", f"学生答案：{student_value}"],
        question_expr=f"judgment:{truth_value}",
        student_expr=f"judgment:{student_value}",
    )


def try_rule_based_arithmetic_grade(
    *,
    question: str,
    truth: str,
    student: str,
    safe_max: float,
    trace_id: Optional[str],
    total_started_at: float,
    equivalence_started_at: float,
    answers_equivalent: Callable[[str, str], bool],
    build_result: Callable[..., Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    question_expr = extract_arithmetic_expression(question)
    student_expr = extract_math_value_expression(student)
    if not question_expr or not student_expr:
        return None

    expected_expr = extract_math_value_expression(truth) if truth else None
    expected_expr = expected_expr or question_expr
    expected_answer = evaluate_arithmetic_expression(expected_expr)
    student_answer_value = evaluate_arithmetic_expression(student_expr)
    if expected_answer is None or student_answer_value is None:
        return None

    key_steps = []
    mixed_notes = build_mixed_fraction_notes(question)
    if mixed_notes:
        key_steps.append("带分数转换：" + "，".join(mixed_notes))
    normalized_question = question_expr.replace("**", "^")
    key_steps.append(f"规范化表达式：{normalized_question}")
    key_steps.append(f"计算结果：{normalized_question} = {expected_answer}")

    return build_result(
        fast_path_kind="arithmetic",
        expected_answer=expected_answer,
        student_answer_value=student_answer_value,
        safe_max=safe_max,
        correct=answers_equivalent(expected_answer, student_answer_value),
        trace_id=trace_id,
        total_started_at=total_started_at,
        equivalence_started_at=equivalence_started_at,
        key_steps=key_steps,
        question_expr=question_expr,
        student_expr=student_expr,
    )
