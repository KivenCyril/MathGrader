from typing import Dict, Any

from src.agents.base_agent import Agent
from src.services.prompt_service import PromptLoader
from src.llm_clients.base_client import LLMClient
from src.services.grading_strategies.strategies import SinglePassStrategy
from src.tools.default_tools import build_default_registry


class GraderAgent(Agent):
    def __init__(self, client: LLMClient, prompt_loader: PromptLoader, prompt_version: str = "v1_basic_grader", tool_names=None):
        self.strategy = SinglePassStrategy(client, prompt_loader, prompt_version)
        self.tool_names = tool_names or []
        self.registry = build_default_registry()

    def act(self, state: Dict[str, Any], enable_tools: bool = False) -> Dict[str, Any]:
        context = {
            "question": state.get("question"),
            "truth": state.get("truth"),
            "student": state.get("student"),
            "max_score": state.get("max_score", 1),
        }
        if not context["question"] or context["truth"] is None or context["student"] is None:
            return {"correct": False, "score": 0, "reason": "Missing required grading fields"}
        if enable_tools and self.tool_names:
            tools = self.registry.get_tools(self.tool_names)
            tool_map = self.registry.get_tool_map(self.tool_names)
            return self.strategy.grade(context, enable_tools=True, tools=tools, tool_map=tool_map)
        return self.strategy.grade(context, enable_tools=enable_tools)
