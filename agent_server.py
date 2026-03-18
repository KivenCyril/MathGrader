import json
import time
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from src.langchain_engine import LangChainMathEngine
from src.services.config_service import config_service
from src.services.ocr_service import OCRService

load_dotenv()

app = Flask(__name__)
engine = LangChainMathEngine(config_service.config)


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
    print("[Trace] " + json.dumps(trace, ensure_ascii=False))


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


@app.route('/models', methods=['GET'])
def list_models():
    models = list(config_service.config.get('models', {}).keys())
    return jsonify(models)


@app.route('/grading-methods', methods=['GET'])
def list_grading_methods():
    return jsonify(engine.list_methods())


ocr_service = OCRService("auto")


@app.route('/ocr', methods=['POST'])
def ocr():
    trace_id = request_trace_id()
    route_started_at = time.perf_counter()
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        ocr_started_at = time.perf_counter()
        text = ocr_service.recognize(file)
        perf = {
            "route_ms": elapsed_ms(route_started_at),
            "ocr_ms": elapsed_ms(ocr_started_at),
        }
        log_trace({"trace_id": trace_id, "route": "/ocr", "file_name": file.filename, "perf": perf})
        return jsonify({"text": text, "traceId": trace_id, "perf": perf})
    except Exception as e:
        print(f"OCR Error: {e}")
        log_trace({"trace_id": trace_id, "route": "/ocr", "error": str(e), "route_ms": elapsed_ms(route_started_at)})
        return jsonify({"error": str(e), "traceId": trace_id}), 500


@app.route('/grade', methods=['POST'])
def grade():
    route_started_at = time.perf_counter()
    data = request.json or {}

    question = data.get('questionText')
    truth = data.get('standardAnswer')
    student = data.get('studentAnswer')
    max_score = parse_max_score(data.get('maxScore', 1), default=1.0)
    model_name = data.get('model')
    dataset_id = data.get("datasetId")
    level = data.get("level")
    question_id = data.get("questionId")
    question_type = data.get("questionType")
    recommendation_count = parse_int(data.get("recommendationCount"), 3)
    retrieval_top_k = parse_int(data.get("retrievalTopK"), 5)

    lc_cfg = config_service.config.get("langchain", {}) or {}
    default_tools_enabled = parse_bool(lc_cfg.get("enable_tools_by_default"), True)
    enable_tools = parse_bool(data.get("enable_tools", data.get("enableTools", default_tools_enabled)), default_tools_enabled)

    trace_id = request_trace_id()
    question_preview = (question or "")[:30]
    print(f"[Grade] LangChain Solver+Supervisor | Model: {model_name or 'default'} | Tools: {enable_tools}")
    print(f"[Grade] Processing question: {question_preview}...")

    log_trace(
        {
            "trace_id": trace_id,
            "route": "/grade",
            "method": engine.method_id,
            "tools_enabled": enable_tools,
            "grader_model": model_name or "default",
            "question_preview": question_preview,
            "dataset_id": dataset_id,
            "level": level,
            "question_id": question_id,
            "question_type": question_type,
            "recommendation_count": recommendation_count,
            "retrieval_top_k": retrieval_top_k,
        }
    )

    result = engine.grade(
        question=question or "",
        truth=truth or "",
        student=student or "",
        max_score=max_score,
        model_alias=model_name,
        enable_tools=enable_tools,
        dataset_id=dataset_id,
        level=level,
        question_id=question_id,
        question_type=question_type,
        recommendation_count=recommendation_count,
        retrieval_top_k=retrieval_top_k,
        trace_id=trace_id,
    )

    result.setdefault("methodUsed", engine.method_id)
    result.setdefault("similarQuestions", [])
    details = ensure_details(result)
    perf = details.get("perf") if isinstance(details.get("perf"), dict) else {}
    perf["route_ms"] = elapsed_ms(route_started_at)
    details["perf"] = perf
    details["trace_id"] = trace_id
    if data.get("compareMethods"):
        result["comparison"] = {}

    log_trace(
        {
            "trace_id": trace_id,
            "route": "/grade",
            "status": "completed",
            "correct": result.get("correct"),
            "score": result.get("score"),
            "perf": perf,
        }
    )
    print(f"[Grade] Finished. Trace: {trace_id} | {perf}")
    return jsonify(result)


@app.route('/solve', methods=['POST'])
def solve():
    route_started_at = time.perf_counter()
    data = request.json or {}
    question = data.get('questionText')
    model_name = data.get('model')

    lc_cfg = config_service.config.get("langchain", {}) or {}
    default_tools_enabled = parse_bool(lc_cfg.get("enable_tools_by_default"), True)
    enable_tools = parse_bool(data.get("enable_tools", data.get("enableTools", default_tools_enabled)), default_tools_enabled)
    solve_mode = data.get("mode") or lc_cfg.get("solve_mode", "loop")
    max_rounds = parse_int(data.get("maxRounds"), parse_int((lc_cfg.get("solve", {}) or {}).get("loop_rounds", 2), 2))

    trace_id = request_trace_id()
    question_preview = (question or "")[:30]
    print(f"[Solve] Generating answer for: {question_preview}... using {model_name or 'default'} | Tools: {enable_tools} | Mode: {solve_mode}")

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
        print(f"[Solve] Generated. Trace: {trace_id} | {perf}")
        return jsonify(result)
    except Exception as e:
        print(f"[Solve] Error: {e}")
        log_trace({"trace_id": trace_id, "route": "/solve", "error": str(e), "route_ms": elapsed_ms(route_started_at)})
        return jsonify({"error": str(e), "traceId": trace_id}), 500


if __name__ == '__main__':
    print("Python Agent Service running on port 5000")
    app.run(port=5000, debug=True, use_reloader=False)
