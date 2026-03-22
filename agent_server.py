import json
import sys
import threading
import time
import uuid
from typing import Any, Dict

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from werkzeug.serving import WSGIRequestHandler

from src.grading.grade_job_store import GradeJobStore
from src.langchain_engine import LangChainMathEngine
from src.services.config_service import config_service
from src.services.ocr_service import OCRService

load_dotenv()

app = Flask(__name__)
engine = LangChainMathEngine(config_service.config)
job_store = GradeJobStore()
print_lock = threading.Lock()

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def parse_max_score(value, default=1.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def parse_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def parse_int(value, default=1):
    try:
        return int(value)
    except Exception:
        return int(default)


def log_trace(trace: dict):
    enabled = config_service.config.get("trace", {}).get("enabled", True)
    if not enabled:
        return
    safe_print("[Trace] " + json.dumps(compact_trace(trace), ensure_ascii=False))


def elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 2)


def request_trace_id() -> str:
    incoming = str(request.headers.get("X-Trace-Id") or "").strip()
    return incoming or uuid.uuid4().hex[:12]


def ensure_details(result: dict) -> dict:
    details = result.get("details")
    if not isinstance(details, dict):
        details = {}
        result["details"] = details
    return details


def safe_print(message: str) -> None:
    with print_lock:
        print(message)


def compact_perf(perf: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    if not isinstance(perf, dict):
        return compact
    if "total_ms" in perf:
        compact["total_ms"] = perf.get("total_ms")
    if "route_ms" in perf:
        compact["route_ms"] = perf.get("route_ms")
    stages = perf.get("stages")
    if isinstance(stages, list):
        compact["stage_count"] = len(stages)
        compact["stage_names"] = [str(item.get("stage") or "") for item in stages if isinstance(item, dict)]
        compact["stage_timings"] = [
            {
                "stage": str(item.get("stage") or ""),
                "timing_ms": item.get("timing_ms"),
                **({"model": str(item.get("model") or "")} if str(item.get("model") or "").strip() else {}),
                **({"tool_call_count": int(item.get("tool_call_count") or 0)} if "tool_call_count" in item else {}),
                **({"backend": str(item.get("backend") or "")} if str(item.get("backend") or "").strip() else {}),
                **({"matched": int(item.get("matched") or 0)} if "matched" in item else {}),
                **({"vector_enabled": bool(item.get("vector_enabled"))} if "vector_enabled" in item else {}),
            }
            for item in stages
            if isinstance(item, dict)
        ]
    return compact


def compact_retrieval(retrieval: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    if not isinstance(retrieval, dict):
        return compact
    for key in [
        "enabled",
        "backend",
        "strategy",
        "datasetId",
        "matched",
        "vectorEnabled",
        "collectionName",
        "fallbackReason",
        "error",
    ]:
        if key in retrieval:
            compact[key] = retrieval.get(key)
    return compact


def compact_trace(trace: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(trace, dict):
        return {}
    compact = dict(trace)
    perf = compact.get("perf")
    if isinstance(perf, dict):
        compact["perf"] = compact_perf(perf)
    retrieval = compact.get("retrieval")
    if isinstance(retrieval, dict):
        compact["retrieval"] = compact_retrieval(retrieval)
    return compact


def build_grade_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    lc_cfg = config_service.config.get("langchain", {}) or {}
    default_tools_enabled = parse_bool(lc_cfg.get("enable_tools_by_default"), True)
    return {
        "question": data.get("questionText") or "",
        "truth": data.get("standardAnswer") or "",
        "student": data.get("studentAnswer") or "",
        "max_score": parse_max_score(data.get("maxScore", 1), default=1.0),
        "model_alias": data.get("model"),
        "dataset_id": data.get("datasetId"),
        "level": data.get("level"),
        "question_id": data.get("questionId"),
        "question_type": data.get("questionType"),
        "recommendation_count": parse_int(data.get("recommendationCount"), 3),
        "retrieval_top_k": parse_int(data.get("retrievalTopK"), 5),
        "enable_recommendation": parse_bool(data.get("enable_recommendation", data.get("enableRecommendation", False)), False),
        "need_score": parse_bool(data.get("need_score", data.get("needScore", True)), True),
        "scoring_mode": str(data.get("scoring_mode", data.get("scoringMode", "auto")) or "auto").strip() or "auto",
        "enable_tools": parse_bool(data.get("enable_tools", data.get("enableTools", default_tools_enabled)), default_tools_enabled),
        "rubric_json": data.get("rubric_json", data.get("rubricJson")),
        "rubric_text": data.get("rubric_text", data.get("rubricText")),
    }


def resolve_model_details(alias: Any) -> Dict[str, str]:
    alias_text = str(alias or "").strip()
    cfg = config_service.get_model_config(alias_text) if alias_text else {}
    model_name = str((cfg or {}).get("model_name") or "").strip()
    return {
        "alias": alias_text or "default",
        "name": model_name or "",
    }


def resolve_grade_runtime_models() -> Dict[str, Dict[str, str]]:
    solver_alias = engine._get_model_alias("grade", "solver_model", "reviewer")
    supervisor_alias = engine._get_model_alias("grade", "supervisor_model", "grader")
    return {
        "solver": resolve_model_details(solver_alias),
        "supervisor": resolve_model_details(supervisor_alias),
    }


def force_backend_grade_models(payload: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(payload or {})
    sanitized["model_alias"] = None
    return sanitized


def make_progress_callback(job_id: str):
    def callback(event: Dict[str, Any]) -> None:
        job_store.update_stage(
            job_id,
            stage=str(event.get("stage") or "").strip(),
            label=str(event.get("label") or "").strip() or None,
            detail=str(event.get("detail") or "").strip(),
            status=str(event.get("status") or "").strip() or None,
            notes=[str(note or "").strip() for note in (event.get("notes") or []) if str(note or "").strip()],
            progress=event.get("progress"),
        )

    return callback


def run_grade_job(job_id: str, trace_id: str, payload: Dict[str, Any]) -> None:
    route_started_at = time.perf_counter()
    question_preview = str(payload.get("question") or "")[:30]
    runtime_models = resolve_grade_runtime_models()
    try:
        job_store.start(job_id)
        safe_print(
            f"[Grade][Async] Job {job_id} | Solver: {runtime_models['solver']['alias']} "
            f"({runtime_models['solver']['name'] or '-'}) | "
            f"Supervisor: {runtime_models['supervisor']['alias']} "
            f"({runtime_models['supervisor']['name'] or '-'}) | "
            f"Tools: {payload.get('enable_tools')} | Question: {question_preview}..."
        )
        result = engine.grade(
            question=payload["question"],
            truth=payload["truth"],
            student=payload["student"],
            max_score=payload["max_score"],
            model_alias=payload.get("model_alias"),
            enable_tools=payload.get("enable_tools"),
            dataset_id=payload.get("dataset_id"),
            level=payload.get("level"),
            question_id=payload.get("question_id"),
            question_type=payload.get("question_type"),
            recommendation_count=payload.get("recommendation_count"),
            retrieval_top_k=payload.get("retrieval_top_k"),
            enable_recommendation=payload.get("enable_recommendation"),
            trace_id=trace_id,
            need_score=payload.get("need_score"),
            scoring_mode=payload.get("scoring_mode"),
            rubric_override=payload.get("rubric_json"),
            rubric_text=payload.get("rubric_text"),
            progress_callback=make_progress_callback(job_id),
        )
        result.setdefault("methodUsed", engine.method_id)
        result.setdefault("similarQuestions", [])
        details = ensure_details(result)
        perf = details.get("perf") if isinstance(details.get("perf"), dict) else {}
        perf["route_ms"] = elapsed_ms(route_started_at)
        details["perf"] = perf
        details["trace_id"] = trace_id
        job_store.complete(job_id, result)
        log_trace(
            {
                "trace_id": trace_id,
                "job_id": job_id,
                "route": "/grade/submit",
                "status": "completed",
                "correct": result.get("correct"),
                "score": result.get("score"),
                "solver_model_alias": runtime_models["solver"]["alias"],
                "solver_model_name": runtime_models["solver"]["name"],
                "supervisor_model_alias": runtime_models["supervisor"]["alias"],
                "supervisor_model_name": runtime_models["supervisor"]["name"],
                "similar_count": len(result.get("similarQuestions") or []),
                "retrieval": result.get("retrieval"),
                "perf": perf,
            }
        )
    except Exception as exc:
        message = str(exc)
        safe_print(f"[Grade][Async] Job {job_id} failed: {message}")
        job_store.fail(job_id, message)
        log_trace(
            {
                "trace_id": trace_id,
                "job_id": job_id,
                "route": "/grade/submit",
                "status": "failed",
                "error": message,
                "route_ms": elapsed_ms(route_started_at),
            }
        )


ocr_service = OCRService("auto")


@app.route("/ocr", methods=["POST"])
def ocr():
    trace_id = request_trace_id()
    route_started_at = time.perf_counter()
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    try:
        ocr_started_at = time.perf_counter()
        text = ocr_service.recognize(file)
        engine_name = getattr(getattr(ocr_service, "strategy", None), "name", "ocr")
        perf = {
            "route_ms": elapsed_ms(route_started_at),
            "ocr_ms": elapsed_ms(ocr_started_at),
        }
        log_trace({"trace_id": trace_id, "route": "/ocr", "file_name": file.filename, "engine": engine_name, "perf": perf})
        return jsonify({"text": text, "traceId": trace_id, "engine": engine_name, "perf": perf})
    except Exception as exc:
        safe_print(f"OCR Error: {exc}")
        log_trace({"trace_id": trace_id, "route": "/ocr", "error": str(exc), "route_ms": elapsed_ms(route_started_at)})
        return jsonify({"error": str(exc), "traceId": trace_id}), 500


@app.route("/grade", methods=["POST"])
def grade():
    route_started_at = time.perf_counter()
    data = request.json or {}
    payload = force_backend_grade_models(build_grade_payload(data))
    trace_id = request_trace_id()
    question_preview = str(payload.get("question") or "")[:30]
    runtime_models = resolve_grade_runtime_models()

    safe_print(
        f"[Grade] LangChain Solver+Supervisor | Solver: {runtime_models['solver']['alias']} "
        f"({runtime_models['solver']['name'] or '-'}) | Supervisor: {runtime_models['supervisor']['alias']} "
        f"({runtime_models['supervisor']['name'] or '-'}) | Tools: {payload.get('enable_tools')}"
    )
    safe_print(f"[Grade] Processing question: {question_preview}...")
    log_trace(
        {
            "trace_id": trace_id,
            "route": "/grade",
            "method": engine.method_id,
            "tools_enabled": payload.get("enable_tools"),
            "solver_model_alias": runtime_models["solver"]["alias"],
            "solver_model_name": runtime_models["solver"]["name"],
            "supervisor_model_alias": runtime_models["supervisor"]["alias"],
            "supervisor_model_name": runtime_models["supervisor"]["name"],
            "question_preview": question_preview,
            "dataset_id": payload.get("dataset_id"),
            "level": payload.get("level"),
            "question_id": payload.get("question_id"),
            "question_type": payload.get("question_type"),
            "recommendation_count": payload.get("recommendation_count"),
            "retrieval_top_k": payload.get("retrieval_top_k"),
            "enable_recommendation": payload.get("enable_recommendation"),
            "need_score": payload.get("need_score"),
            "scoring_mode": payload.get("scoring_mode"),
        }
    )

    result = engine.grade(
        question=payload["question"],
        truth=payload["truth"],
        student=payload["student"],
        max_score=payload["max_score"],
        model_alias=payload.get("model_alias"),
        enable_tools=payload.get("enable_tools"),
        dataset_id=payload.get("dataset_id"),
        level=payload.get("level"),
        question_id=payload.get("question_id"),
        question_type=payload.get("question_type"),
        recommendation_count=payload.get("recommendation_count"),
        retrieval_top_k=payload.get("retrieval_top_k"),
        enable_recommendation=payload.get("enable_recommendation"),
        trace_id=trace_id,
        need_score=payload.get("need_score"),
        scoring_mode=payload.get("scoring_mode"),
        rubric_override=payload.get("rubric_json"),
        rubric_text=payload.get("rubric_text"),
    )
    result.setdefault("methodUsed", engine.method_id)
    result.setdefault("similarQuestions", [])
    details = ensure_details(result)
    perf = details.get("perf") if isinstance(details.get("perf"), dict) else {}
    perf["route_ms"] = elapsed_ms(route_started_at)
    details["perf"] = perf
    details["trace_id"] = trace_id
    log_trace(
        {
            "trace_id": trace_id,
            "route": "/grade",
            "status": "completed",
            "correct": result.get("correct"),
            "score": result.get("score"),
            "solver_model_alias": runtime_models["solver"]["alias"],
            "solver_model_name": runtime_models["solver"]["name"],
            "supervisor_model_alias": runtime_models["supervisor"]["alias"],
            "supervisor_model_name": runtime_models["supervisor"]["name"],
            "similar_count": len(result.get("similarQuestions") or []),
            "retrieval": result.get("retrieval"),
            "perf": perf,
        }
    )
    safe_print(
        f"[Grade] Finished. Trace: {trace_id} | total_ms={perf.get('total_ms')} "
        f"route_ms={perf.get('route_ms')} stage_count={len(perf.get('stages') or [])}"
    )
    return jsonify(result)


@app.route("/grade/submit", methods=["POST"])
def submit_grade_job():
    data = request.json or {}
    payload = force_backend_grade_models(build_grade_payload(data))
    trace_id = request_trace_id()
    job = job_store.create(trace_id)
    job_id = str(job.get("jobId") or "")
    runtime_models = resolve_grade_runtime_models()
    log_trace(
        {
            "trace_id": trace_id,
            "job_id": job_id,
            "route": "/grade/submit",
            "status": "accepted",
            "solver_model_alias": runtime_models["solver"]["alias"],
            "solver_model_name": runtime_models["solver"]["name"],
            "supervisor_model_alias": runtime_models["supervisor"]["alias"],
            "supervisor_model_name": runtime_models["supervisor"]["name"],
            "question_preview": str(payload.get("question") or "")[:30],
            "enable_recommendation": payload.get("enable_recommendation"),
            "need_score": payload.get("need_score"),
            "scoring_mode": payload.get("scoring_mode"),
        }
    )
    worker = threading.Thread(target=run_grade_job, args=(job_id, trace_id, payload), daemon=True)
    worker.start()
    return jsonify(
        {
            "jobId": job_id,
            "traceId": trace_id,
            "status": "accepted",
            "headline": job.get("headline"),
            "items": job.get("items") or [],
        }
    )


@app.route("/grade/jobs/<job_id>", methods=["GET"])
def get_grade_job(job_id: str):
    job = job_store.snapshot(job_id)
    if not job:
        return jsonify({"error": "Job not found", "jobId": job_id}), 404
    return jsonify(job)


class QuietRequestHandler(WSGIRequestHandler):
    QUIET_PATH_PREFIXES = ("/grade/jobs/",)
    QUIET_PATHS = set()

    def log_request(self, code="-", size="-"):
        path = str(getattr(self, "path", "") or "").split("?", 1)[0]
        if path in self.QUIET_PATHS or any(path.startswith(prefix) for prefix in self.QUIET_PATH_PREFIXES):
            return
        return super().log_request(code=code, size=size)


@app.route("/solve", methods=["POST"])
def solve():
    route_started_at = time.perf_counter()
    data = request.json or {}
    question = data.get("questionText")
    model_name = data.get("model")

    lc_cfg = config_service.config.get("langchain", {}) or {}
    default_tools_enabled = parse_bool(lc_cfg.get("enable_tools_by_default"), True)
    enable_tools = parse_bool(data.get("enable_tools", data.get("enableTools", default_tools_enabled)), default_tools_enabled)
    solve_mode = data.get("mode") or lc_cfg.get("solve_mode", "loop")
    max_rounds = parse_int(data.get("maxRounds"), parse_int((lc_cfg.get("solve", {}) or {}).get("loop_rounds", 2), 2))

    trace_id = request_trace_id()
    question_preview = (question or "")[:30]
    safe_print(
        f"[Solve] Generating answer for: {question_preview}... using {model_name or 'default'} | "
        f"Tools: {enable_tools} | Mode: {solve_mode}"
    )

    try:
        log_trace(
            {
                "trace_id": trace_id,
                "route": "/solve",
                "tools_enabled": enable_tools,
                "solve_mode": solve_mode,
                "solver_model": model_name or "default",
                "question_preview": question_preview,
            }
        )

        result = engine.solve(
            question=question or "",
            model_alias=model_name,
            enable_tools=enable_tools,
            mode=solve_mode,
            max_rounds=max_rounds,
            trace_id=trace_id,
        )
        details = ensure_details(result)
        perf = details.get("perf") if isinstance(details.get("perf"), dict) else {}
        perf["route_ms"] = elapsed_ms(route_started_at)
        details["perf"] = perf
        details["trace_id"] = trace_id
        log_trace(
            {
                "trace_id": trace_id,
                "route": "/solve",
                "status": "completed",
                "perf": perf,
            }
        )
        safe_print(
            f"[Solve] Generated. Trace: {trace_id} | total_ms={perf.get('total_ms')} "
            f"route_ms={perf.get('route_ms')} stage_count={len(perf.get('stages') or [])}"
        )
        return jsonify(result)
    except Exception as exc:
        safe_print(f"[Solve] Error: {exc}")
        log_trace({"trace_id": trace_id, "route": "/solve", "error": str(exc), "route_ms": elapsed_ms(route_started_at)})
        return jsonify({"error": str(exc), "traceId": trace_id}), 500


if __name__ == "__main__":
    safe_print("Python Agent Service running on port 5000")
    app.run(port=5000, debug=True, use_reloader=False, request_handler=QuietRequestHandler)
