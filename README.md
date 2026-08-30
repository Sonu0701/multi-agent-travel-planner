# Multi-Agent Travel Planner

An AI-powered travel planning system built with **LangGraph**, featuring a supervisor-routed team of specialist agents, input guardrails, human-in-the-loop approval, and resilient integrations with real-world travel data via **MCP (Model Context Protocol)** servers.

Instead of one monolithic AI call, the system breaks travel planning into discrete, coordinated steps — a supervisor agent decides which specialists are needed (flights, hotels, weather, budget), each specialist gathers real data, and a human reviews the draft itinerary before it's finalized.

---

## Architecture

```
User Query
    │
    ▼
┌─────────────────────┐
│   Input Guardrail    │  → Validates relevance, safety, and policy.
│  (Supervisor Agent)  │     Blocks off-topic/harmful requests immediately.
└─────────┬────────────┘
          │ (allowed)
          ▼
┌─────────────────────┐
│   Supervisor Agent    │  → Reads the request, extracts trip constraints,
│  (dynamic routing)   │     and decides which specialist agents to run.
└─────────┬────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│           Specialist Agents (as needed)        │
│  ✈️ Flight Agent   🏨 Hotel Agent               │
│  🌦️ Weather Agent  💰 Budget Agent              │
└─────────────────────┬───────────────────────┘
                       ▼
              ┌─────────────────┐
              │ Itinerary Agent   │  → Synthesizes all specialist output
              └────────┬──────────┘     into a structured draft plan.
                       ▼
              ┌─────────────────┐
              │  Human Approval   │  → Pauses execution (LangGraph interrupt),
              │   (interrupt)     │     waits for user approve/reject + feedback.
              └────────┬──────────┘
                       │
        ┌──────────────┼───────────────┐
        │ approved                     │ rejected (feedback)
        ▼                              ▼
┌─────────────────┐           loops back to Itinerary Agent
│ Final Response    │           (up to MAX_REVISIONS times)
└─────────────────┘
```

**Shared state** (`TravelState`) flows through every node — user query, trip constraints, each specialist's results, approval status, and revision count are all tracked in a single typed state object.

---

## Key Features

- **Dynamic agent routing** — the supervisor decides which specialists a request actually needs (e.g. a pure hotel question skips flight/weather/budget agents entirely) instead of always running a fixed pipeline.
- **Input guardrails** — an LLM-based validation step blocks off-topic, unsafe, or invalid requests *before* any specialist agents or paid API calls run, and short-circuits the graph cleanly (no wasted work downstream).
- **Human-in-the-loop approval** — drafts pause for human review via LangGraph's `interrupt()`. Rejecting with feedback loops back into the Itinerary Agent, which explicitly incorporates that feedback into the next draft — not just a cosmetic rewrite.
- **Revision cap** — a `MAX_REVISIONS` limit prevents runaway revision loops (and runaway LLM cost) if a user rejects indefinitely.
- **MCP tool integrations** — real data instead of hallucinated answers:
  - **Tavily** (hotel/general search) via streamable HTTP
  - **AviationStack** (airports, airlines) via a custom stdio MCP server
  - **OpenWeather** (current conditions + forecast) via a custom stdio MCP server
- **Resilient tool calls** — MCP failures (timeouts, bad API keys, malformed responses) degrade gracefully to a fallback message instead of crashing the entire graph run.
- **Clean data pipelines** — raw JSON tool responses are parsed and reformatted into concise text before being fed into LLM prompts, reducing token usage and prompt noise.
- **Durable state via Postgres** — LangGraph checkpoints (including in-progress interrupts) are persisted to Postgres using a connection pool (`psycopg_pool.ConnectionPool`), supporting safe concurrent access and automatic reconnection.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) |
| LLM | Groq (`langchain-groq`) |
| Tool protocol | MCP via `langchain-mcp-adapters` |
| Search | Tavily |
| Flight data | AviationStack (custom MCP server) |
| Weather data | OpenWeather (custom MCP server) |
| Persistence | PostgreSQL (`langgraph-checkpoint-postgres`, `psycopg_pool`) |
| Frontend | Streamlit |

---

## Project Structure

```
flightAIagent/
├── agents.py                      # All agent node definitions (supervisor, flight, hotel, weather, budget, itinerary, approval, final)
├── graph.py                       # LangGraph StateGraph construction, routing logic, Postgres checkpointer setup
├── state.py                       # TravelState TypedDict (shared state schema)
├── config.py                      # Environment variable loading, LLM client setup
├── mcp_client.py                  # MultiServerMCPClient configuration for Tavily / AviationStack / Weather
├── custom_weather_mcp_server.py   # Custom MCP server wrapping the OpenWeather API
├── frontend1.py                   # Streamlit UI (chat input, draft display, approval controls)
├── aviationstack-mcp/             # Custom MCP server package wrapping the AviationStack API
├── requirements.txt
└── .env                           # API keys & DB connection string (not committed)
```

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Sonu0701/multi-agent-travel-planner.git
cd multi-agent-travel-planner
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

The `aviationstack-mcp` server has its own dependencies — install those too:

```bash
cd aviationstack-mcp
pip install -e .
cd ..
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b

TAVILY_API_KEY=your_tavily_api_key
AVIATION_STACK_API_KEY=your_aviationstack_api_key
OPENWEATHER_API_KEY=your_openweather_api_key

DATABASE_URL=postgresql://user:password@host:5432/dbname
```

> `DATABASE_URL` is optional — if omitted, the graph runs without persistent checkpointing (no resume-after-restart support, and human-in-the-loop state won't survive a server restart).

### 4. Run the app

```bash
streamlit run frontend1.py
```

Open the local URL Streamlit prints (typically `http://localhost:8501`).

---

## How It Works

1. **Enter a travel request** (e.g. *"Plan a 5-day trip to Goa under $800"*).
2. The **guardrail** checks the request is a legitimate, safe travel-planning query.
3. The **supervisor** extracts structured trip constraints (destination, budget, duration, etc.) and decides which specialist agents to invoke.
4. Selected **specialist agents** run in sequence, each pulling real data via MCP tools and writing their results into shared state.
5. The **itinerary agent** synthesizes everything into a structured draft.
6. The graph **pauses** for human review — you see the draft and choose **Approve** or **Request Changes** (with feedback).
7. If changes are requested, the **itinerary agent re-runs**, explicitly incorporating your feedback, and the cycle repeats (up to a configurable revision limit).
8. Once approved (or the revision limit is reached), the **final response agent** produces the polished plan.

---

## Known Limitations / Roadmap

- `flight_agent`'s raw AviationStack JSON isn't cleaned/summarized before being passed to the LLM prompt (unlike hotel/weather results) — a token-efficiency improvement, not a correctness issue.
- Hardcoded local paths in `mcp_client.py` should be made fully platform-independent for containerized/cloud deployment (in progress).
- No automated test suite yet — testing has been manual, end-to-end, via the Streamlit UI.
- Planned: a dedicated web frontend (Vite + React) served by a FastAPI wrapper around the LangGraph app, replacing the current Streamlit UI for production use.

---

## License

Add your preferred license here (e.g. MIT).