import os
import sys
import json
from flask import Flask, jsonify, request
from src.llm_clients.base_client import LLMClient
from src.services.prompt_service import PromptLoader
from src.services.config_service import config_service
from src.services.grading_strategies.strategies import SinglePassStrategy, PeerReviewStrategy
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Initialize Clients based on settings.yaml
def get_client(role):
    model_alias = config_service.get_role_model(role)
    config = config_service.get_model_config(model_alias)
    return LLMClient(config)

client_main = get_client("grader")    # e.g. DeepSeek
client_reviewer = get_client("reviewer") # e.g. Qwen

prompt_loader = PromptLoader()

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
    
    if mode == 'review':
        strategy = PeerReviewStrategy(client_main, client_reviewer, prompt_loader)
    else:
        strategy = SinglePassStrategy(client_main, prompt_loader)

    result = strategy.grade(context)
    return jsonify(result)

if __name__ == '__main__':
    print("Python Agent Service running on port 5000")
    app.run(port=5000, debug=True)
