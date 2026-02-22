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
- `app.py` — Entrypoint that exposes the agent as a fastapi endpoint.
- `streamlit_app.py` — Frontend for the project, calls the fastapi backend.
- - `Dockerfile` — docker file to build the docker image that runs the project.
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

## Examples

### Absurdism debate (formatted)

Below is an example formatted debate between two philosopher personas (Albert Camus and Thomas Aquinas) on the theme of Absurdism. The example was adapted from `example.txt` for readability.

---

#### Albert Camus

The absurd is not a mere philosophical abstraction but the lived reality of a world that offers no ultimate meaning, yet insists upon our search for it. To begin a debate on absurdism is to acknowledge that the human condition is defined by this tension: the yearning for order against the indifferent universe. Critics of existentialism often claim that it devolves into nihilism or moral relativism, but that is a misreading. Existentialism, and absurdism in particular, does not surrender to despair; it invites us to revolt against the absurd by creating our own values through conscious choice. The opponent’s suggestion to merely "begin" the debate overlooks the fact that the absurd is already present in every act of living. To ignore it is to live in denial, to accept it is to confront the very core of our freedom. Therefore, the debate must start with the recognition that the absurd is not a theoretical construct but a lived fact that demands a response of defiance and authenticity.

> I challenge the opponent’s reasoning by asking: if the absurd is indeed a universal condition, why do some philosophers dismiss it as a mere rhetorical flourish? Their dismissal betrays a failure to confront the very reality that compels us to question the legitimacy of all our institutions and beliefs. The absurd is not a convenient excuse for moral laxity; it is the crucible in which genuine moral courage is forged.

> **Question:** If we accept that the absurd is unavoidable, how can we justify the imposition of external moral codes that claim to provide meaning, without becoming complicit in the very absurdity we seek to transcend?

---

#### Thomas Aquinas

The notion that life is inherently absurd, that existence lacks any objective meaning, is a position that undermines the very foundations of human reason and the natural order. In the Scholastic tradition, we hold that all beings are created by a rational God, and that nature itself is a manifestation of divine wisdom. As I have argued in the Summa Theologiae, the existence of a first cause—God—provides the ultimate grounding for all being. If we deny this, we fall into a vicious circle: we cannot explain why there is a world at all, nor why human beings possess the capacity for rational thought and moral discernment. Absurdism, by asserting that life is devoid of meaning, effectively erases the possibility of objective truth and moral law. It also contradicts the Aristotelian principle of teleology, which holds that every natural thing has a purpose or end (telos). To claim that existence is absurd is to deny that purpose, thereby negating the very possibility of human flourishing (eudaimonia) and the pursuit of virtue.

> Moreover, the method of Scholasticism—deduction from first principles, rigorous logical analysis, and the synthesis of faith and reason—provides a robust framework for addressing existential questions. It does not rely on subjective whims but on the intelligibility of the cosmos as a rational creation. Therefore, absurdism is not only philosophically untenable but also epistemologically dangerous, as it invites moral relativism and existential despair.

> **Question:** If we accept that all beings are created by a rational God, how can we reconcile the existence of suffering and apparent moral evil with the notion of a benevolent, all-powerful creator?

---

*(Full formatted debate appended to `example.txt` in repository.)*

