import json
import uuid
from flask import Flask, jsonify, request
from src.llm_clients.base_client import LLMClient
from src.services.prompt_service import PromptLoader
from src.services.config_service import config_service
from src.services.ocr_service import OCRService
from src.agents.solver_agent import SolverAgent
from src.agents.grader_agent import GraderAgent
from src.agents.reviewer_agent import ReviewerAgent
from src.orchestrators.grading_orchestrator import GradingOrchestrator
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)


def normalize_answer(value):
    if value is None:
        return ""
    s = str(value).strip()
    # Normalize common formatting differences.
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("，", ",").replace("。", ".")
    return "".join(s.split()).lower()


def parse_max_score(value, default=1.0):
    try:
        return float(value)
    except Exception:
        return float(default)

# Initialize Clients based on settings.yaml
def get_client(role):
    # Old logic: by role
    model_alias = config_service.get_role_model(role)
    config = config_service.get_model_config(model_alias)
    return LLMClient(config)

def get_client_by_name(model_name):
    # New logic: by specific model name (e.g. "qwen", "deepseek")
    # If name not found, fallback to role default or error
    try:
        config = config_service.get_model_config(model_name)
        return LLMClient(config)
    except:
        print(f"Model {model_name} not found, falling back to grader role")
        return get_client("grader")

prompt_loader = PromptLoader()

def build_agents_from_config():
    cfg = config_service.config or {}
    agents_cfg = cfg.get("agents", {})

    solver_cfg = agents_cfg.get("solver", {})
    grader_cfg = agents_cfg.get("grader", {})
    reviewer_cfg = agents_cfg.get("reviewer", {})

    solver_model = solver_cfg.get("model") or config_service.get_role_model("reviewer")
    grader_model = grader_cfg.get("model") or config_service.get_role_model("grader")
    reviewer_model = reviewer_cfg.get("model") or config_service.get_role_model("reviewer")

    solver_prompt = solver_cfg.get("prompt", "v1_solver")
    grader_prompt = grader_cfg.get("prompt", "v1_basic_grader")
    reviewer_prompt = reviewer_cfg.get("prompt", "v1_reviewer")

    solver_tools = solver_cfg.get("tools", ["calculate"])
    grader_tools = grader_cfg.get("tools", ["calculate"])

    solver_agent = SolverAgent(get_client_by_name(solver_model), prompt_loader, solver_prompt, tool_names=solver_tools)
    grader_agent = GraderAgent(get_client_by_name(grader_model), prompt_loader, grader_prompt, tool_names=grader_tools)
    reviewer_agent = ReviewerAgent(get_client_by_name(reviewer_model), prompt_loader, reviewer_prompt)

    orchestrator = GradingOrchestrator(grader_agent, reviewer_agent)
    return solver_agent, grader_agent, reviewer_agent, orchestrator

solver_agent, grader_agent, reviewer_agent, grading_orchestrator = build_agents_from_config()

def log_trace(trace: dict):
    enabled = config_service.config.get("trace", {}).get("enabled", True)
    if not enabled:
        return
    print("[Trace] " + json.dumps(trace, ensure_ascii=False))

@app.route('/models', methods=['GET'])
def list_models():
    # Return list of available models from config
    # Assuming config_service has a way to list keys, or we parse settings.yaml structure
    # Since config_service.config is the dict loaded from yaml:
    models = list(config_service.config.get('models', {}).keys())
    return jsonify(models)

# Initialize OCR Service (Auto-detects EasyOCR or falls back to Mock)
ocr_service = OCRService("auto")

@app.route('/ocr', methods=['POST'])
def ocr():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    try:
        # Use OCR Service to recognize text
        text = ocr_service.recognize(file)
        return jsonify({"text": text})
    except Exception as e:
        print(f"OCR Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/grade', methods=['POST'])
def grade():
    # Reload config on each request? Or just restart server.
    # For now, static init.
    
    data = request.json
    
    # 构造标准上下文
    context = {
        "question": data.get('questionText'),
        "truth": data.get('standardAnswer'),
        "student": data.get('studentAnswer'),
        "max_score": data.get('maxScore', 1)
    }
    max_score_value = parse_max_score(context["max_score"], default=1.0)

    # Deterministic fast-path: exact normalized match should always be correct.
    if normalize_answer(context["truth"]) and normalize_answer(context["truth"]) == normalize_answer(context["student"]):
        return jsonify({
            "correct": True,
            "score": max_score_value,
            "reason": "Exact answer match."
        })

    # 策略选择 (可以通过参数控制)
    mode = data.get('mode', 'single') # single or review
    model_name = data.get('model') # specific grader model
    enable_tools = data.get('enable_tools', False) # Tool switch

    # Dynamic client selection
    grader_client = get_client_by_name(model_name) if model_name else None

    trace_id = uuid.uuid4().hex[:12]
    if mode == 'review':
        print(f"[Grade] Mode: Peer Review (Grader: {model_name or 'Default'} + Reviewer) | Tools: {enable_tools}")
    else:
        print(f"[Grade] Mode: Single Pass (Grader: {model_name or 'Default'}) | Tools: {enable_tools}")

    question_preview = (context.get("question") or "")[:30]
    print(f"[Grade] Processing question: {question_preview}...")

    if model_name:
        grader = GraderAgent(grader_client, prompt_loader, tool_names=["calculate"])
        orchestrator = GradingOrchestrator(grader, reviewer_agent)
    else:
        orchestrator = grading_orchestrator

    log_trace({
        "trace_id": trace_id,
        "route": "/grade",
        "mode": mode,
        "tools_enabled": enable_tools,
        "grader_model": model_name or config_service.get_role_model("grader"),
        "reviewer_model": config_service.get_role_model("reviewer"),
        "question_preview": (context.get("question") or "")[:30]
    })

    result = orchestrator.grade(context, mode=mode, enable_tools=enable_tools)

    print("[Grade] Finished.")
    return jsonify(result)

@app.route('/solve', methods=['POST'])
def solve():
    data = request.json
    question = data.get('questionText')
    model_name = data.get('model')
    enable_tools = data.get('enable_tools', False)
    
    trace_id = uuid.uuid4().hex[:12]
    question_preview = (question or "")[:30]
    print(f"[Solve] Generating answer for: {question_preview}... using {model_name or 'Default'} | Tools: {enable_tools}")
    
    try:
        # Use specified model or default reviewer
        if model_name:
            client_student = get_client_by_name(model_name)
            agent = SolverAgent(client_student, prompt_loader, tool_names=["calculate"])
        else:
            agent = solver_agent

        log_trace({
            "trace_id": trace_id,
            "route": "/solve",
            "tools_enabled": enable_tools,
            "solver_model": model_name or config_service.get_role_model("reviewer"),
            "question_preview": (question or "")[:30]
        })

        result = agent.act({"questionText": question}, enable_tools=enable_tools)
        print("[Solve] Generated.")
        return jsonify(result)
    except Exception as e:
        print(f"[Solve] Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Python Agent Service running on port 5000")
    app.run(port=5000, debug=True)
