import time
from typing import Any, Dict, List, Optional

from src.langchain_engine.grading_results import build_rule_based_grade_result, ensure_supervisor_analysis
from src.langchain_engine.grading_support import (
    build_mixed_fraction_notes,
    classify_question_type,
    evaluate_arithmetic_expression,
    extract_arithmetic_expression,
    extract_math_value_expression,
    has_usable_truth,
    normalize_arithmetic_text,
    normalize_choice_answer,
    normalize_judgment_answer,
    normalize_question_type,
    question_type_label,
    try_rule_based_arithmetic_grade,
    try_rule_based_choice_grade,
    try_rule_based_judgment_grade,
)

def _answers_equivalent(self, truth: str, student: str) -> bool:
    t = self._normalize_answer(truth)
    s = self._normalize_answer(student)
    if t and t == s:
        return True
    try:
        from sympy import N, simplify, sympify

        lt = sympify(str(truth).replace("^", "**"))
        ls = sympify(str(student).replace("^", "**"))
        diff = simplify(lt - ls)
        if diff == 0:
            return True
        if not (lt.free_symbols or ls.free_symbols):
            return abs(float(N(diff))) <= 1e-9
    except Exception:
        return False
    return False

def _normalize_arithmetic_text(self, text: str) -> str:
    return normalize_arithmetic_text(text)

def _extract_arithmetic_expression(self, text: str) -> Optional[str]:
    return extract_arithmetic_expression(text)

def _extract_math_value_expression(self, text: str) -> Optional[str]:
    return extract_math_value_expression(text)

def _evaluate_arithmetic_expression(self, expr: str) -> Optional[str]:
    return evaluate_arithmetic_expression(expr)

def _build_mixed_fraction_notes(self, text: str) -> List[str]:
    return build_mixed_fraction_notes(text)

def _normalize_choice_answer(self, text: str) -> str:
    return normalize_choice_answer(text)

def _normalize_judgment_answer(self, text: str) -> str:
    return normalize_judgment_answer(text, self._normalize_answer)

def _classify_question_type(self, question: str, truth: str, student: str) -> str:
    return classify_question_type(question, truth, student, normalize_answer=self._normalize_answer)

def _normalize_question_type(self, value: Any) -> str:
    return normalize_question_type(value)

def _question_type_label(self, question_type: str) -> str:
    return question_type_label(question_type)

def _has_usable_truth(self, truth: str) -> bool:
    return has_usable_truth(truth)

def _build_rule_based_grade_result(
    self,
    fast_path_kind: str,
    expected_answer: str,
    student_answer_value: str,
    safe_max: float,
    correct: bool,
    trace_id: Optional[str],
    total_started_at: float,
    equivalence_started_at: float,
    key_steps: List[str],
    question_expr: str = "",
    student_expr: str = "",
) -> Dict[str, Any]:
    return build_rule_based_grade_result(
        method_id=self.method_id,
        recommender_enabled=self.recommender.enabled,
        fast_path_kind=fast_path_kind,
        question_type_label=self._question_type_label(fast_path_kind),
        expected_answer=expected_answer,
        student_answer_value=student_answer_value,
        safe_max=safe_max,
        correct=correct,
        trace_id=trace_id,
        total_started_at=total_started_at,
        equivalence_started_at=equivalence_started_at,
        key_steps=key_steps,
        question_expr=question_expr,
        student_expr=student_expr,
        elapsed_ms=self._elapsed_ms,
    )

def _ensure_supervisor_analysis(
    self,
    supervisor_json: Optional[Dict[str, Any]],
    correct: bool,
    truth: str,
    student: str,
    reference_answer: str,
    solver_steps: str,
) -> Dict[str, Any]:
    return ensure_supervisor_analysis(
        supervisor_json,
        correct=correct,
        truth=truth,
        student=student,
        reference_answer=reference_answer,
        solver_steps=solver_steps,
    )

def _try_rule_based_choice_grade(
    self,
    truth: str,
    student: str,
    safe_max: float,
    trace_id: Optional[str],
    total_started_at: float,
    equivalence_started_at: float,
) -> Optional[Dict[str, Any]]:
    return try_rule_based_choice_grade(
        truth=truth,
        student=student,
        safe_max=safe_max,
        trace_id=trace_id,
        total_started_at=total_started_at,
        equivalence_started_at=equivalence_started_at,
        build_result=self._build_rule_based_grade_result,
    )

def _try_rule_based_judgment_grade(
    self,
    truth: str,
    student: str,
    safe_max: float,
    trace_id: Optional[str],
    total_started_at: float,
    equivalence_started_at: float,
) -> Optional[Dict[str, Any]]:
    return try_rule_based_judgment_grade(
        truth=truth,
        student=student,
        safe_max=safe_max,
        trace_id=trace_id,
        total_started_at=total_started_at,
        equivalence_started_at=equivalence_started_at,
        normalize_answer=self._normalize_answer,
        build_result=self._build_rule_based_grade_result,
    )

def _try_rule_based_arithmetic_grade(
    self,
    question: str,
    truth: str,
    student: str,
    safe_max: float,
    trace_id: Optional[str],
    total_started_at: float,
    equivalence_started_at: float,
) -> Optional[Dict[str, Any]]:
    return try_rule_based_arithmetic_grade(
        question=question,
        truth=truth,
        student=student,
        safe_max=safe_max,
        trace_id=trace_id,
        total_started_at=total_started_at,
        equivalence_started_at=equivalence_started_at,
        answers_equivalent=self._answers_equivalent,
        build_result=self._build_rule_based_grade_result,
    )

def _build_progress_summary(
    self,
    perf_stages: List[Dict[str, Any]],
    retrieval_meta: Dict[str, Any],
    correct: bool,
) -> Dict[str, Any]:
    def format_duration_ms(value: Any) -> str:
        try:
            seconds = float(value or 0.0) / 1000.0
        except Exception:
            seconds = 0.0
        if seconds < 0.1:
            return f"{seconds:.2f} 秒"
        if seconds < 1:
            return f"{seconds:.2f} 秒"
        return f"{seconds:.1f} 秒"

    items: List[Dict[str, Any]] = []
    stage_labels = {
        "answer_equivalence": "答案快速比对",
        "rule_fast_path": "规则直接判定",
        "grade_solver": "独立求解参考答案",
        "grade_solver_skipped": "跳过独立求解",
        "grade_supervisor": "生成判卷结论",
        "recommendation_retrieval": "检索相似题",
    }

    for stage in perf_stages:
        name = str(stage.get("stage") or "")
        label = stage_labels.get(name)
        if not label:
            continue

        timing_ms = float(stage.get("timing_ms") or 0.0)
        detail = f"耗时 {format_duration_ms(timing_ms)}"
        if name == "rule_fast_path":
            detail = str(stage.get("detail") or "已通过规则引擎直接完成判定。").strip()
        elif name == "grade_solver_skipped":
            detail = "已检测到标准答案，直接进入最终判定"
        elif name in {"grade_solver", "grade_supervisor"}:
            model = str(stage.get("model") or "").strip()
            tool_calls = int(stage.get("tool_call_count") or 0)
            detail = f"模型 {model or 'default'}，工具调用 {tool_calls} 次，耗时 {format_duration_ms(timing_ms)}"
        elif name == "recommendation_retrieval":
            matched = int(stage.get("matched") or 0)
            backend = str(stage.get("backend") or "local").strip()
            vector_enabled = bool(stage.get("vector_enabled"))
            detail = f"候选 {matched} 条，后端 {backend or 'local'}，向量检索 {'已启用' if vector_enabled else '未启用'}，耗时 {format_duration_ms(timing_ms)}"

        items.append(
            {
                "stage": name,
                "label": label,
                "detail": detail,
                "status": "done",
                "notes": [str(x).strip() for x in (stage.get("notes") or []) if str(x).strip()],
            }
        )

    if not items:
        items.append(
            {
                "stage": "completed",
                "label": "判卷完成",
                "detail": "本次请求未生成可展示的阶段摘要。",
                "status": "done",
            }
        )

    headline = "判卷已完成"
    if not correct and retrieval_meta.get("matched"):
        headline = "判卷已完成，并生成了相似题推荐"
    return {
        "headline": headline,
        "items": items,
    }
