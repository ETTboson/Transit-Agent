<p align="center">
  <img src="assets/Mascot.png" alt="Transit-Agent mascot" width="128">
</p>

<h1 align="center">Transit-Agent: An Autonomous Planning Agent for Urban Transportation Analysis</h1>

<p align="center">
  English · <a href="README_zh-CN.md">简体中文</a>
</p>

## Overview

![Transit-Agent overview](assets/Overview.png)

Transit-Agent turns transportation questions into executable analysis tasks. It identifies objects, roles, and task types, organizes tasks in a dependency graph, and combines domain tools with code to carry out analysis. Results and execution feedback guide whether to continue, revise the plan, or submit an answer together with the analysis steps and supporting evidence.

## Contributions

- Autonomous analysis planning: organize transportation analysis around objects, roles, and task types, manage computations and result dependencies through a task graph, and revise the analysis in response to feedback.
- Domain tools and code: combine reusable capabilities for sample comparisons, sustained change detection, and spatial analysis with model-generated code for task-specific computations.
- Task set and evaluation: use planning documents, vehicle observations, residential community profiles, and synthetic scenarios to construct analysis, scenario comparison, and update tasks. Evaluate answers, evidence, revisions, task completion, and resource costs.

## Quickstart

Use Python 3.11. From the repository root, create a virtual environment:

```bash
python -m venv .venv
```

Activate it with `.venv\Scripts\Activate.ps1` in Windows PowerShell, or `source .venv/bin/activate` on Linux / macOS.

Install dependencies and check the example materials:

```bash
python -m pip install -r requirements.txt
python -X utf8 -m agent.planning --data-dir benchmark/demo/data --question "Check whether these materials support a bus stop adjustment analysis" --prepare-only
```

The example uses synthetic materials to demonstrate the data interface. This check does not call a model API.

After preparing your own materials, start an analysis through the current bus planning entry point:

```bash
python -X utf8 -m agent.planning --data-dir data/my_case --question "Analyse how the bus stop changes affect access, and produce a results table and map" --model deepseek-flash --temporary-key
```

You will be prompted for an API key. The program saves the results page, analysis code, and run records under `data/planning_runs/`.

## Repository structure

```text
agent/                  Model configuration and planning loop
  tools/                Transit-Agent tools
benchmark/              Benchmark framework
  questions/            Questions
  references/           Reference workflows and answers
  demo/                 Synthetic data-interface example
evaluate/              Evaluation entry point
tests/                 Software regression tests
```

`agent/models.py` contains model adapters and credentials; `agent/runtime.py` contains planning request settings and the shared prompt. `agent/planning.py` defines actions and budgets.

Run a local scoring program against saved runs:

```bash
python -m evaluate.score --scorer /path/to/scorer.py --root /path/to/runs
```

The scoring program exposes `score(root, output)`, where `root` is the run directory and `output` is a new results subdirectory (default: `scores`). Keep its companion modules and reference materials in their existing local layout.
