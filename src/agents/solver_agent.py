from typing import Dict, Any

from src.agents.base_agent import Agent
from src.services.prompt_service import PromptLoader
from src.llm_clients.base_client import LLMClient
from src.tools.default_tools import build_default_registry


class SolverAgent(Agent):
    def __init__(self, client: LLMClient, prompt_loader: PromptLoader, prompt_version: str = "v1_solver", tool_names=None):
        self.client = client
        self.loader = prompt_loader
        self.version = prompt_version
        self.tool_names = tool_names or []
        self.registry = build_default_registry()

    def act(self, state: Dict[str, Any], enable_tools: bool = False) -> Dict[str, Any]:
        question = state.get("questionText") or state.get("question") or state.get("question_text")
        if not question:
            return {"error": "Missing question text"}

        prompt = self.loader.load(self.version, question_text=question)

        tools = self.registry.get_tools(self.tool_names) if enable_tools else None
        tool_map = self.registry.get_tool_map(self.tool_names) if enable_tools else None

        resp = self.client.chat_completion(
            [{"role": "user", "content": prompt}],
            tools=tools,
            tool_map=tool_map
        )
        content = resp["choices"][0]["message"]["content"]
        return {"answer": content}
