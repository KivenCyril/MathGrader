from typing import Any, Callable, Dict, List, Optional


def build_rule_based_grade_result(
    *,
    method_id: str,
    recommender_enabled: bool,
    fast_path_kind: str,
    question_type_label: str,
    expected_answer: str,
    student_answer_value: str,
    safe_max: float,
    correct: bool,
    trace_id: Optional[str],
    total_started_at: float,
    equivalence_started_at: float,
    key_steps: List[str],
    question_expr: str,
    student_expr: str,
    elapsed_ms: Callable[[float], float],
) -> Dict[str, Any]:
    reason = (
        f"学生答案正确，正确结果为 {expected_answer}。"
        if correct
        else f"学生答案错误，正确结果为 {expected_answer}；学生结果为 {student_answer_value}。"
    )
    correct_solution = "\n".join([step for step in key_steps if step])
    return {
        "correct": correct,
        "score": safe_max if correct else 0.0,
        "reason": reason,
        "methodUsed": f"{method_id}_rule_fast_path",
        "similarQuestions": [],
        "retrieval": {
            "enabled": recommender_enabled,
            "strategy": "skipped_rule_fast_path",
            "datasetId": None,
            "matched": 0,
        },
        "details": {
            "fast_path": True,
            "fast_path_kind": fast_path_kind,
            "question_type": fast_path_kind,
            "trace_id": trace_id,
            "solver_model": "rule_engine",
            "supervisor_model": "rule_engine",
            "solver_output": {
                "reference_answer": expected_answer,
                "key_steps": correct_solution,
            },
            "supervisor_output": {
                "correct": correct,
                "reason": reason,
                "analysis": {
                    "basis": f"识别为{question_type_label}，采用规则引擎进行确定性判定。",
                    "error_point": "" if correct else f"学生答案与该{question_type_label}的期望结果不一致。",
                    "correct_solution": correct_solution,
                    "suggestion": "" if correct else "建议先统一答案格式，再直接比较最终结果。",
                },
            },
            "rule_input": {
                "question_expr": question_expr.replace("**", "^"),
                "student_expr": student_expr.replace("**", "^"),
            },
            "perf": {
                "total_ms": elapsed_ms(total_started_at),
                "answer_equivalence_ms": elapsed_ms(equivalence_started_at),
                "stages": [
                    {
                        "stage": "answer_equivalence",
                        "timing_ms": elapsed_ms(equivalence_started_at),
                    },
                    {
                        "stage": f"{fast_path_kind}_fast_path",
                        "timing_ms": elapsed_ms(total_started_at),
                    },
                ],
            },
        },
    }


def ensure_supervisor_analysis(
    supervisor_json: Optional[Dict[str, Any]],
    *,
    correct: bool,
    truth: str,
    student: str,
    reference_answer: str,
    solver_steps: str,
) -> Dict[str, Any]:
    data = dict(supervisor_json or {})
    reason = str(data.get("reason") or "").strip()
    analysis = data.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}

    truth_text = str(truth or "").strip()
    student_text = str(student or "").strip()
    reference_text = str(reference_answer or truth_text).strip()
    key_steps = str(solver_steps or "").strip()

    if not reason:
        reason = "学生答案正确。" if correct else "学生答案错误。"
        data["reason"] = reason

    basis = str(analysis.get("basis") or analysis.get("judgement_basis") or "").strip()
    if not basis:
        if correct:
            basis = "根据题目与标准答案比对，学生答案与参考结论一致。"
        elif truth_text:
            basis = f"根据题目与标准答案比对，标准答案为 {truth_text}，学生答案为 {student_text}。"
        else:
            basis = "根据题目要求、参考答案和学生作答综合判断，学生答案不正确。"

    error_point = str(analysis.get("error_point") or analysis.get("mistake_point") or "").strip()
    if not error_point:
        error_point = "无关键错误。" if correct else "学生答案与标准答案或参考结论不一致。"

    correct_solution = str(analysis.get("correct_solution") or analysis.get("fix") or "").strip()
    if not correct_solution:
        if key_steps:
            correct_solution = key_steps
        elif reference_text:
            correct_solution = f"可参考标准答案：{reference_text}。"
        else:
            correct_solution = "请结合题意重新列式或重新梳理解题步骤。"

    suggestion = str(analysis.get("suggestion") or "").strip()
    if not suggestion:
        suggestion = "" if correct else "建议先根据题意列出关系式，再核对最终结果。"

    data["analysis"] = {
        "basis": basis,
        "error_point": error_point,
        "correct_solution": correct_solution,
        "suggestion": suggestion,
    }
    return data
