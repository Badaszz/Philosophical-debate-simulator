# Philosophical Debate Simulator

A lightweight framework for generating and running multi-turn philosophical debates between synthetic "philosopher" agents. The project combines LLM-driven persona generation with external retrieval (Tavily search + Wikipedia enrichment) and a stateful graph orchestration using LangGraph.

## Overview
- Generate two opposing philosopher profiles for a given topic using an LLM.
- Retrieve relevant sources for each philosopher using Tavily, then enrich those sources with summaries from Wikipedia.
- Run a multi-turn (default 5-turn) debate where each philosopher responds to the previous philosopher's question.
- Produce a readable, formatted dialogue as output.

## Key Features
- Modular codebase (graphs, retrieval, schemas).
- Uses `langchain-groq` for LLM calls (plain invoke + JSON parsing to avoid tool-call errors).
- Retrieves web search results via Tavily and enriches with Wikipedia summaries.
- Runs debate flow in a LangGraph state graph with configurable turns.

## Repo Structure
- `main.py` — Entrypoint that wires imports and lets you run the graph locally.
- `langgraph.json` — LangGraph dev config.
- `src/philo_agent/schemas/philosopher.py` — Pydantic models and TypedDict state schema.
- `src/philo_agent/graphs/create_philosophers.py` — Node that generates philosopher profiles.
- `src/philo_agent/graphs/main_graph.py` — Compiled LangGraph pipeline (retrieval, enrichment, debate loop, formatting).
- `src/philo_agent/retrieval/retrieve_tavily.py` — Tavily client wrapper and retrieval map.
- `src/philo_agent/retrieval/wikipedia.py` — (helper) fetch and enrich Wikipedia summaries.
- `notebook.ipynb` — Experimental notebook used during development.

## Requirements
- Python >= 3.11 (project uses 3.13 in config).
- Virtual environment recommended.
- This project uses the `uv` package manager. Add packages with `uv add`, create the lockfile with `uv lock`, and install from the lockfile using your preferred `uv` command (for example, `uv sync`). Consult your `uv` documentation if your environment requires a different install command.


## Environment
- Create a `.env` file with required credentials (example):

```
TAVILY_API_KEY=your_tavily_api_key
OPENAI_API_KEY=your_openai_api_key_or_equivalent
```

## Run Locally (LangGraph dev)
1. Activate your virtualenv.
2. (If necessary) ensure `src` is on the Python path — `main.py` already adds it at runtime.
3. Start LangGraph dev UI:

```bash
langgraph dev
```

Or run the script directly to test a single invocation:

```bash
python main.py
```

## Notes & Troubleshooting
- If you see import errors for `philo_agent`, ensure `python_path` in `langgraph.json` points to the project root or `src`, and `main.py` prepends `src` to `sys.path`.
- If the LLM returns non-JSON output, the code attempts to extract the first JSON object from the response; prompts explicitly request JSON-only to reduce parsing errors.
- Ensure `TAVILY_API_KEY` is set and `tavily-python` package is installed. If the LangChain Tavily wrapper is unavailable, the code uses the Tavily client directly.

## Next steps (ideas)
- Add unit tests for parsing and retrieval modules.
- Add logging and retry/backoff on external calls (Tavily, Wikipedia, LLM).
- Provide a CLI wrapper for running debates from the command line.

---
Generated and organized from the project notebook and source files.

