from src.tools.calculator import CALCULATOR_TOOL_DEF, calculate
from src.tools.tool_registry import ToolRegistry


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("calculate", CALCULATOR_TOOL_DEF, calculate)
    return registry
