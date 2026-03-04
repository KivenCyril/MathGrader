# MathGrader (LangChain + MCP)

MathGrader now uses `LangChain + MCP` as the main AI runtime.
The evaluation baseline you requested is preserved:

1. `Solve` flow generates an answer.
2. `Grade` flow judges that answer independently.

Java and Python are still split by responsibility:
- Java (`backend_java`) handles web pages, user flow, dataset APIs, and proxying.
- Python (`agent_server.py`) handles AI orchestration and tool execution.

---

## Core Features

- LangChain-based agent orchestration.
- MCP tool integration (multiple servers configurable).
- Local toolset:
  - `ocr_math` (PaddleOCR, optional Mathpix fallback)
  - `img2latex` (pix2tex)
  - `eval_expr` (SymPy expression evaluation)
  - `verify_step` (rule-based step validation)
  - `find_counterexample` (random counterexample search)
  - `calculate` (basic calculator)
- Grading with two roles:
  - `solver_model` solves the question independently.
  - `supervisor_model` makes the final correctness decision.
- Wrong-question recommendation with hybrid retrieval (vector + lexical).

---

## Agent Loop Logic

### Solve Loop (`/solve`)

`/solve` supports `single | loop`, default is `loop`.

```text
Draft = Solver(question)
for i in 1..N:
  Critique = Critic(question, Draft)
  if Critique.pass:
    break
  Draft = Solver.revise(question, Draft, Critique.feedback)
return Draft
```

Code entry points:
- `agent_server.py` -> `/solve`
- `src/langchain_engine/engine.py::solve`

### Grade Dual-Flow (`/grade`)

`/grade` remains a separate flow from `/solve`.

```text
Reference = GradeSolver(question)
Verdict = Supervisor(question, truth, student, Reference)
score = maxScore if Verdict.correct else 0
if incorrect:
  similarQuestions = HybridRetriever(question, dataset)
```

Code entry points:
- `agent_server.py` -> `/grade`
- `src/langchain_engine/engine.py::grade`

This is exactly the experimental setup you requested: one flow solves, one flow supervises grading.

---

## Wrong-Question Recommendation (Hybrid Retrieval)

Recommendations are triggered only when the result is incorrect.
Response includes:
- `similarQuestions`
- `retrieval` metadata

Strategy:
1. Lexical prefilter for speed.
2. Embedding rerank on candidate set for precision.
3. Final score uses:
   `final = (1 - blend) * vector + blend * lexical`

Implementation:
- `src/langchain_engine/retrieval.py`

---

## Configuration (`settings.yaml`)

Main sections are `mcp` and `langchain`.

```yaml
mcp:
  refresh_sec: 90
  servers:
    - name: "math"
      url: "http://127.0.0.1:8787/mcp"
      enabled: false
      name_prefix: "math"
      timeout_sec: 20
      headers: {}

langchain:
  method_id: "langchain_solver_supervisor"
  max_tool_rounds: 4
  enable_tools_by_default: true
  solve_mode: "loop"

  prompts:
    solve_system: "v2_lc_solve_system"
    solve_user: "v2_lc_solve_user"
    critic_system: "v2_lc_critic_system"
    critic_user: "v2_lc_critic_user"
    revise_system: "v2_lc_revise_system"
    revise_user: "v2_lc_revise_user"
    grade_solver_system: "v2_lc_grade_solver_system"
    grade_solver_user: "v2_lc_grade_solver_user"
    grade_supervisor_system: "v2_lc_grade_supervisor_system"
    grade_supervisor_user: "v2_lc_grade_supervisor_user"

  solve:
    solver_model: "qwen"
    critic_model: "deepseek"
    loop_rounds: 2
    tools: ["calculate", "ocr_math", "img2latex", "eval_expr", "verify_step", "find_counterexample", "mcp:*"]

  grade:
    solver_model: "qwen"
    supervisor_model: "deepseek"
    tools: ["calculate", "ocr_math", "img2latex", "eval_expr", "verify_step", "find_counterexample", "mcp:*"]

  recommendation:
    enabled: true
    data_root: "data/raw"
    apply_to_datasets: []
    top_k: 5
    recommendation_count: 3
    min_score: 0.05
    lexical_blend: 0.35
    vector_candidate_k: 80
    model_alias: "qwen"
    embedding_model: "text-embedding-v4"
    max_docs: 60000
```

---

## Prompt Directory

All LangChain prompt templates are in:
- `src/prompts/versions/`

Current templates:
- `v2_lc_solve_system.txt`
- `v2_lc_solve_user.txt`
- `v2_lc_critic_system.txt`
- `v2_lc_critic_user.txt`
- `v2_lc_revise_system.txt`
- `v2_lc_revise_user.txt`
- `v2_lc_grade_solver_system.txt`
- `v2_lc_grade_solver_user.txt`
- `v2_lc_grade_supervisor_system.txt`
- `v2_lc_grade_supervisor_user.txt`

---

## API Overview

- `GET /models`
- `GET /grading-methods`
- `POST /ocr`
- `POST /solve`
- `POST /grade`

`/solve` common payload fields:
- `questionText`
- `model` (optional)
- `enableTools` (optional)
- `mode` = `single | loop` (optional)
- `maxRounds` (optional)

`/grade` common payload fields:
- `questionText`
- `standardAnswer`
- `studentAnswer`
- `maxScore`
- `model` (optional)
- `enableTools` (optional)
- `datasetId` (for recommendation)
- `level` (recommendation filter)
- `questionId` (exclude current question)
- `recommendationCount`
- `retrievalTopK`

---

## Quick Start

### Python Agent

```bash
pip install -r requirements.txt
python agent_server.py
```

Default: `http://localhost:5000`

### Java Web Backend

```bash
cd backend_java
mvn spring-boot:run
```

Default: `http://localhost:8080`

---

## Evaluation

The evaluation script keeps the dual-flow baseline:
- call `/solve`
- send result to `/grade`

Script:
- `src/evaluation/run_eval.py`

---

## Current Project Layout

```text
agent_server.py
settings.yaml
settings.example.yaml
requirements.txt
src/
  langchain_engine/
    engine.py
    local_tools.py
    retrieval.py
  prompts/versions/
    v2_lc_*.txt
  llm_clients/
    base_client.py
  tools/
    calculator.py
    tool_hub.py
    mcp_tool_manager.py
  services/
    config_service.py
    ocr_service.py
    prompt_service.py
  evaluation/
    run_eval.py
backend_java/
```

---

## Notes

- If `langchain` is not installed, runtime falls back to OpenAI-compatible `LLMClient` calls.
- `pix2tex` and `Mathpix` are optional.
- Hybrid recommendation can still work in lexical fallback mode when vector embedding is unavailable.