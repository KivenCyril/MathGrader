from typing import Dict, Any, Optional

from src.agents.grader_agent import GraderAgent
from src.agents.reviewer_agent import ReviewerAgent


class GradingOrchestrator:
    def __init__(self, grader: GraderAgent, reviewer: Optional[ReviewerAgent] = None):
        self.grader = grader
        self.reviewer = reviewer

    def grade(self, context: Dict[str, Any], mode: str = "single", enable_tools: bool = False) -> Dict[str, Any]:
        if mode == "review":
            if not self.reviewer:
                return {"correct": False, "score": 0, "reason": "Reviewer agent is not configured"}

            result_a = self.grader.act(context, enable_tools=enable_tools)
            review_context = {
                **context,
                "prev_correct": result_a.get("correct"),
                "prev_score": result_a.get("score"),
                "prev_reason": result_a.get("reason"),
            }
            result_b = self.reviewer.act(review_context)
            return {
                "correct": result_b.get("final_correct", result_a.get("correct")),
                "score": result_b.get("final_score", result_a.get("score")),
                "reason": result_b.get("final_reason", result_a.get("reason")),
                "details": {
                    "grader_output": result_a,
                    "reviewer_output": result_b,
                },
            }

        return self.grader.act(context, enable_tools=enable_tools)
