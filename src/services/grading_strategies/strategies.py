import json
from src.llm_clients.base_client import LLMClient
from src.services.prompt_service import PromptLoader

class GradingStrategy:
    def grade(self, context: dict) -> dict:
        raise NotImplementedError

class SinglePassStrategy(GradingStrategy):
    """
    单次判卷策略：只调用一个模型
    """
    def __init__(self, client: LLMClient, prompt_loader: PromptLoader, prompt_version="v1_basic_grader"):
        self.client = client
        self.loader = prompt_loader
        self.version = prompt_version

    def grade(self, context: dict) -> dict:
        prompt = self.loader.load(self.version, **context)
        
        messages = [
            {"role": "user", "content": prompt}
        ]
        
        resp = self.client.chat_completion(messages)
        return self._parse(resp)

    def _parse(self, resp):
        try:
            content = resp['choices'][0]['message']['content']
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            return json.loads(content)
        except Exception as e:
            return {"correct": False, "score": 0, "reason": f"Parse Error: {str(e)}"}

class PeerReviewStrategy(GradingStrategy):
    """
    互评策略：
    1. Grader (Model A) 先判
    2. Reviewer (Model B) 复核
    """
    def __init__(self, client_a: LLMClient, client_b: LLMClient, prompt_loader: PromptLoader):
        self.grader = SinglePassStrategy(client_a, prompt_loader, "v1_basic_grader")
        self.reviewer_client = client_b
        self.loader = prompt_loader

    def grade(self, context: dict) -> dict:
        # Step 1: 初审
        result_a = self.grader.grade(context)
        
        # Step 2: 复核
        # 构造复核需要的上下文
        review_context = {
            **context,
            "prev_correct": result_a.get("correct"),
            "prev_score": result_a.get("score"),
            "prev_reason": result_a.get("reason")
        }
        
        prompt = self.loader.load("v1_reviewer", **review_context)
        resp = self.reviewer_client.chat_completion([{"role": "user", "content": prompt}])
        result_b = self.grader._parse(resp) # 复用解析逻辑
        
        # Step 3: 合并结果
        final_res = {
            "correct": result_b.get("final_correct", result_a.get("correct")),
            "score": result_b.get("final_score", result_a.get("score")),
            "reason": result_b.get("final_reason", result_a.get("reason")),
            "details": {
                "grader_output": result_a,
                "reviewer_output": result_b
            }
        }
        return final_res
