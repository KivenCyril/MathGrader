import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.grading import MCPScoringAnalyzer, RubricLoader, ScoringEngine, VerdictEngine

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
from src.langchain_engine.local_tools import build_local_langchain_tools
from src.langchain_engine.retrieval import HybridRecommendationService
from src.llm_clients.base_client import LLMClient
from src.services.prompt_service import PromptLoader
from src.tools.tool_hub import ToolHub

try:
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
except Exception:
    HumanMessage = None
    SystemMessage = None
    ToolMessage = None
    ChatOpenAI = None


class LangChainMathEngine:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.prompt_loader = PromptLoader()
        self.tool_hub = ToolHub.from_runtime_config(self.config)
        self.local_tool_defs, self.local_tool_handlers = build_local_langchain_tools()
        self.recommender = HybridRecommendationService(self.config)
        self.verdict_engine = VerdictEngine(self)
        self.scoring_engine = ScoringEngine()
        self.mcp_scoring_analyzer = MCPScoringAnalyzer(self)
        self.rubric_loader = RubricLoader(self.config)

        lc_cfg = self.config.get("langchain", {}) or {}
        self.method_id = str(lc_cfg.get("method_id") or "langchain_solver_supervisor")
        self.max_tool_rounds = max(1, int(lc_cfg.get("max_tool_rounds", 4)))
        self.default_tools_enabled = bool(lc_cfg.get("enable_tools_by_default", True))
        self.default_solve_mode = str(lc_cfg.get("solve_mode", "loop")).strip() or "loop"

        prompts_cfg = lc_cfg.get("prompts", {}) or {}
        self.prompt_keys = {
            "solve_system": prompts_cfg.get("solve_system", "v2_lc_solve_system"),
            "solve_user": prompts_cfg.get("solve_user", "v2_lc_solve_user"),
            "critic_system": prompts_cfg.get("critic_system", "v2_lc_critic_system"),
            "critic_user": prompts_cfg.get("critic_user", "v2_lc_critic_user"),
            "revise_system": prompts_cfg.get("revise_system", "v2_lc_revise_system"),
            "revise_user": prompts_cfg.get("revise_user", "v2_lc_revise_user"),
            "grade_solver_system": prompts_cfg.get("grade_solver_system", "v2_lc_grade_solver_system"),
            "grade_solver_user": prompts_cfg.get("grade_solver_user", "v2_lc_grade_solver_user"),
            "grade_supervisor_system": prompts_cfg.get("grade_supervisor_system", "v2_lc_grade_supervisor_system"),
            "grade_supervisor_user": prompts_cfg.get("grade_supervisor_user", "v2_lc_grade_supervisor_user"),
        }

    def _system_msg(self, content: str):
        if SystemMessage is not None:
            return SystemMessage(content=content)
        return {"role": "system", "content": str(content)}

    def _human_msg(self, content: str):
        if HumanMessage is not None:
            return HumanMessage(content=content)
        return {"role": "user", "content": str(content)}

    def _tool_msg(self, content: str, tool_call_id: str):
        if ToolMessage is not None:
            return ToolMessage(content=str(content), tool_call_id=str(tool_call_id))
        return {"role": "tool", "content": str(content), "tool_call_id": str(tool_call_id)}

    def list_methods(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": self.method_id,
                "kind": "langchain",
                "label": "LangChain Solver+Supervisor",
                "isDefault": True,
            }
        ]

    def _normalize_answer(self, value: Any) -> str:
        if value is None:
            return ""
        s = str(value).strip()
        s = s.translate(
            str.maketrans(
                {
                    "\uFF08": "(",
                    "\uFF09": ")",
                    "\uFF0C": ",",
                    "\u3002": ".",
                }
            )
        )
        return "".join(s.split()).lower()

    def _parse_json(self, content: str) -> Dict[str, Any]:
        text = str(content or "").strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end >= start:
            text = text[start : end + 1]
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except Exception:
            return {}
        return {}

    def _safe_prompt(self, key: str, **kwargs) -> str:
        name = self.prompt_keys[key]
        try:
            return self.prompt_loader.load(name, **kwargs)
        except Exception as e:
            return f"[PromptMissing:{name}] {e}\n{json.dumps(kwargs, ensure_ascii=False)}"

    def _get_model_alias(self, section: str, key: str, fallback_role: str, override: Optional[str] = None) -> str:
        if override:
            return str(override).strip()
        lc_cfg = self.config.get("langchain", {}) or {}
        sec = lc_cfg.get(section, {}) or {}
        alias = str(sec.get(key) or "").strip()
        if alias:
            return alias
        role_alias = str((self.config.get("roles", {}) or {}).get(fallback_role) or "").strip()
        if role_alias:
            return role_alias
        models = list((self.config.get("models", {}) or {}).keys())
        return models[0] if models else ""

    def _get_model_config(self, alias: str) -> Dict[str, Any]:
        return dict((self.config.get("models", {}) or {}).get(alias, {}) or {})

    def _collect_tools(self) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
        defs = {}
        handlers = {}

        hub_defs = self.tool_hub.get_tools()
        hub_map = self.tool_hub.get_tool_map()
        for item in hub_defs:
            name = ((item.get("function") or {}).get("name") or "").strip()
            if name:
                defs[name] = item
        handlers.update(hub_map)

        defs.update(self.local_tool_defs)
        handlers.update(self.local_tool_handlers)
        return defs, handlers

    def _expand_tool_names(self, names: List[str], all_names: List[str]) -> List[str]:
        out = []
        seen = set()
        for name in names:
            n = str(name).strip()
            if not n:
                continue
            if n in {"*", "all"}:
                for item in all_names:
                    if item not in seen:
                        seen.add(item)
                        out.append(item)
                continue
            if n == "mcp:*":
                for item in all_names:
                    if item in {"calculate", "ocr_math", "img2latex", "eval_expr", "verify_step", "find_counterexample"}:
                        continue
                    if item not in seen:
                        seen.add(item)
                        out.append(item)
                continue
            if n in all_names and n not in seen:
                seen.add(n)
                out.append(n)
        return out

    def _resolve_tool_names(self, section: str) -> List[str]:
        lc_cfg = self.config.get("langchain", {}) or {}
        sec_cfg = lc_cfg.get(section, {}) or {}
        default_names = [
                "calculate",
                "ocr_math",
                "img2latex",
                "eval_expr",
                "verify_step",
                "verify_equation_setup",
                "find_counterexample",
          ]
        names = sec_cfg.get("tools") or default_names
        if not isinstance(names, list):
            names = default_names
        return [str(x).strip() for x in names if str(x).strip()]

    def _build_langchain_model(self, cfg: Dict[str, Any], temperature: float):
        if ChatOpenAI is None:
            return None
        api_key = str(cfg.get("api_key") or "").strip()
        if not api_key:
            return None
        base_url = str(cfg.get("base_url") or "https://api.openai.com/v1").strip()
        model_name = str(cfg.get("model_name") or "gpt-4o-mini").strip()
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            timeout=60,
            max_retries=1,
        )

    def _lc_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    txt = item.get("text")
                    if txt is not None:
                        parts.append(str(txt))
                    else:
                        parts.append(json.dumps(item, ensure_ascii=False))
                else:
                    parts.append(str(item))
            return "\n".join(parts).strip()
        return str(content or "")

    def _to_openai_messages(self, messages: List[Any]) -> List[Dict[str, Any]]:
        out = []
        for msg in messages:
            if isinstance(msg, dict):
                role = str(msg.get("role") or "user")
                payload = {"role": role, "content": str(msg.get("content") or "")}
                if role == "tool":
                    payload["tool_call_id"] = str(msg.get("tool_call_id") or "")
                if role == "assistant" and msg.get("tool_calls"):
                    payload["tool_calls"] = msg.get("tool_calls")
                out.append(payload)
                continue
            mtype = getattr(msg, "type", "")
            content = self._lc_content_to_text(getattr(msg, "content", ""))
            if mtype == "system":
                out.append({"role": "system", "content": content})
            elif mtype == "human":
                out.append({"role": "user", "content": content})
            elif mtype == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": getattr(msg, "tool_call_id", ""),
                        "content": content,
                    }
                )
            else:
                extra = {}
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    extra["tool_calls"] = tool_calls
                out.append({"role": "assistant", "content": content, **extra})
        return out

    def _elapsed_ms(self, started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000.0, 2)

    def _invoke_with_tools(
        self,
        model_alias: str,
        messages: List[Any],
        tool_names: List[str],
        enable_tools: bool,
        temperature: float,
    ) -> Dict[str, Any]:
        started_at = time.perf_counter()
        cfg = self._get_model_config(model_alias)
        llm = self._build_langchain_model(cfg, temperature)
        all_defs, all_handlers = self._collect_tools()
        all_names = list(all_defs.keys())
        selected_names = self._expand_tool_names(tool_names, all_names) if enable_tools else []
        selected_defs = [all_defs[n] for n in selected_names if n in all_defs]
        selected_handlers = {n: all_handlers[n] for n in selected_names if n in all_handlers}
        metadata = {
            "timing_ms": 0.0,
            "tool_rounds": 0,
            "tool_call_count": 0,
            "selected_tool_count": len(selected_names),
            "selected_tools": selected_names,
            "used_langchain_runtime": llm is not None,
            "llm_round_timings_ms": [],
        }

        if llm is None:
            fallback_client = LLMClient(cfg)
            data = fallback_client.chat_completion(
                self._to_openai_messages(messages),
                temperature=temperature,
                tools=selected_defs if enable_tools else None,
                tool_map=selected_handlers if enable_tools else None,
                max_tool_rounds=self.max_tool_rounds,
            )
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            metadata["timing_ms"] = self._elapsed_ms(started_at)
            perf = dict((data.get("_perf") or {}))
            if perf:
                metadata["tool_rounds"] = perf.get("tool_rounds", metadata["tool_rounds"])
                metadata["tool_call_count"] = perf.get("tool_call_count", metadata["tool_call_count"])
                metadata["llm_round_timings_ms"] = perf.get("llm_round_timings_ms", metadata["llm_round_timings_ms"])
                metadata["timing_ms"] = perf.get("timing_ms", metadata["timing_ms"])
            tool_trace = list(data.get("_tool_trace") or [])
            return {"content": str(content), "tool_trace": tool_trace, "model_alias": model_alias, "perf": metadata}

        if not enable_tools or not selected_defs:
            llm_started_at = time.perf_counter()
            ai = llm.invoke(messages)
            metadata["llm_round_timings_ms"] = [self._elapsed_ms(llm_started_at)]
            metadata["timing_ms"] = self._elapsed_ms(started_at)
            return {
                "content": self._lc_content_to_text(getattr(ai, "content", "")),
                "tool_trace": [],
                "model_alias": model_alias,
                "perf": metadata,
            }

        runner = llm.bind_tools(selected_defs)
        convo = list(messages)
        trace = []
        final_ai = None

        for round_idx in range(self.max_tool_rounds + 1):
            llm_started_at = time.perf_counter()
            ai = runner.invoke(convo)
            metadata["llm_round_timings_ms"].append(self._elapsed_ms(llm_started_at))
            final_ai = ai
            convo.append(ai)
            tool_calls = getattr(ai, "tool_calls", []) or []
            if not tool_calls:
                break
            metadata["tool_rounds"] = round_idx + 1
            for tc in tool_calls:
                name = str(tc.get("name") or "").strip()
                args = tc.get("args") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                if not isinstance(args, dict):
                    args = {}

                handler = selected_handlers.get(name)
                tool_started_at = time.perf_counter()
                if handler is None:
                    result = f"Error: tool {name} not found"
                else:
                    try:
                        result = handler(**args)
                    except Exception as e:
                        result = f"Error: tool {name} failed: {e}"

                metadata["tool_call_count"] = int(metadata["tool_call_count"]) + 1
                trace.append(
                    {
                        "name": name,
                        "args": args,
                        "result": str(result)[:300],
                        "timing_ms": self._elapsed_ms(tool_started_at),
                    }
                )
                convo.append(self._tool_msg(str(result), str(tc.get("id") or "")))

        content = self._lc_content_to_text(getattr(final_ai, "content", "") if final_ai else "")
        metadata["timing_ms"] = self._elapsed_ms(started_at)
        return {"content": content, "tool_trace": trace, "model_alias": model_alias, "perf": metadata}

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
                vector_enabled = bool(stage.get("vector_enabled"))
                detail = f"候选 {matched} 条，向量重排 {'已启用' if vector_enabled else '未启用'}，耗时 {format_duration_ms(timing_ms)}"

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
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        safe_max = float(max_score if max_score is not None else 1.0)
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
            progress_callback=progress_callback,
        )
        details = verdict_result.get("details")
        if not isinstance(details, dict):
            details = {}
            verdict_result["details"] = details
        resolved_question_type = str(details.get("question_type") or question_type or "").strip().lower()
        if bool(need_score) and resolved_question_type not in {"choice", "judgment", "arithmetic"}:
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
            )
        else:
            scoring_analysis = {"enabled": False, "used": False, "reason": "skipped_for_current_mode"}
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
