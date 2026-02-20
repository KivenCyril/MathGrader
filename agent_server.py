import os
import sys
import json
from flask import Flask, jsonify, request
from src.llm_clients.base_client import LLMClient
from src.services.prompt_service import PromptLoader
from src.services.config_service import config_service
from src.services.grading_strategies.strategies import SinglePassStrategy, PeerReviewStrategy
from src.services.ocr_service import OCRService
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

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

client_main = get_client("grader")    # e.g. DeepSeek
client_reviewer = get_client("reviewer") # e.g. Qwen

prompt_loader = PromptLoader()

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

    # 策略选择 (可以通过参数控制)
    mode = data.get('mode', 'single') # single or review
    model_name = data.get('model') # specific grader model
    enable_tools = data.get('enable_tools', False) # Tool switch

    # Dynamic client selection
    grader_client = get_client_by_name(model_name) if model_name else client_main

    if mode == 'review':
        print(f"[Grade] Mode: Peer Review (Grader: {model_name or 'Default'} + Reviewer) | Tools: {enable_tools}")
        # For review, we keep the fixed reviewer for now, or allow passing 'reviewer_model' too
        strategy = PeerReviewStrategy(grader_client, client_reviewer, prompt_loader)
    else:
        print(f"[Grade] Mode: Single Pass (Grader: {model_name or 'Default'}) | Tools: {enable_tools}")
        strategy = SinglePassStrategy(grader_client, prompt_loader)

    print(f"[Grade] Processing question: {context['question'][:30]}...")
    result = strategy.grade(context, enable_tools=enable_tools)
    print("[Grade] Finished.")
    return jsonify(result)

@app.route('/solve', methods=['POST'])
def solve():
    data = request.json
    question = data.get('questionText')
    model_name = data.get('model')
    enable_tools = data.get('enable_tools', False)
    
    print(f"[Solve] Generating answer for: {question[:30]}... using {model_name or 'Default'} | Tools: {enable_tools}")
    
    # Use specified model or default reviewer
    if model_name:
        client_student = get_client_by_name(model_name)
    else:
        client_student = get_client("reviewer") 
    
    prompt = prompt_loader.load("v1_solver", question_text=question)
    
    try:
        from src.tools.calculator import CALCULATOR_TOOL_DEF, calculate
        tools = [CALCULATOR_TOOL_DEF] if enable_tools else None
        tool_map = {"calculate": calculate} if enable_tools else None

        resp = client_student.chat_completion(
            [{"role": "user", "content": prompt}], 
            tools=tools, 
            tool_map=tool_map
        )
        content = resp['choices'][0]['message']['content']
        print("[Solve] Generated.")
        return jsonify({"answer": content})
    except Exception as e:
        print(f"[Solve] Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Python Agent Service running on port 5000")
    app.run(port=5000, debug=True)
