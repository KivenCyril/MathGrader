import time
from typing import Any, Callable, Dict, List, Optional

def solve(
    self,
    question: str,
    model_alias: Optional[str] = None,
    enable_tools: Optional[bool] = None,
    mode: Optional[str] = None,
    max_rounds: Optional[int] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    total_started_at = time.perf_counter()
    q = str(question or "").strip()
    if not q:
        return {"error": "缺少题目内容"}

    use_tools = self.default_tools_enabled if enable_tools is None else bool(enable_tools)
    solve_mode = str(mode or self.default_solve_mode).strip().lower()
    loop_rounds = max(1, int(max_rounds or (self.config.get("langchain", {}).get("solve", {}) or {}).get("loop_rounds", 2)))

    solver_alias = self._get_model_alias("solve", "solver_model", "reviewer", override=model_alias)
    critic_alias = self._get_model_alias("solve", "critic_model", "grader")
    tool_names = self._resolve_tool_names("solve")

    sys_prompt = self._safe_prompt("solve_system")
    user_prompt = self._safe_prompt("solve_user", question_text=q)
    first = self._invoke_with_tools(
        solver_alias,
        [self._system_msg(sys_prompt), self._human_msg(user_prompt)],
        tool_names=tool_names,
        enable_tools=use_tools,
        temperature=0.2,
    )
    answer = first.get("content", "")
    rounds = []
    first_perf = first.get("perf") or {}
    perf_stages = [
        {
            "stage": "solve_initial",
            "model": solver_alias,
            "timing_ms": first_perf.get("timing_ms", 0.0),
            "tool_call_count": first_perf.get("tool_call_count", 0),
        }
    ]

    if solve_mode == "single":
        return {
            "answer": answer,
            "details": {
                "mode": "single",
                "trace_id": trace_id,
                "solver_model": solver_alias,
                "tool_trace": first.get("tool_trace", []),
                "rounds": [],
                "perf": {
                    "total_ms": self._elapsed_ms(total_started_at),
                    "stages": perf_stages,
                },
            },
        }

    for idx in range(loop_rounds):
        critic_sys = self._safe_prompt("critic_system")
        critic_user = self._safe_prompt("critic_user", question=q, draft_answer=answer)
        critic = self._invoke_with_tools(
            critic_alias,
            [self._system_msg(critic_sys), self._human_msg(critic_user)],
            tool_names=tool_names,
            enable_tools=use_tools,
            temperature=0.0,
        )
        critic_json = self._parse_json(critic.get("content", ""))
        passed = bool(critic_json.get("pass", False))
        feedback = str(critic_json.get("feedback", "")).strip()
        critic_perf = critic.get("perf") or {}
        round_info = {
            "round": idx + 1,
            "critic_model": critic_alias,
            "critic_pass": passed,
            "critic_feedback": feedback,
            "critic_timing_ms": critic_perf.get("timing_ms", 0.0),
        }
        rounds.append(round_info)
        perf_stages.append(
            {
                "stage": f"critic_round_{idx + 1}",
                "model": critic_alias,
                "timing_ms": critic_perf.get("timing_ms", 0.0),
                "tool_call_count": critic_perf.get("tool_call_count", 0),
            }
        )
        if passed:
            break

        revise_sys = self._safe_prompt("revise_system")
        revise_user = self._safe_prompt(
            "revise_user",
            question=q,
            draft_answer=answer,
            feedback=feedback or "Please correct possible mistakes.",
        )
        revised = self._invoke_with_tools(
            solver_alias,
            [self._system_msg(revise_sys), self._human_msg(revise_user)],
            tool_names=tool_names,
            enable_tools=use_tools,
            temperature=0.2,
        )
        revised_perf = revised.get("perf") or {}
        round_info["revise_timing_ms"] = revised_perf.get("timing_ms", 0.0)
        perf_stages.append(
            {
                "stage": f"revise_round_{idx + 1}",
                "model": solver_alias,
                "timing_ms": revised_perf.get("timing_ms", 0.0),
                "tool_call_count": revised_perf.get("tool_call_count", 0),
            }
        )
        answer = revised.get("content", "")

    return {
        "answer": answer,
        "details": {
            "mode": "loop",
            "trace_id": trace_id,
            "solver_model": solver_alias,
            "critic_model": critic_alias,
            "tool_trace": first.get("tool_trace", []),
            "rounds": rounds,
            "perf": {
                "total_ms": self._elapsed_ms(total_started_at),
                "stages": perf_stages,
            },
        },
    }

def grade(
    self,
    question: str,
    truth: str,
    student: str,
    max_score: float = 1.0,
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
    need_score: Optional[bool] = True,
    scoring_mode: Optional[str] = None,
    rubric_override: Optional[Dict[str, Any]] = None,
    rubric_text: Optional[str] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    safe_max = float(max_score if max_score is not None else 1.0)
    preliminary_question_type = self._normalize_question_type(question_type) or self._classify_question_type(question, truth, student)
    rubric_resolution = {"enabled": False, "used": False, "reason": "not_requested"}
    if rubric_override is not None or str(rubric_text or "").strip():
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "mcp_rubric_parse",
                    "label": "解析评分细则",
                    "detail": "正在通过 MCP 解析和校验外部评分细则。",
                    "status": "active",
                    "notes": [],
                }
            )
        rubric_resolution = self.mcp_rubric_resolver.resolve(
            question_type=preliminary_question_type,
            rubric_override=rubric_override,
            rubric_text=rubric_text,
        )
        if isinstance(rubric_resolution.get("rubric"), dict):
            rubric_override = rubric_resolution.get("rubric")
            rubric_text = None
        rubric_notes = [str(item).strip() for item in (rubric_resolution.get("notes") or []) if str(item).strip()]
        if progress_callback is not None:
            detail = "已完成评分细则解析。"
            if rubric_resolution.get("used"):
                detail = f"已通过 MCP 解析评分细则，来源 {rubric_resolution.get('toolName') or 'mcp'}。"
            elif rubric_resolution.get("enabled"):
                detail = "评分细则 MCP 解析失败，已回退到本地逻辑。"
            progress_callback(
                {
                    "stage": "mcp_rubric_parse",
                    "label": "解析评分细则",
                    "detail": detail,
                    "status": "done",
                    "notes": rubric_notes,
                }
            )
    verdict_result = self.verdict_engine.evaluate(
        question=question,
        truth=truth,
        student=student,
        max_score=safe_max,
        model_alias=model_alias,
        enable_tools=enable_tools,
        dataset_id=dataset_id,
        level=level,
        question_id=question_id,
        question_type=question_type,
        recommendation_count=recommendation_count,
        retrieval_top_k=retrieval_top_k,
        enable_recommendation=enable_recommendation,
        trace_id=trace_id,
        need_score=bool(need_score),
        scoring_mode=scoring_mode,
        rubric_override=rubric_override,
        rubric_text=rubric_text,
        progress_callback=progress_callback,
    )
    details = verdict_result.get("details")
    if not isinstance(details, dict):
        details = {}
        verdict_result["details"] = details
    details["rubric_resolution"] = rubric_resolution
    resolved_question_type = str(details.get("question_type") or question_type or "").strip().lower()
    has_runtime_rubric = bool(rubric_override is not None or str(rubric_text or "").strip())
    if bool(need_score) and resolved_question_type not in {"choice", "judgment", "arithmetic"} and has_runtime_rubric:
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "mcp_scoring_analysis",
                    "label": "评分分析准备",
                    "detail": "正在结合 MCP、评分规则和判卷结论分析得分依据。",
                    "status": "active",
                    "notes": [],
                }
            )
        scoring_analysis = self.mcp_scoring_analyzer.analyze(
            verdict_result=verdict_result,
            question=question,
            truth=truth,
            student=student,
            safe_max=safe_max,
            question_type=resolved_question_type,
            rubric=details.get("rubric") if isinstance(details.get("rubric"), dict) else {},
        )
    else:
        scoring_analysis = {
            "enabled": bool(((self.config.get("langchain", {}) or {}).get("grade", {}) or {}).get("scoring_analysis", {}).get("enabled", False)),
            "used": False,
            "reason": "skipped_without_runtime_rubric" if bool(need_score) and resolved_question_type not in {"choice", "judgment", "arithmetic"} and not has_runtime_rubric else "skipped_for_current_mode",
        }
    details["scoring_analysis"] = scoring_analysis
    scoring_analysis_notes: List[str] = []
    if scoring_analysis.get("used"):
        scoring_analysis_notes.append(f"已调用评分分析工具：{scoring_analysis.get('toolName') or 'mcp'}。")
        scoring_payload = scoring_analysis.get("scoring") if isinstance(scoring_analysis.get("scoring"), dict) else {}
        analysis_summary = str(scoring_payload.get("summary") or "").strip()
        if analysis_summary:
            scoring_analysis_notes.append(analysis_summary)
    elif scoring_analysis.get("enabled"):
        scoring_analysis_notes.append(f"MCP 评分分析未生效：{scoring_analysis.get('reason')}")
    elif bool(need_score) and resolved_question_type not in {"choice", "judgment", "arithmetic"}:
        scoring_analysis_notes.append("当前未启用 MCP 评分分析，继续使用内置评分逻辑。")
    if progress_callback is not None and bool(need_score) and resolved_question_type not in {"choice", "judgment", "arithmetic"}:
        analysis_detail = "评分依据分析已完成。"
        if scoring_analysis.get("used"):
            analysis_detail = f"已完成评分依据分析，来源 {scoring_analysis.get('toolName') or 'mcp'}。"
        elif scoring_analysis.get("enabled"):
            analysis_detail = "评分依据分析已回退到内置逻辑。"
        progress_callback(
            {
                "stage": "mcp_scoring_analysis",
                "label": "评分分析准备",
                "detail": analysis_detail,
                "status": "done",
                "notes": scoring_analysis_notes,
            }
        )
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "score_mapping",
                "label": "生成得分结果",
                "detail": "正在根据判卷结论和评分规则计算最终得分。",
                "status": "active",
                "notes": [],
            }
        )
    scoring = self.scoring_engine.score(
        verdict_result=verdict_result,
        safe_max=safe_max,
        question_type=resolved_question_type,
        need_score=bool(need_score),
        scoring_mode=scoring_mode,
    )
    verdict_result["score"] = float(scoring.get("score", 0.0) or 0.0)
    verdict_result["scoring"] = scoring
    details["scoring"] = scoring
    summary = details.get("progress_summary")
    if isinstance(summary, dict):
        items = summary.get("items")
        if isinstance(items, list):
            if bool(need_score) and resolved_question_type not in {"choice", "judgment", "arithmetic"}:
                analysis_detail = "评分依据分析已完成。"
                if scoring_analysis.get("used"):
                    analysis_detail = f"已完成评分依据分析，来源 {scoring_analysis.get('toolName') or 'mcp'}。"
                elif scoring_analysis.get("enabled"):
                    analysis_detail = "评分依据分析已回退到内置逻辑。"
                items.append(
                    {
                        "stage": "mcp_scoring_analysis",
                        "label": "评分分析准备",
                        "detail": analysis_detail,
                        "status": "done",
                        "notes": scoring_analysis_notes,
                    }
                )
            detail_text = "本次未计算得分。"
            if bool(scoring.get("applied")):
                detail_text = f"评分模式 {scoring.get('mode')}，结果 {verdict_result['score']} / {scoring.get('maxScore')}"
            score_item = {
                "stage": "score_mapping",
                "label": "生成得分结果",
                "detail": detail_text,
                "status": "done",
                "notes": [str(x).strip() for x in (scoring.get("notes") or []) if str(x).strip()],
            }
            items.append(score_item)
            if progress_callback is not None:
                progress_callback(score_item)
    elif progress_callback is not None:
        progress_callback(
            {
                "stage": "score_mapping",
                "label": "生成得分结果",
                "detail": "得分计算已完成。",
                "status": "done",
                "notes": [str(x).strip() for x in (scoring.get("notes") or []) if str(x).strip()],
            }
        )
    return verdict_result
