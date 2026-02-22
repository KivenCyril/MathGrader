import json
from typing import Dict, Any

from src.agents.base_agent import Agent
from src.services.prompt_service import PromptLoader
from src.llm_clients.base_client import LLMClient


class ReviewerAgent(Agent):
    def __init__(self, client: LLMClient, prompt_loader: PromptLoader, prompt_version: str = "v1_reviewer"):
        self.client = client
        self.loader = prompt_loader
        self.version = prompt_version

    def act(self, state: Dict[str, Any], enable_tools: bool = False) -> Dict[str, Any]:
        prompt = self.loader.load(self.version, **state)
        resp = self.client.chat_completion([{"role": "user", "content": prompt}])
        return self._parse(resp)

    def _parse(self, resp):
        try:
            content = resp["choices"][0]["message"]["content"]
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                content = content[start:end + 1]

            return json.loads(content)
        except Exception as e:
            return {"agree": False, "final_correct": False, "final_score": 0, "final_reason": f"Parse Error: {str(e)}"}
