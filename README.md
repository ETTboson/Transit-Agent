<p align="center">
  <img src="assets/Mascot.png" alt="Transit-Agent mascot" width="128">
</p>

<h1 align="center">Transit-Agent: Urban Transportation Analysis with Dynamic Data</h1>

<p align="center">
  English · <a href="README_zh-CN.md">简体中文</a>
</p>

## Overview

![Transit-Agent overview](assets/Overview.png)

Transit-Agent combines transportation Context, executable domain tools, and a data dependency graph to answer urban transportation questions. The model selects methods and interprets results. The tools perform spatial and transport calculations, while the graph records their inputs and result dependencies. When data or parameters change, affected computations are updated and valid results are reused.

## How it works

- Transportation Context: the planning prompt includes nine traffic concepts, six functional roles, and rules for service schedules, transfers, travel-time objectives, peak periods, and network constraints. Concrete locations, times and constraints come from the question and supplied materials.
- Professional tools: eleven named tools cover GTFS ingestion, geocoding, spatial operations, network analysis, timetable-aware routing, OD analysis and accessibility. Model-generated Python remains available for additional computations.
- Data dependencies: professional-tool calls have stable task IDs and explicit file or upstream-result references. The graph checks input versions and parameters when a branch is requested, recalculates affected steps, and reuses unchanged results. The graph and tool outputs persist across continued sessions.

### Transportation Context

| Layer | Contents |
|---|---|
| Traffic concepts | Transport mode, location, network, route, service, demand, supply, operational performance, event |
| Functional roles | Origin, destination, analysis extent, time, travel mode, travel constraints |
| Professional rules | Service days and operating hours, walking and waiting during transfers, distance versus travel time, peak-period differences, directed network connectivity and capacity, departure schedules |

The Context is defined in [`agent/domain_context.py`](agent/domain_context.py) and included in each planning session.

### Executable tools

| Category | Tools | Input and calculation |
|---|---|---|
| Data acquisition | GTFS Reader | Read a local GTFS ZIP for a specified service date, applying service calendars and date exceptions. Produce a directed graph with scheduled departures and arrivals. |
| Spatial processing | Geocoding, Spatial Search, Buffer, Overlay | Match names or addresses in a supplied gazetteer, query nearby features, create metric buffers, and intersect layers. |
| Network analysis | Shortest Path, K-shortest Path, Network Analysis | Find paths using supplied distance or travel-time weights and inspect directed connectivity. |
| Travel analysis | Multimodal Routing, OD Analysis, Accessibility | Calculate arrival times with waiting and transfers, build OD travel-time results, and identify destinations within a time budget. |

Spatial tools use WGS84 GeoJSON and an explicit metric projected CRS for distance-based operations. Geocoding uses exact matches in the supplied point gazetteer and returns all ambiguous candidates. Spatial distance is geometric distance in that projection.

Routing uses an explicit directed graph. Static shortest-path tools compare edge weights; timetable-aware tools use departure times and transfer constraints. Walking links must be supplied. GTFS ingestion supports scheduled services, calendar exceptions and times after midnight; frequency-based or on-demand services and unsupported transfer variants return a specific input error. The tool parameters are defined in [`transit_network.py`](agent/tools/transit_network.py) and [`transit_spatial.py`](agent/tools/transit_spatial.py).

### Dependency-aware tool calls

The model can read a GTFS feed and pass its graph to a later routing task:

```json
{"动作":"专业工具","任务":"feed","工具":"GTFS Reader","参数":{"file":"feed.zip","service_date":"2026-11-11"},"理由":"读取指定服务日的班次"}
```

```json
{"动作":"专业工具","任务":"route_a","工具":"Multimodal Routing","参数":{"graph":{"结果":"feed","路径":["graph"]},"origin":"A","destination":"B","departure_seconds":28800,"transfer_min_seconds":120,"max_transfers":2},"理由":"按出发时刻计算可搭乘路径"}
```

Here `A` and `B` are stop IDs in the supplied feed. The second call records its dependency on `feed`. Additional source documents can be declared with `"资料依赖":["guide.json"]`. Changes to a declared input invalidate the affected branch. Dependency tracking covers registered professional tools and their declared inputs; arbitrary Python code is executed separately.

## Quickstart

Use Python 3.11. From the repository root, create a virtual environment:

```bash
python -m venv .venv
```

Activate it with `.venv\Scripts\Activate.ps1` in Windows PowerShell, or `source .venv/bin/activate` on Linux / macOS.

Install dependencies and run the offline dependency-update example:

```bash
python -m pip install -r requirements.txt
python -m agent.tool_demo
```

The example changes one of two synthetic transport networks, then shows which path calculation is recomputed and which is reused. It uses a temporary directory and requires no model API or credentials.

Check the planning data interface:

```bash
python -X utf8 -m agent.planning --data-dir benchmark/demo/data --question "Check whether these materials support a bus stop adjustment analysis" --prepare-only
```

The example uses synthetic materials to demonstrate the data interface. This check does not call a model API.

After preparing your own materials, start an analysis through the planning entry point:

```bash
python -X utf8 -m agent.planning --data-dir data/my_case --question "Analyse how the bus stop changes affect access, and produce a results table and map" --model deepseek-flash --temporary-key
```

You will be prompted for an API key. The program saves the results page, analysis code, and run records under `data/planning_runs/`.

Continue a session with updated materials:

```bash
python -X utf8 -m agent.planning --continue-from data/planning_runs/<previous-run> --data-dir data/my_case --question "Update the analysis using the revised materials" --temporary-key
```

Each new run keeps its own `tool_graph.json` and `tool_results/`. Tool feedback records computations and reuse. Previous results remain in their original run directory.

Run the offline software tests:

```bash
python -m unittest discover -s tests -v
```

## Repository structure

```text
agent/                  Model configuration and planning loop
  domain_context.py     Traffic concepts, roles and professional rules
  tool_graph.py         Tool dependencies, input versions and result reuse
  tool_demo.py          Offline example with changing synthetic inputs
  tools/                Transport, spatial and code-execution tools
benchmark/              Benchmark framework
  questions/            Questions
  references/           Reference workflows and answers
  demo/                 Synthetic data-interface example
evaluate/              Evaluation entry point
tests/                 Software regression tests
```

`agent/models.py` contains model adapters and credential-reading logic. `agent/runtime.py` contains request settings and the shared prompt. `agent/planning.py` connects the domain Context, tools, dependency graph and action loop.

## Evaluation

The repository separates benchmark questions, reference materials and evaluation code. The public `benchmark/questions/` and `benchmark/references/` directories currently contain placeholders. The included synthetic examples and software tests check implementation behavior.

Run a local scoring program against saved runs:

```bash
python -m evaluate.score --scorer /path/to/scorer.py --root /path/to/runs
```

The scoring program exposes `score(root, output)`, where `root` is the run directory and `output` is a new results subdirectory (default: `scores`). Keep its companion modules and reference materials in their existing local layout.
