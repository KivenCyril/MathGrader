import json
from pathlib import Path
from typing import List, Union
from src.evaluation.schema import MathProblem


def load_math23k(json_path: Union[str, Path]) -> List[MathProblem]:
    """
    从 Math23K 的 JSON 文件（多个对象首尾相接）读取数据。
    """
    json_path = Path(json_path)
    text = json_path.read_text(encoding="utf-8").strip()

    # 直接转换 {..}{..}{..} → [{..},{..},{..}]
    fixed_text = "[" + text.replace("}\n{", "},{") + "]"
    raw_items = json.loads(fixed_text)

    problems: List[MathProblem] = []
    for idx, item in enumerate(raw_items):
        problems.append(
            MathProblem(
                id=str(item.get("id") or idx),
                question=item.get("original_text") or item.get("text") or item.get("question"),
                equation=item.get("equation"),
                answer=str(item.get("ans") or item.get("answer")),
                grade=None,
                level=None,
                source="Math23K",
            )
        )

    return problems
