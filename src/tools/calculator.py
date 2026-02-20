import math

def calculate(expression: str) -> str:
    """
    Evaluates a mathematical expression safely.
    Supports basic arithmetic (+, -, *, /, **, %) and math functions (sqrt, sin, cos, etc).
    """
    try:
        # Define safe environment
        safe_dict = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
        safe_dict.update({"abs": abs, "round": round, "min": min, "max": max})
        
        # Clean expression
        expression = expression.replace("^", "**")
        
        # Eval
        result = eval(expression, {"__builtins__": None}, safe_dict)
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"

# OpenAI Tool Definition
CALCULATOR_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": "Calculate the result of a mathematical expression. Use this whenever you need to verify a calculation.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The mathematical expression to evaluate (e.g., '123 * 45', 'sqrt(16)', '3.14 * 5**2')."
                }
            },
            "required": ["expression"]
        }
    }
}
