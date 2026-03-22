from typing import Any, Dict, Optional

from src.grading import MCPRubricResolver, MCPScoringAnalyzer, RubricLoader, ScoringEngine, VerdictEngine
from src.langchain_engine.engine_grading_support import (
    _answers_equivalent,
    _build_mixed_fraction_notes,
    _build_progress_summary,
    _build_rule_based_grade_result,
    _classify_question_type,
    _ensure_supervisor_analysis,
    _evaluate_arithmetic_expression,
    _extract_arithmetic_expression,
    _extract_math_value_expression,
    _has_usable_truth,
    _normalize_arithmetic_text,
    _normalize_choice_answer,
    _normalize_judgment_answer,
    _normalize_question_type,
    _question_type_label,
    _try_rule_based_arithmetic_grade,
    _try_rule_based_choice_grade,
    _try_rule_based_judgment_grade,
)
from src.langchain_engine.engine_runtime import (
    _build_langchain_model,
    _coerce_positive_int,
    _collect_tools,
    _elapsed_ms,
    _expand_tool_names,
    _get_model_alias,
    _get_model_config,
    _human_msg,
    _invoke_with_tools,
    _lc_content_to_text,
    _normalize_answer,
    _parse_json,
    _resolve_tool_names,
    _safe_prompt,
    _system_msg,
    _to_openai_messages,
    _tool_msg,
)
from src.langchain_engine.engine_workflows import grade, solve
from src.langchain_engine.local_tools import build_local_langchain_tools
from src.langchain_engine.retrieval import HybridRecommendationService
from src.services.prompt_service import PromptLoader
from src.tools.tool_hub import ToolHub


class LangChainMathEngine:
    _system_msg = _system_msg
    _human_msg = _human_msg
    _tool_msg = _tool_msg
    _normalize_answer = _normalize_answer
    _parse_json = _parse_json
    _safe_prompt = _safe_prompt
    _get_model_alias = _get_model_alias
    _get_model_config = _get_model_config
    _collect_tools = _collect_tools
    _expand_tool_names = _expand_tool_names
    _resolve_tool_names = _resolve_tool_names
    _coerce_positive_int = _coerce_positive_int
    _build_langchain_model = _build_langchain_model
    _lc_content_to_text = _lc_content_to_text
    _to_openai_messages = _to_openai_messages
    _elapsed_ms = _elapsed_ms
    _invoke_with_tools = _invoke_with_tools

    _answers_equivalent = _answers_equivalent
    _normalize_arithmetic_text = _normalize_arithmetic_text
    _extract_arithmetic_expression = _extract_arithmetic_expression
    _extract_math_value_expression = _extract_math_value_expression
    _evaluate_arithmetic_expression = _evaluate_arithmetic_expression
    _build_mixed_fraction_notes = _build_mixed_fraction_notes
    _normalize_choice_answer = _normalize_choice_answer
    _normalize_judgment_answer = _normalize_judgment_answer
    _classify_question_type = _classify_question_type
    _normalize_question_type = _normalize_question_type
    _question_type_label = _question_type_label
    _has_usable_truth = _has_usable_truth
    _build_rule_based_grade_result = _build_rule_based_grade_result
    _ensure_supervisor_analysis = _ensure_supervisor_analysis
    _try_rule_based_choice_grade = _try_rule_based_choice_grade
    _try_rule_based_judgment_grade = _try_rule_based_judgment_grade
    _try_rule_based_arithmetic_grade = _try_rule_based_arithmetic_grade
    _build_progress_summary = _build_progress_summary

    solve = solve
    grade = grade

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.prompt_loader = PromptLoader()
        self.tool_hub = ToolHub.from_runtime_config(self.config)
        self.local_tool_defs, self.local_tool_handlers = build_local_langchain_tools()
        self.recommender = HybridRecommendationService(self.config)
        self.verdict_engine = VerdictEngine(self)
        self.scoring_engine = ScoringEngine()
        self.mcp_scoring_analyzer = MCPScoringAnalyzer(self)
        self.mcp_rubric_resolver = MCPRubricResolver(self)
        self.rubric_loader = RubricLoader(self.config)

        lc_cfg = self.config.get("langchain", {}) or {}
        self.method_id = str(lc_cfg.get("method_id") or "langchain_solver_supervisor")
        self.max_tool_rounds = max(1, int(lc_cfg.get("max_tool_rounds", 4)))
        self.default_tools_enabled = bool(lc_cfg.get("enable_tools_by_default", True))
        self.default_solve_mode = str(lc_cfg.get("solve_mode", "loop")).strip() or "loop"
        grade_cfg = lc_cfg.get("grade", {}) or {}
        self.grade_solver_max_tokens = self._coerce_positive_int(grade_cfg.get("solver_max_tokens"), default=180)
        self.grade_supervisor_max_tokens = self._coerce_positive_int(grade_cfg.get("supervisor_max_tokens"), default=240)

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
