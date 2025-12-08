from dataclasses import dataclass
from typing import Optional

@dataclass
class MathProblem:
    """统一后的数学应用题结构"""
    id: str
    question: str            # 题目文本
    equation: Optional[str]  # 标准方程（某些数据集可能有）
    answer: str              # 标准答案（先全部转成字符串）
    grade: Optional[int] = None   # 年级（如果有的话）
    level: Optional[int] = None   # 难度等级（CMM-Math 里会有）
    source: Optional[str] = None  # 数据来源：Math23K / Ape210K / CMM-Math 等
