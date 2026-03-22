import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.grading.progress_trace import append_notes

ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]

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

def _try_rule_fast_path(
    self,
    *,
    normalized_question_type: str,
    question: str,
    truth: str,
    student: str,
    safe_max: float,
    trace_id: Optional[str],
    total_started_at: float,
    equivalence_started_at: float,
    dataset_id: Optional[str],
    rubric: Dict[str, Any],
    need_score: bool,
    scoring_mode: Optional[str],
    publish: Callable[[str, str, str, str, Optional[List[str]]], None],
) -> Optional[Dict[str, Any]]:
    attempts = {
        "choice": {
            "runner": lambda: self.engine._try_rule_based_choice_grade(
                truth, student, safe_max, trace_id, total_started_at, equivalence_started_at
            ),
            "summary_note": "已按选择题规则直接判定。",
            "detail": "已按选择题规则完成判定。",
        },
        "judgment": {
            "runner": lambda: self.engine._try_rule_based_judgment_grade(
                truth, student, safe_max, trace_id, total_started_at, equivalence_started_at
            ),
            "summary_note": "已按判断题规则直接判定。",
            "detail": "已按判断题规则完成判定。",
        },
        "arithmetic": {
            "runner": lambda: self.engine._try_rule_based_arithmetic_grade(
                question, truth, student, safe_max, trace_id, total_started_at, equivalence_started_at
            ),
            "summary_note": "已按简单计算规则直接判定。",
            "detail": "已按简单计算规则完成判定。",
        },
    }
    attempt = attempts.get(normalized_question_type)
    if not attempt:
        return None

    result = attempt["runner"]()
    if not result:
        return None
    return self._finalize_rule_fast_path(
        result=result,
        dataset_id=dataset_id,
        rubric=rubric,
        need_score=need_score,
        scoring_mode=scoring_mode,
        summary_note=str(attempt["summary_note"]),
        publish_detail=str(attempt["detail"]),
        publish=publish,
    )

def _finalize_rule_fast_path(
    self,
    *,
    result: Dict[str, Any],
    dataset_id: Optional[str],
    rubric: Dict[str, Any],
    need_score: bool,
    scoring_mode: Optional[str],
    summary_note: str,
    publish_detail: str,
    publish: Callable[[str, str, str, str, Optional[List[str]]], None],
) -> Dict[str, Any]:
    result["retrieval"]["datasetId"] = dataset_id
    self._inject_metadata(result, rubric, need_score, scoring_mode)
    self._ensure_progress_summary(result, summary_note)
    publish("rule_fast_path", "规则直接判定", publish_detail, "done", ["本题命中规则快速路径。"])
    return result

def _run_retrieval(
    self,
    *,
    correct: bool,
    enable_recommendation: Optional[bool],
    dataset_id: Optional[str],
    question: str,
    question_id: Optional[str],
    level: Optional[str],
    retrieval_top_k: Optional[int],
    recommendation_count: Optional[int],
    perf_stages: List[Dict[str, Any]],
    publish: Callable[[str, str, str, str, Optional[List[str]]], None],
    progress_callback: ProgressCallback,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    retrieval_meta: Dict[str, Any] = {
        "enabled": self.engine.recommender.enabled and bool(enable_recommendation),
        "strategy": "skipped_correct",
        "datasetId": dataset_id,
        "matched": 0,
    }
    if correct:
        return [], retrieval_meta
    if not bool(enable_recommendation):
        retrieval_meta["strategy"] = "disabled_by_request"
        return [], retrieval_meta

    retrieval_started_at = time.perf_counter()
    publish("recommendation_retrieval", "检索相似题", "正在检索相似题和巩固推荐。", "active")
    similar_questions, retrieval_meta = self.engine.recommender.recommend(
        dataset_id=dataset_id,
        query_question=question,
        exclude_question_id=question_id,
        level=level,
        top_k=retrieval_top_k,
        recommendation_count=recommendation_count,
        progress_callback=self._build_retrieval_progress_callback(
            dataset_id=dataset_id,
            publish=publish,
            progress_callback=progress_callback,
        ),
    )
    retrieval_stage = {
        "stage": "recommendation_retrieval",
        "timing_ms": self.engine._elapsed_ms(retrieval_started_at),
        "matched": retrieval_meta.get("matched", 0),
        "backend": retrieval_meta.get("backend", "local"),
        "vector_enabled": retrieval_meta.get("vectorEnabled", False),
        "notes": [],
    }
    append_notes(
        retrieval_stage,
        f"检索到 {retrieval_meta.get('matched', 0)} 条候选相似题。",
        "已返回错题巩固推荐。" if similar_questions else "未命中足够相似的推荐题。",
    )
    perf_stages.append(retrieval_stage)
    publish(
        "recommendation_retrieval",
        "检索相似题",
        f"已完成相似题检索，命中 {retrieval_meta.get('matched', 0)} 条候选。",
        "done",
        retrieval_stage["notes"],
    )
    return similar_questions, retrieval_meta

def _build_retrieval_progress_callback(
    self,
    *,
    dataset_id: Optional[str],
    publish: Callable[[str, str, str, str, Optional[List[str]]], None],
    progress_callback: ProgressCallback,
) -> Callable[[Dict[str, Any]], None]:
    def retrieval_progress_callback(event: Dict[str, Any]) -> None:
        phase = str(event.get("phase") or "").strip()
        if phase == "prepare":
            publish(
                "recommendation_retrieval",
                "检索相似题",
                "正在为当前数据集准备推荐索引。",
                "active",
                [f"dataset: {dataset_id or '-'}", f"collection: {event.get('collectionName') or '-'}"],
            )
            if progress_callback is not None:
                progress_callback({"stage": "recommendation_retrieval", "progress": 0.0})
            return
        if phase == "import" and progress_callback is not None:
            imported_docs = int(event.get("importedDocs") or 0)
            total_docs = int(event.get("totalDocs") or 0)
            batch_index = int(event.get("batchIndex") or 0)
            total_batches = int(event.get("totalBatches") or 0)
            progress_callback(
                {
                    "stage": "recommendation_retrieval",
                    "label": "检索相似题",
                    "detail": f"正在建立推荐索引：{imported_docs}/{total_docs}，批次 {batch_index}/{total_batches}",
                    "status": "active",
                    "notes": [f"collection: {event.get('collectionName') or '-'}"],
                    "progress": event.get("progress"),
                }
            )

    return retrieval_progress_callback

def _select_supervisor_tool_names(self, *, tool_names: List[str], equation_like_student: bool) -> List[str]:
    if not equation_like_student:
        return tool_names
    preferred = ["verify_equation_setup", "verify_step", "find_counterexample", "eval_expr"]
    selected = [name for name in preferred if name in tool_names]
    return selected or tool_names

def _extract_equation_candidate(self, student: str) -> str:
    text = str(student or "").strip()
    if not text:
        return ""
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:table|tbody|tr|td|div|p|span|strong|em|section)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("$", " ")
    text = re.sub(r"\\left|\\right", "", text)
    text = re.sub(r"\\cdot", "*", text)
    while True:
        updated = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1/\2)", text)
        if updated == text:
            break
        text = updated
    matches = re.findall(r"([A-Za-z0-9\(\)\[\]\{\}\\+\-*/\^=.\s]+=[A-Za-z0-9\(\)\[\]\{\}\\+\-*/\^=.\s]+)", text)
    equation_lines = [str(item).strip() for item in matches if str(item).strip()]
    if not equation_lines:
        equation_lines = [line.strip() for line in re.split(r"[\r\n]+", text) if "=" in line and line.strip()]
    if equation_lines:
        def score(line: str) -> int:
            return sum(1 for ch in line if ch in "=+-*/^()[]{}0123456789" or ch.isalpha())

        candidate = max(equation_lines, key=score)
        eq_index = candidate.find("=")
        left_side = candidate[:eq_index]
        start_candidates = [idx for idx in (left_side.find(token) for token in ("(", "[", "{")) if idx >= 0]
        first_digit = next((idx for idx, ch in enumerate(left_side) if ch.isdigit()), -1)
        if first_digit >= 0:
            start_candidates.append(first_digit)
        start = min(start_candidates) if start_candidates else -1
        if start >= 0:
            candidate = candidate[start:]
        return " ".join(candidate.split())
    if "=" in text:
        return text
    return ""

def _has_equation_validation_evidence(self, evidence: str) -> bool:
    text = str(evidence or "").strip()
    if not text or text in {"not_applicable", "unavailable"}:
        return False
    parsed = self.engine._parse_json(text)
    return bool(parsed) if isinstance(parsed, dict) else True

def _build_equation_validation(self, *, student: str, truth: str, enabled: bool) -> str:
    if not enabled:
        return "not_applicable"
    handler = self.engine.local_tool_handlers.get("verify_equation_setup")
    if handler is None:
        return "unavailable"
    equation = self._extract_equation_candidate(student)
    if not equation:
        return "unavailable"
    try:
        raw = handler(equation=equation, expected_answer=str(truth or "").strip())
        parsed = self.engine._parse_json(str(raw or ""))
        if not isinstance(parsed, dict) or not parsed:
            return str(raw or "").strip() or "unavailable"
        return json.dumps(parsed, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": f"equation precheck failed: {exc}"}, ensure_ascii=False)
