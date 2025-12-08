from pathlib import Path

from src.datasets.math23k import load_math23k


def main():
    data_path = Path("data/raw/math23k/math23k_test.json")
    problems = load_math23k(data_path)

    print("题目总数：", len(problems))
    print("-" * 40)
    for p in problems[:5]:  # 打印前 5 条看效果
        print(f"ID: {p.id}")
        print("题目：", p.question)
        print("标准答案：", p.answer)
        print("方程：", p.equation)
        print("-" * 40)


if __name__ == "__main__":
    main()
