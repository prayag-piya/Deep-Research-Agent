# Deep Agent — AI-Powered Deep Research & Report Writer

An autonomous multi-agent research system built with **LangGraph** and **Ollama** that conducts in-depth web research on any topic and produces publication-quality IEEE-style technical reports.

---

## What Does This Project Do?

Deep Agent takes a research question from the user and autonomously:

1. **Asks clarifying questions** to understand the research intent
2. **Generates a task plan** — breaks the research into discrete, manageable tasks
3. **Conducts surface research** — quick web searches per task using Tavily
4. **Generates follow-up questions** — identifies knowledge gaps from initial research
5. **Performs deep parallel research** — dispatches multiple search queries concurrently
6. **Classifies and drafts** — organizes findings into sections and generates academic drafts
7. **Loops until all tasks are complete** — iterates through the task list automatically
8. **Writes a formatted report** using the Writer Agent:
   - Reads all accumulated sources, notes, and drafts
   - Generates IEEE-style section headings
   - Writes each section in parallel (500–2000 words each)
   - Quality-checks every section; if it fails, performs additional web research and rewrites
   - Assembles a final report with title, abstract, table of contents, numbered sections, and references
   - Saves the report as a Markdown file

---

## Architecture

```
┌─────────────────────────── Main Research Agent ───────────────────────────┐
│                                                                          │
│  User Query → Clarifying Questions → Task Plan → [For each task:]        │
│                                                                          │
│    Surface Research → Follow-up Questions → Deep Research (parallel)      │
│       → Classify → Draft (parallel) → Summarize → Next Task              │
│                                                                          │
│  [All tasks done] → Writer Agent                                         │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────── Writer Agent ─────────────────────────────────┐
│                                                                          │
│  Read Sources/Notes/Draft → Summarize → Generate Headings                │
│       → [For each heading (parallel):]                                   │
│                                                                          │
│         Generate Section → Quality Check ─┬─ Pass → Finalize             │
│                                           └─ Fail → Web Search           │
│                                                      → Rewrite           │
│                                                      → Finalize          │
│                                                                          │
│  Collect All Sections → Format with TOC + Abstract → Write to File       │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
deep_agent/
├── agent.py              # Main research agent — orchestrates the full pipeline
├── writer_agent.py       # Writer agent — generates the formatted IEEE report
├── states.py             # TypedDict state definitions for LangGraph
├── schema.py             # Pydantic models for structured LLM outputs
├── prompt.py             # All system prompts (task planning, research, writing, etc.)
├── tools.py              # Tavily search tools, file read/write utilities
├── configration.py       # Configuration model (model name, loop limits, etc.)
├── utils.py              # Helper utilities (message parsing, token management)
├── langgraph.json        # LangGraph deployment config
├── pyproject.toml        # Project metadata and dependencies
├── research/             # Auto-generated research data per thread
│   ├── sources_<id>/     # Web search results (JSON)
│   ├── notes_<id>/       # Research notes (JSON)
│   ├── draft_<id>/       # Section drafts (JSON)
│   ├── question_<id>/    # Follow-up questions (JSON)
│   ├── todo_<id>/        # Task lists (JSON)
│   └── report_<id>.md    # Final formatted report
└── .env                  # API keys (not committed)
```

---

## Prerequisites

- **Python** >= 3.12
- **Ollama** installed and running locally with a model pulled (default: `llama3.2:latest`)
- **Tavily API key** for web search
- **OpenRouter API key** (checked at startup; can be swapped for Ollama-only usage)

---

## Installation

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd deep_agent
```

### 2. Install dependencies with Poetry

```bash
pip install poetry
poetry install
```

### 3. Set up Ollama

```bash
# Install Ollama (https://ollama.com)
curl -fsSL https://ollama.com/install.sh | sh

# Pull the default model
ollama pull llama3.2:latest
```

### 4. Create a `.env` file

```bash
cp .env.example .env
```

Add your API keys:

```env
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxxxxx
OPENROUTER_API_KEY=sk-or-xxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Usage

### Run the full research + report pipeline

```bash
poetry run python agent.py
```

You will be prompted to:
1. Enter your research question
2. Enter a unique thread ID (used to organize research files)
3. Answer clarifying questions from the agent

The agent then researches autonomously and writes the final report to `research/report_<thread_id>.md`.

### Run only the writer agent (if you already have research data)

```bash
poetry run python writer_agent.py
```

This reads existing research files from `research/` and generates a formatted report.

---

## Configuration

Edit `configration.py` or pass values via LangGraph's `RunnableConfig`:

| Parameter               | Default                                    | Description                                   |
|-------------------------|--------------------------------------------|-----------------------------------------------|
| `query_generation_model`| `llama3.2:latest`                          | Model for query generation                    |
| `query_count`           | `3`                                        | Number of initial search queries              |
| `max_question`          | `3`                                        | Clarifying questions to ask the user          |
| `max_research_loop`     | `3`                                        | Max research iterations per topic             |
| `max_follow_up_question`| `3`                                        | Follow-up questions per research round        |

The LLM defaults to **Ollama** (`llama3.2:latest`). To use OpenRouter or OpenAI, uncomment the relevant lines in `agent.py` and `writer_agent.py`.

---

## Key Dependencies

| Package              | Purpose                              |
|----------------------|--------------------------------------|
| `langgraph`          | Agent orchestration and state graphs |
| `langchain`          | LLM abstractions and tool framework  |
| `langchain-ollama`   | Local LLM inference via Ollama       |
| `tavily-python`      | Web search API                       |
| `pydantic`           | Structured output schemas            |
| `tiktoken`           | Token counting and management        |
| `python-dotenv`      | Environment variable loading         |

---

## How the Report is Formatted

The writer agent produces a Markdown report with:

- **Title block** with date and author placeholders
- **Abstract** — auto-generated 150–250 word summary
- **Table of Contents** — linked section and subsection anchors
- **IEEE-numbered headings** — `## 1. Section`, `### 1.1. Subsection`
- **Horizontal rules** between major sections
- **Inline citations** converted to IEEE bracket format `[1]`, `[2]`
- **References section** at the end

Output is saved to `research/report_<thread_id>.md`.

---

## License

MIT — see [LICENSE](LICENSE) for details.
