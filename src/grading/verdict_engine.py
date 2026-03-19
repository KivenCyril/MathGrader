import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from src.grading.progress_trace import append_notes, extract_lines, summarize_tool_trace


ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


class VerdictEngine:
    def __init__(self, engine: Any):
        self.engine = engine

    def evaluate(
        self,
        *,
        question: str,
        truth: str,
        student: str,
        max_score: float,
        model_alias: Optional[str] = None,
        enable_tools: Optional[bool] = None,
        dataset_id: Optional[str] = None,
        level: Optional[str] = None,
        question_id: Optional[str] = None,
        question_type: Optional[str] = None,
        recommendation_count: Optional[int] = None,
        retrieval_top_k: Optional[int] = None,
        enable_recommendation: Optional[bool] = True,
        trace_id: Optional[str] = None,
        need_score: bool = True,
        scoring_mode: Optional[str] = None,
        progress_callback: ProgressCallback = None,
    ) -> Dict[str, Any]:
        total_started_at = time.perf_counter()
        q = str(question or "").strip()
        t = str(truth or "").strip()
        s = str(student or "").strip()
        safe_max = float(max_score if max_score is not None else 1.0)

        def publish(stage: str, label: str, detail: str, status: str, notes: Optional[List[str]] = None) -> None:
            if progress_callback is None:
                return
            progress_callback(
                {
                    "stage": stage,
                    "label": label,
                    "detail": detail,
                    "status": status,
                    "notes": list(notes or []),
                }
            )

        if not q:
            return {"correct": False, "reason": "缺少题目内容。", "methodUsed": self.engine.method_id}

        equivalence_started_at = time.perf_counter()
        publish("answer_equivalence", "答案快速比对", "正在检查学生答案与标准答案是否可直接判定。", "active")

        normalized_question_type = self.engine._normalize_question_type(question_type) or self.engine._classify_question_type(q, t, s)
        rubric = self.engine.rubric_loader.load(normalized_question_type)
        rubric_text = self.engine.rubric_loader.prompt_text(rubric)
        rubric_notes = self.engine.rubric_loader.notes(rubric)

        answer_equivalence_stage: Dict[str, Any] = {
            "stage": "answer_equivalence",
            "timing_ms": self.engine._elapsed_ms(equivalence_started_at),
            "notes": [
                f"题型识别结果：{normalized_question_type or 'unknown'}。",
                "已执行答案快速比对。",
            ],
        }
        for note in rubric_notes[:3]:
            append_notes(answer_equivalence_stage, note)
        perf_stages: List[Dict[str, Any]] = [answer_equivalence_stage]

        if t and self.engine._answers_equivalent(t, s):
            append_notes(answer_equivalence_stage, "学生答案与标准答案等价，直接返回正确。")
            publish(
                "answer_equivalence",
                "答案快速比对",
                f"耗时 {self.engine._elapsed_ms(equivalence_started_at) / 1000.0:.2f} 秒",
                "done",
                answer_equivalence_stage["notes"],
            )
            return {
                "correct": True,
                "reason": "学生答案与参考答案等价。",
                "methodUsed": self.engine.method_id,
                "similarQuestions": [],
                "retrieval": {
                    "enabled": self.engine.recommender.enabled,
                    "strategy": "skipped_fast_path",
                    "datasetId": dataset_id,
                    "matched": 0,
                },
                "details": {
                    "fast_path": True,
                    "fast_path_kind": "answer_equivalence",
                    "trace_id": trace_id,
                    "question_type": normalized_question_type,
                    "rubric": rubric,
                    "progress_summary": self.engine._build_progress_summary(perf_stages, {"matched": 0}, True),
                    "scoring_request": {
                        "need_score": bool(need_score),
                        "requested_mode": str(scoring_mode or "auto"),
                    },
                    "perf": {
                        "total_ms": self.engine._elapsed_ms(total_started_at),
                        "answer_equivalence_ms": self.engine._elapsed_ms(equivalence_started_at),
                        "stages": perf_stages,
                    },
                },
            }

        append_notes(answer_equivalence_stage, "快速比对未命中，继续深入判卷。")
        publish(
            "answer_equivalence",
            "答案快速比对",
            f"耗时 {self.engine._elapsed_ms(equivalence_started_at) / 1000.0:.2f} 秒",
            "done",
            answer_equivalence_stage["notes"],
        )

        if normalized_question_type == "choice":
            result = self.engine._try_rule_based_choice_grade(t, s, safe_max, trace_id, total_started_at, equivalence_started_at)
            if result:
                result["retrieval"]["datasetId"] = dataset_id
                self._inject_metadata(result, rubric, need_score, scoring_mode)
                self._ensure_progress_summary(result, "已按选择题规则直接判定。")
                publish("rule_fast_path", "规则直接判定", "已按选择题规则完成判定。", "done", ["本题命中规则快速路径。"])
                return result

        if normalized_question_type == "judgment":
            result = self.engine._try_rule_based_judgment_grade(t, s, safe_max, trace_id, total_started_at, equivalence_started_at)
            if result:
                result["retrieval"]["datasetId"] = dataset_id
                self._inject_metadata(result, rubric, need_score, scoring_mode)
                self._ensure_progress_summary(result, "已按判断题规则直接判定。")
                publish("rule_fast_path", "规则直接判定", "已按判断题规则完成判定。", "done", ["本题命中规则快速路径。"])
                return result

        if normalized_question_type == "arithmetic":
            result = self.engine._try_rule_based_arithmetic_grade(q, t, s, safe_max, trace_id, total_started_at, equivalence_started_at)
            if result:
                result["retrieval"]["datasetId"] = dataset_id
                self._inject_metadata(result, rubric, need_score, scoring_mode)
                self._ensure_progress_summary(result, "已按简单计算规则直接判定。")
                publish("rule_fast_path", "规则直接判定", "已按简单计算规则完成判定。", "done", ["本题命中规则快速路径。"])
                return result

        use_tools = self.engine.default_tools_enabled if enable_tools is None else bool(enable_tools)
        grade_cfg = (self.engine.config.get("langchain", {}) or {}).get("grade", {}) or {}
        solver_only_when_truth_missing = bool(grade_cfg.get("solver_only_when_truth_missing", True))
        supervisor_tools_when_truth_present = bool(grade_cfg.get("supervisor_tools_when_truth_present", False))
        has_usable_truth = self.engine._has_usable_truth(t)
        skip_solver = solver_only_when_truth_missing and has_usable_truth
        solver_alias = self.engine._get_model_alias("grade", "solver_model", "reviewer", override=model_alias)
        supervisor_alias = self.engine._get_model_alias("grade", "supervisor_model", "grader")
        tool_names = self.engine._resolve_tool_names("grade")

        solver_json: Dict[str, Any] = {}
        solver_res: Dict[str, Any] = {"tool_trace": [], "perf": {}}
        reference_answer = ""
        solver_steps = ""

        if skip_solver:
            reference_answer = t
            solver_json = {
                "reference_answer": reference_answer,
                "key_steps": "",
                "skipped": True,
                "skip_reason": "standard_truth_available",
            }
            solver_stage = {
                "stage": "grade_solver_skipped",
                "model": solver_alias,
                "timing_ms": 0.0,
                "tool_call_count": 0,
                "reason": "standard_truth_available",
                "notes": [
                    "检测到可用标准答案，跳过独立求解。",
                    f"参考答案直接采用标准答案：{reference_answer[:100]}",
                ],
            }
            perf_stages.append(solver_stage)
            publish("grade_solver_skipped", "跳过独立求解", "已检测到标准答案，直接进入最终判定。", "done", solver_stage["notes"])
        else:
            publish("grade_solver", "独立求解参考答案", "正在独立生成参考答案和关键步骤。", "active")
            solver_sys = self.engine._safe_prompt("grade_solver_system")
            solver_user = self.engine._safe_prompt("grade_solver_user", question=q)
            solver_res = self.engine._invoke_with_tools(
                solver_alias,
                [self.engine._system_msg(solver_sys), self.engine._human_msg(solver_user)],
                tool_names=tool_names,
                enable_tools=use_tools,
                temperature=0.1,
            )
            solver_json = self.engine._parse_json(solver_res.get("content", ""))
            reference_answer = str(solver_json.get("reference_answer") or "").strip()
            solver_steps = str(solver_json.get("key_steps") or "").strip()
            solver_perf = solver_res.get("perf") or {}
            solver_stage = {
                "stage": "grade_solver",
                "model": solver_alias,
                "timing_ms": solver_perf.get("timing_ms", 0.0),
                "tool_call_count": solver_perf.get("tool_call_count", 0),
                "notes": [],
            }
            if reference_answer:
                append_notes(solver_stage, f"独立求解参考答案：{reference_answer[:120]}")
            for line in extract_lines(solver_steps, limit=3):
                append_notes(solver_stage, f"求解步骤：{line}")
            for line in summarize_tool_trace(solver_res.get("tool_trace", []), limit=2):
                append_notes(solver_stage, line)
            perf_stages.append(solver_stage)
            publish("grade_solver", "独立求解参考答案", f"模型 {solver_alias or 'default'} 已完成参考求解。", "done", solver_stage["notes"])

        equation_like_student = normalized_question_type == "complex" and "=" in s and bool(re.search(r"[A-Za-z]", s))
        equation_validation = self._build_equation_validation(student=s, truth=t, enabled=equation_like_student)
        supervisor_tool_names = self._select_supervisor_tool_names(tool_names=tool_names, equation_like_student=equation_like_student)

        supervisor_sys = self.engine._safe_prompt("grade_supervisor_system")
        supervisor_user = self.engine._safe_prompt(
            "grade_supervisor_user",
            question=q,
            truth=t,
            student=s,
            reference_answer=reference_answer,
            solver_steps=solver_steps,
            question_type=normalized_question_type,
            equation_like_student="true" if equation_like_student else "false",
            equation_validation=equation_validation,
            max_score=safe_max,
            need_score="true" if need_score else "false",
            scoring_mode=str(scoring_mode or "auto"),
            rubric_text=rubric_text,
        )
        supervisor_enable_tools = use_tools and (not has_usable_truth or supervisor_tools_when_truth_present or equation_like_student)
        publish("grade_supervisor", "生成判卷结论", "正在结合题目、标准答案和学生答案生成判卷结论。", "active")
        supervisor_res = self.engine._invoke_with_tools(
            supervisor_alias,
            [self.engine._system_msg(supervisor_sys), self.engine._human_msg(supervisor_user)],
            tool_names=supervisor_tool_names,
            enable_tools=supervisor_enable_tools,
            temperature=0.0,
        )
        supervisor_json = self.engine._parse_json(supervisor_res.get("content", ""))
        supervisor_perf = supervisor_res.get("perf") or {}
        raw_supervisor_content = str(supervisor_res.get("content") or "").strip()
        if not supervisor_json and raw_supervisor_content:
            supervisor_json = {
                "reason": raw_supervisor_content,
                "analysis": {
                    "basis": raw_supervisor_content,
                    "error_point": "",
                    "correct_solution": solver_steps,
                    "suggestion": "",
                },
            }

        correct = bool(supervisor_json.get("correct", False))
        supervisor_json = self.engine._ensure_supervisor_analysis(
            supervisor_json=supervisor_json,
            correct=correct,
            truth=t,
            student=s,
            reference_answer=reference_answer,
            solver_steps=solver_steps,
        )
        reason = str(supervisor_json.get("reason") or raw_supervisor_content).strip()
        analysis = supervisor_json.get("analysis") if isinstance(supervisor_json.get("analysis"), dict) else {}

        supervisor_stage = {
            "stage": "grade_supervisor",
            "model": supervisor_alias,
            "timing_ms": supervisor_perf.get("timing_ms", 0.0),
            "tool_call_count": supervisor_perf.get("tool_call_count", 0),
            "notes": [],
        }
        if reason:
            append_notes(supervisor_stage, f"监督判定：{reason}")
        if equation_validation not in {"not_applicable", "unavailable"}:
            append_notes(supervisor_stage, "已提供方程验证证据，供监督判定参考。")
        if equation_like_student and supervisor_enable_tools:
            append_notes(supervisor_stage, "方程型作答仅开放方程验证相关工具。")
        for line in extract_lines(analysis.get("basis"), limit=2):
            append_notes(supervisor_stage, f"判定依据：{line}")
        for line in extract_lines(analysis.get("error_point"), limit=1):
            append_notes(supervisor_stage, f"关键错因：{line}")
        for line in extract_lines(analysis.get("suggestion"), limit=1):
            append_notes(supervisor_stage, f"改进建议：{line}")
        for line in summarize_tool_trace(supervisor_res.get("tool_trace", []), limit=2):
            append_notes(supervisor_stage, line)
        perf_stages.append(supervisor_stage)
        publish("grade_supervisor", "生成判卷结论", f"模型 {supervisor_alias or 'default'} 已生成判卷结论。", "done", supervisor_stage["notes"])

        similar_questions: List[Dict[str, Any]] = []
        retrieval_meta: Dict[str, Any] = {
            "enabled": self.engine.recommender.enabled and bool(enable_recommendation),
            "strategy": "skipped_correct",
            "datasetId": dataset_id,
            "matched": 0,
        }
        if not correct and bool(enable_recommendation):
            retrieval_started_at = time.perf_counter()
            publish("recommendation_retrieval", "检索相似题", "正在检索相似题和巩固推荐。", "active")
            similar_questions, retrieval_meta = self.engine.recommender.recommend(
                dataset_id=dataset_id,
                query_question=q,
                exclude_question_id=question_id,
                level=level,
                top_k=retrieval_top_k,
                recommendation_count=recommendation_count,
            )
            retrieval_stage = {
                "stage": "recommendation_retrieval",
                "timing_ms": self.engine._elapsed_ms(retrieval_started_at),
                "matched": retrieval_meta.get("matched", 0),
                "vector_enabled": retrieval_meta.get("vectorEnabled", False),
                "notes": [],
            }
            append_notes(
                retrieval_stage,
                f"检索到 {retrieval_meta.get('matched', 0)} 条候选相似题。",
                "已返回错题巩固推荐。" if similar_questions else "未命中足够相似的推荐题。",
            )
            perf_stages.append(retrieval_stage)
            publish("recommendation_retrieval", "检索相似题", f"已完成相似题检索，命中 {retrieval_meta.get('matched', 0)} 条候选。", "done", retrieval_stage["notes"])
        elif not correct:
            retrieval_meta["strategy"] = "disabled_by_request"

        return {
            "correct": correct,
            "reason": reason or ("学生答案正确。" if correct else "学生答案错误。"),
            "methodUsed": self.engine.method_id,
            "similarQuestions": similar_questions,
            "retrieval": retrieval_meta,
            "details": {
                "trace_id": trace_id,
                "question_type": normalized_question_type,
                "rubric": rubric,
                "solver_model": solver_alias,
                "supervisor_model": supervisor_alias,
                "equation_validation": equation_validation,
                "solver_output": solver_json,
                "supervisor_output": supervisor_json,
                "solver_tool_trace": solver_res.get("tool_trace", []),
                "supervisor_tool_trace": supervisor_res.get("tool_trace", []),
                "progress_summary": self.engine._build_progress_summary(perf_stages, retrieval_meta, correct),
                "scoring_request": {
                    "need_score": bool(need_score),
                    "requested_mode": str(scoring_mode or "auto"),
                },
                "perf": {
                    "total_ms": self.engine._elapsed_ms(total_started_at),
                    "stages": perf_stages,
                },
            },
        }

    def _inject_metadata(self, result: Dict[str, Any], rubric: Dict[str, Any], need_score: bool, scoring_mode: Optional[str]) -> None:
        details = result.get("details")
        if not isinstance(details, dict):
            details = {}
            result["details"] = details
        details["rubric"] = rubric
        details["scoring_request"] = {
            "need_score": bool(need_score),
            "requested_mode": str(scoring_mode or "auto"),
        }

    def _ensure_progress_summary(self, result: Dict[str, Any], note: str) -> None:
        details = result.get("details")
        if not isinstance(details, dict):
            details = {}
            result["details"] = details
        details["progress_summary"] = {
            "headline": "判卷已完成",
            "items": [
                {
                    "stage": "rule_fast_path",
                    "label": "规则直接判定",
                    "detail": "已通过规则引擎直接完成判定。",
                    "status": "done",
                    "notes": [note],
                }
            ],
        }

    def _select_supervisor_tool_names(self, *, tool_names: List[str], equation_like_student: bool) -> List[str]:
        if not equation_like_student:
            return tool_names
        preferred = ["verify_equation_setup", "verify_step", "find_counterexample", "eval_expr"]
        selected = [name for name in preferred if name in tool_names]
        return selected or tool_names

    def _build_equation_validation(self, *, student: str, truth: str, enabled: bool) -> str:
        if not enabled:
            return "not_applicable"
        handler = self.engine.local_tool_handlers.get("verify_equation_setup")
        if handler is None:
            return "unavailable"
        try:
            raw = handler(equation=str(student or "").strip(), expected_answer=str(truth or "").strip())
            parsed = self.engine._parse_json(str(raw or ""))
            if not isinstance(parsed, dict) or not parsed:
                return str(raw or "").strip() or "unavailable"
            return json.dumps(parsed, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "reason": f"equation precheck failed: {exc}"}, ensure_ascii=False)
