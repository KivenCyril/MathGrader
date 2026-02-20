import argparse
import json
import requests
import time
import os
import csv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

API_BASE = "http://localhost:5000"

def load_dataset(path):
    try:
        # Try standard JSON load first
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        # If failed, try to handle concatenated JSON objects (like math23k format)
        print("Warning: Standard JSON load failed, trying concatenated JSON fix...")
        data = []
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            decoder = json.JSONDecoder()
            idx = 0
            while idx < len(content):
                try:
                    # Skip whitespace
                    while idx < len(content) and content[idx].isspace():
                        idx += 1
                    if idx >= len(content):
                        break
                        
                    obj, end_idx = decoder.raw_decode(content, idx=idx)
                    data.append(obj)
                    idx = end_idx
                except json.JSONDecodeError:
                    # Try to skip bad chars and continue
                    idx += 1
        return data

def normalize_question(q):
    """
    Normalize dataset fields to 'text' and 'truth'
    """
    # math23k format
    if "original_text" in q and "ans" in q:
        q["text"] = q["original_text"]
        q["truth"] = q["ans"]
    # ape210k format (often uses 'original_text' and 'ans' too, or similar)
    # primary_math.json format (uses 'text' and 'truth' or 'answer')
    
    # Fallback if text is missing but 'question' exists
    if "text" not in q and "question" in q:
        q["text"] = q["question"]
    
    # Fallback if truth is missing but 'answer' exists
    if "truth" not in q and "answer" in q:
        q["truth"] = q["answer"]
        
    return q

def run_single_case(q, solver_model, grader_model, enable_tools):
    """
    Run Solve -> Grade pipeline for a single question
    """
    q = normalize_question(q)
    
    start_time = time.time()
    result = {
        "id": q.get("id"),
        "question": q.get("text"),
        "truth": q.get("truth"),
        "solver_model": solver_model,
        "grader_model": grader_model,
        "tools_enabled": enable_tools,
        "student_answer": "",
        "score": 0,
        "is_correct": False,
        "latency": 0,
        "error": ""
    }

    try:
        # Step 1: Solve
        solve_payload = {
            "questionText": q.get("text"),
            "model": solver_model,
            "enable_tools": enable_tools
        }
        resp_solve = requests.post(f"{API_BASE}/solve", json=solve_payload, timeout=120)
        if resp_solve.status_code != 200:
            raise Exception(f"Solve API Error: {resp_solve.text}")
        
        student_ans = resp_solve.json().get("answer", "")
        result["student_answer"] = student_ans

        # Step 2: Grade
        grade_payload = {
            "questionText": q.get("text"),
            "standardAnswer": q.get("truth"),
            "studentAnswer": student_ans,
            "maxScore": q.get("maxScore", 1),
            "mode": "review", # Always use peer review for robust eval
            "model": grader_model,
            "enable_tools": enable_tools
        }
        resp_grade = requests.post(f"{API_BASE}/grade", json=grade_payload, timeout=120)

        if resp_grade.status_code != 200:
            raise Exception(f"Grade API Error: {resp_grade.text}")
        
        grade_data = resp_grade.json()
        result["score"] = grade_data.get("score", 0)
        result["is_correct"] = grade_data.get("correct", False)
        result["reason"] = grade_data.get("reason", "")

    except Exception as e:
        result["error"] = str(e)
        print(f"Error processing {q.get('id')}: {e}")

    result["latency"] = round(time.time() - start_time, 2)
    return result

def main():
    parser = argparse.ArgumentParser(description="Run evaluation benchmark")
    parser.add_argument("--data", type=str, default="data/primary_math.json", help="Path to dataset JSON")
    parser.add_argument("--solver", type=str, default="qwen", help="Model to solve questions")
    parser.add_argument("--grader", type=str, default="deepseek", help="Model to grade answers")
    parser.add_argument("--limit", type=int, default=10, help="Max questions to run")
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers")
    parser.add_argument("--tools", action="store_true", help="Enable calculator tool")
    
    args = parser.parse_args()

    # Verify data file
    if not os.path.exists(args.data):
        # Try relative to project root
        root_data = os.path.join(os.getcwd(), args.data)
        if os.path.exists(root_data):
            args.data = root_data
        else:
            print(f"Dataset not found: {args.data}")
            return

    print(f"🚀 Starting Evaluation...")
    print(f"Dataset: {args.data}")
    print(f"Solver: {args.solver} | Grader: {args.grader}")
    
    questions = load_dataset(args.data)
    if args.limit > 0:
        questions = questions[:args.limit]
    
    print(f"Total Questions: {len(questions)}")

    results = []
    
    # Run loop
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_single_case, q, args.solver, args.grader, args.tools) for q in questions]
        for i, future in enumerate(futures):
            res = future.result()
            results.append(res)
            print(f"[{i+1}/{len(questions)}] {res['id']} - Correct: {res['is_correct']} ({res['latency']}s)")
    
    # Save results
    os.makedirs("results", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tool_suffix = "_tools" if args.tools else ""
    csv_path = f"results/eval_{timestamp}{tool_suffix}.csv"
    
    fieldnames = ["id", "question", "truth", "solver_model", "grader_model", "tools_enabled", "student_answer", "score", "is_correct", "latency", "error", "reason"]
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # Calculate stats
    correct_count = sum(1 for r in results if r["is_correct"])
    accuracy = (correct_count / len(results)) * 100 if results else 0
    avg_latency = sum(r["latency"] for r in results) / len(results) if results else 0

    print("\n" + "="*40)
    print(f"📊 Evaluation Complete")
    print(f"Total: {len(results)}")
    print(f"Correct: {correct_count}")
    print(f"Accuracy: {accuracy:.2f}%")
    print(f"Avg Latency: {avg_latency:.2f}s")
    print(f"Saved to: {csv_path}")
    print("="*40)

if __name__ == "__main__":
    main()
