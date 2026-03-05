import json
from typing import Any, Dict, List, Optional, Tuple

from src.langchain_engine.local_tools import build_local_langchain_tools
from src.langchain_engine.retrieval import HybridRecommendationService
from src.llm_clients.base_client import LLMClient
from src.services.prompt_service import PromptLoader
from src.tools.tool_hub import ToolHub

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
except Exception:
    AIMessage = None
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

    def _invoke_with_tools(
        self,
        model_alias: str,
        messages: List[Any],
        tool_names: List[str],
        enable_tools: bool,
        temperature: float,
    ) -> Dict[str, Any]:
        cfg = self._get_model_config(model_alias)
        llm = self._build_langchain_model(cfg, temperature)
        all_defs, all_handlers = self._collect_tools()
        all_names = list(all_defs.keys())
        selected_names = self._expand_tool_names(tool_names, all_names) if enable_tools else []
        selected_defs = [all_defs[n] for n in selected_names if n in all_defs]
        selected_handlers = {n: all_handlers[n] for n in selected_names if n in all_handlers}

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
            return {"content": str(content), "tool_trace": [], "model_alias": model_alias}

        if not enable_tools or not selected_defs:
            ai = llm.invoke(messages)
            return {"content": self._lc_content_to_text(getattr(ai, "content", "")), "tool_trace": [], "model_alias": model_alias}

        runner = llm.bind_tools(selected_defs)
        convo = list(messages)
        trace = []
        final_ai = None

        for _ in range(self.max_tool_rounds + 1):
            ai = runner.invoke(convo)
            final_ai = ai
            convo.append(ai)
            tool_calls = getattr(ai, "tool_calls", []) or []
            if not tool_calls:
                break
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
                if handler is None:
                    result = f"Error: tool {name} not found"
                else:
                    try:
                        result = handler(**args)
                    except Exception as e:
                        result = f"Error: tool {name} failed: {e}"

                trace.append({"name": name, "args": args, "result": str(result)[:300]})
                convo.append(self._tool_msg(str(result), str(tc.get("id") or "")))

        content = self._lc_content_to_text(getattr(final_ai, "content", "") if final_ai else "")
        return {"content": content, "tool_trace": trace, "model_alias": model_alias}

    def _answers_equivalent(self, truth: str, student: str) -> bool:
        t = self._normalize_answer(truth)
        s = self._normalize_answer(student)
        if t and t == s:
            return True
        try:
            from sympy import N, simplify, sympify

            lt = sympify(truth.replace("^", "**"))
            ls = sympify(student.replace("^", "**"))
            diff = simplify(lt - ls)
            if diff == 0:
                return True
            if not (lt.free_symbols or ls.free_symbols):
                return abs(float(N(diff))) <= 1e-9
        except Exception:
            return False
        return False

    def solve(
        self,
        question: str,
        model_alias: Optional[str] = None,
        enable_tools: Optional[bool] = None,
        mode: Optional[str] = None,
        max_rounds: Optional[int] = None,
    ) -> Dict[str, Any]:
        q = str(question or "").strip()
        if not q:
            return {"error": "Missing question text"}

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

        if solve_mode == "single":
            return {
                "answer": answer,
                "details": {
                    "mode": "single",
                    "solver_model": solver_alias,
                    "tool_trace": first.get("tool_trace", []),
                    "rounds": [],
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
            rounds.append(
                {
                    "round": idx + 1,
                    "critic_model": critic_alias,
                    "critic_pass": passed,
                    "critic_feedback": feedback,
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
            answer = revised.get("content", "")

        return {
            "answer": answer,
            "details": {
                "mode": "loop",
                "solver_model": solver_alias,
                "critic_model": critic_alias,
                "tool_trace": first.get("tool_trace", []),
                "rounds": rounds,
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
        recommendation_count: Optional[int] = None,
        retrieval_top_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        q = str(question or "").strip()
        t = str(truth or "").strip()
        s = str(student or "").strip()
        safe_max = float(max_score if max_score is not None else 1.0)

        if not q:
            return {"correct": False, "score": 0, "reason": "缺少题目文本。", "methodUsed": self.method_id}

        if t and self._answers_equivalent(t, s):
            return {
                "correct": True,
                "score": safe_max,
                "reason": "学生答案与标准答案等价。",
                "methodUsed": self.method_id,
                "details": {"fast_path": True},
                "similarQuestions": [],
                "retrieval": {
                    "enabled": self.recommender.enabled,
                    "strategy": "skipped_fast_path",
                    "datasetId": dataset_id,
                    "matched": 0,
                },
            }

        use_tools = self.default_tools_enabled if enable_tools is None else bool(enable_tools)
        solver_alias = self._get_model_alias("grade", "solver_model", "reviewer", override=model_alias)
        supervisor_alias = self._get_model_alias("grade", "supervisor_model", "grader")
        tool_names = self._resolve_tool_names("grade")

        solver_sys = self._safe_prompt("grade_solver_system")
        solver_user = self._safe_prompt("grade_solver_user", question=q)
        solver_res = self._invoke_with_tools(
            solver_alias,
            [self._system_msg(solver_sys), self._human_msg(solver_user)],
            tool_names=tool_names,
            enable_tools=use_tools,
            temperature=0.1,
        )
        solver_json = self._parse_json(solver_res.get("content", ""))
        reference_answer = str(solver_json.get("reference_answer") or "").strip()
        solver_steps = str(solver_json.get("key_steps") or "").strip()

        supervisor_sys = self._safe_prompt("grade_supervisor_system")
        supervisor_user = self._safe_prompt(
            "grade_supervisor_user",
            question=q,
            truth=t,
            student=s,
            reference_answer=reference_answer,
            solver_steps=solver_steps,
        )
        supervisor_res = self._invoke_with_tools(
            supervisor_alias,
            [self._system_msg(supervisor_sys), self._human_msg(supervisor_user)],
            tool_names=tool_names,
            enable_tools=use_tools,
            temperature=0.0,
        )
        supervisor_json = self._parse_json(supervisor_res.get("content", ""))
        correct = bool(supervisor_json.get("correct", False))
        reason = str(supervisor_json.get("reason") or "").strip()
        score = safe_max if correct else 0.0
        similar_questions: List[Dict[str, Any]] = []
        retrieval_meta: Dict[str, Any] = {
            "enabled": self.recommender.enabled,
            "strategy": "skipped_correct",
            "datasetId": dataset_id,
            "matched": 0,
        }
        if not correct:
            similar_questions, retrieval_meta = self.recommender.recommend(
                dataset_id=dataset_id,
                query_question=q,
                exclude_question_id=question_id,
                level=level,
                top_k=retrieval_top_k,
                recommendation_count=recommendation_count,
            )

        return {
            "correct": correct,
            "score": score,
            "reason": reason or ("判定正确。" if correct else "判定错误。"),
            "methodUsed": self.method_id,
            "similarQuestions": similar_questions,
            "retrieval": retrieval_meta,
            "details": {
                "solver_model": solver_alias,
                "supervisor_model": supervisor_alias,
                "solver_output": solver_json,
                "supervisor_output": supervisor_json,
                "solver_tool_trace": solver_res.get("tool_trace", []),
                "supervisor_tool_trace": supervisor_res.get("tool_trace", []),
            },
        }
