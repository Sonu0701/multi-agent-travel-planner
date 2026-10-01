# 🌍 TripPilot — Agentic Travel Planning System

> An AI-powered travel planning system built with **LangGraph**, featuring supervisor-routed specialist agents, real-world data through **Model Context Protocol (MCP)** servers, human approval workflows, and durable PostgreSQL state.

[![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-1C3C3C)](https://github.com/langchain-ai/langgraph)
[![MCP](https://img.shields.io/badge/Tool%20Protocol-MCP-blueviolet)](https://modelcontextprotocol.io/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![PostgreSQL](https://img.shields.io/badge/Persistence-PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)

## Overview

**Multi-Agent Travel Planner** turns a natural-language travel request into a structured itinerary using a coordinated team of AI agents.

Instead of relying on one large prompt, the application divides planning into specialized tasks. A supervisor determines which agents are required, specialists collect live travel information, and an itinerary agent combines the results into a draft.

Before the itinerary is finalized, execution pauses for human review. The user can approve the plan or request specific changes, which are incorporated into the next revision.

### Example request

> “Plan a five-day trip to Goa under $800, including hotels, weather, and an estimated daily budget.”

The system can:

- Validate whether the request is relevant and safe
- Extract destination, dates, duration, budget, and preferences
- Dynamically select the required specialist agents
- Retrieve real-world information through MCP tools
- Generate a structured itinerary
- Pause for human approval
- Revise the itinerary using explicit user feedback
- Resume interrupted workflows using PostgreSQL checkpoints

---

## Architecture

```text
User Request
     │
     ▼
┌─────────────────────────┐
│     Input Guardrail     │
│                         │
│ Validates relevance,    │
│ safety, and policy      │
└────────────┬────────────┘
             │ Allowed
             ▼
┌─────────────────────────┐
│    Supervisor Agent     │
│                         │
│ Extracts constraints    │
│ and dynamically routes  │
│ the request             │
└────────────┬────────────┘
             │
             ▼
┌───────────────────────────────────────────────┐
│             Specialist Agents                │
│                                               │
│  ✈️ Flight Agent        🏨 Hotel Agent       │
│  🌦️ Weather Agent      💰 Budget Agent       │
│                                               │
│      Only required specialists are run       │
└──────────────────────┬────────────────────────┘
                       │
                       ▼
              ┌─────────────────────┐
              │   Itinerary Agent   │
              │                     │
              │ Combines specialist │
              │ results into a plan │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │   Human Approval    │
              │                     │
              │ LangGraph interrupt │
              └──────────┬──────────┘
                         │
             ┌───────────┴───────────┐
             │                       │
          Approved                Rejected
             │                  with feedback
             ▼                       │
┌─────────────────────────┐          │
│     Final Response      │          │
│                         │          │
│ Produces the polished   │          │
│ travel plan             │          │
└─────────────────────────┘          │
                                     ▼
                          Itinerary Agent reruns
                          up to MAX_REVISIONS
```

---

## Shared State

Every graph node reads from and writes to a typed `TravelState` object.

The state tracks:

- Original user request
- Extracted trip constraints
- Selected specialist agents
- Flight information
- Hotel information
- Weather information
- Budget estimates
- Current itinerary draft
- Human approval status
- Revision feedback
- Revision count
- Guardrail result and errors

This creates a transparent workflow in which each agent has a focused responsibility while still contributing to the same execution context.

---

## Key Features

### 🧭 Dynamic Agent Routing

The supervisor analyzes each request and invokes only the specialists that are necessary.

For example:

- A hotel-only question can skip the flight, weather, and budget agents.
- A weather question does not trigger unnecessary hotel searches.
- A complete trip request can use the entire agent team.

This reduces latency, API usage, and LLM cost compared with a fixed pipeline.

### 🛡️ Input Guardrails

An LLM-based guardrail validates requests before specialist agents or external APIs are called.

It can reject:

- Requests unrelated to travel
- Unsafe or harmful requests
- Invalid or unusable input
- Requests outside the application's intended scope

Rejected requests short-circuit the graph, preventing unnecessary downstream work.

### 🙋 Human-in-the-Loop Approval

The graph pauses using LangGraph's `interrupt()` mechanism after generating a draft itinerary.

The user can:

- **Approve** the itinerary and continue to the final response
- **Request changes** and provide detailed feedback

When changes are requested, the itinerary agent runs again and explicitly incorporates the feedback into the revised plan.

### 🔁 Controlled Revision Loop

A configurable `MAX_REVISIONS` limit prevents:

- Infinite rejection loops
- Unexpected LLM costs
- Excessive API usage
- Workflows that never terminate

### 🔌 Real-World Data Through MCP

The application uses **Model Context Protocol** integrations instead of depending entirely on the model's internal knowledge.

| Integration | Purpose | Transport |
|---|---|---|
| Tavily | Hotel and general web search | Streamable HTTP |
| AviationStack | Airport and airline information | Custom stdio MCP server |
| OpenWeather | Current weather and forecasts | Custom stdio MCP server |

### 🧯 Resilient Tool Execution

External tools can fail because of timeouts, invalid credentials, rate limits, or malformed responses.

Tool calls are wrapped with graceful error handling so that one failed integration does not crash the entire graph. Agents receive a clear fallback message and can continue with the available information.

### 🧹 Clean Data Pipelines

Large API responses are parsed and converted into concise, prompt-friendly text before being sent to the model.

This helps:

- Reduce token usage
- Remove irrelevant response fields
- Improve prompt clarity
- Make model output more consistent

### 💾 Durable PostgreSQL Checkpoints

LangGraph state can be persisted using:

- `langgraph-checkpoint-postgres`
- `psycopg_pool.ConnectionPool`

This allows interrupted workflows—including pending human approvals—to survive application restarts.

If PostgreSQL is not configured, the application can still run without durable checkpointing.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python |
| Agent orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) |
| LLM provider | Groq through `langchain-groq` |
| Tool protocol | MCP through `langchain-mcp-adapters` |
| Search | Tavily |
| Flight data | AviationStack |
| Weather data | OpenWeather |
| Persistence | PostgreSQL |
| Connection pooling | `psycopg_pool` |
| User interface | Streamlit |

---

## Project Structure

```text
multi-agent-travel-planner/
├── agents.py
│   └── Agent node implementations:
│       guardrail, supervisor, specialists,
│       itinerary, approval, and final response
│
├── graph.py
│   └── LangGraph construction, conditional routing,
│       revision flow, and checkpointer configuration
│
├── state.py
│   └── TravelState TypedDict shared across graph nodes
│
├── config.py
│   └── Environment configuration and LLM initialization
│
├── mcp_client.py
│   └── MultiServerMCPClient configuration
│
├── custom_weather_mcp_server.py
│   └── Custom MCP server for the OpenWeather API
│
├── frontend1.py
│   └── Streamlit chat UI and approval controls
│
├── aviationstack-mcp/
│   └── Custom AviationStack MCP server package
│
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

---

## Getting Started

### Prerequisites

Before running the project, make sure you have:

- Python installed
- PostgreSQL access if durable checkpointing is required
- API keys for Groq, Tavily, AviationStack, and OpenWeather

### 1. Clone the repository

```bash
git clone https://github.com/Sonu0701/multi-agent-travel-planner.git
cd multi-agent-travel-planner
```

### 2. Create a virtual environment

#### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
```

#### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the application dependencies

```bash
pip install -r requirements.txt
```

### 4. Install the AviationStack MCP server

The AviationStack integration is maintained as a local Python package with its own dependencies.

```bash
cd aviationstack-mcp
pip install -e .
cd ..
```

### 5. Configure environment variables

Create a `.env` file in the project root:

```env
# LLM
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b

# External services
TAVILY_API_KEY=your_tavily_api_key
AVIATION_STACK_API_KEY=your_aviationstack_api_key
OPENWEATHER_API_KEY=your_openweather_api_key

# Optional durable checkpointing
DATABASE_URL=postgresql://user:password@host:5432/database_name
```

> [!IMPORTANT]
> Never commit your `.env` file or API credentials to version control.

`DATABASE_URL` is optional. If it is omitted, the graph runs without persistent checkpoints. In that mode, interrupted workflows cannot be resumed after the application restarts.

### 6. Start the application

```bash
streamlit run frontend1.py
```

Open the local URL printed by Streamlit, usually:

```text
http://localhost:8501
```

---

## How the Workflow Runs

1. The user submits a travel-planning request.
2. The guardrail checks whether the request is valid, safe, and travel-related.
3. The supervisor extracts trip constraints and selects the required agents.
4. The selected specialists retrieve information through MCP tools.
5. Each specialist writes its result to the shared state.
6. The itinerary agent combines the available information into a draft.
7. LangGraph pauses execution for human review.
8. The user approves the draft or requests changes.
9. If rejected, the itinerary agent incorporates the feedback and generates a new version.
10. Once approved—or when the revision limit is reached—the final response agent produces the completed travel plan.

---

## Engineering Highlights

This project demonstrates practical experience with:

- Multi-agent workflow design
- Conditional graph routing
- Typed shared state management
- Human-in-the-loop AI systems
- Persistent and resumable agent execution
- Model Context Protocol integrations
- Custom MCP server development
- External API response processing
- Fault-tolerant tool execution
- LLM guardrails and request validation
- Connection pooling and PostgreSQL persistence
- Token and API-cost optimization

---

## Current Limitations

- AviationStack responses still require the same cleaning and summarization pipeline used for hotel and weather data.
- Some MCP server paths need to be made fully platform-independent for container and cloud deployment.
- Testing is currently performed manually through the Streamlit interface.
- The quality and availability of results depend on external API limits and data coverage.
- The Streamlit interface is intended as a development UI rather than a production frontend.

---

## Roadmap

- [ ] Add unit tests for individual graph nodes
- [ ] Add integration tests for MCP tool calls
- [ ] Add end-to-end tests for approval and revision workflows
- [ ] Normalize AviationStack responses before LLM processing
- [ ] Remove hardcoded local paths
- [ ] Add structured logging and observability
- [ ] Add retry and backoff policies for external APIs
- [ ] Containerize the complete application
- [ ] Add CI checks using GitHub Actions
- [ ] Build a FastAPI backend
- [ ] Replace Streamlit with a Vite and React frontend
- [ ] Add authentication and per-user trip history
- [ ] Support additional travel providers

---

## Security Notes

- Keep all credentials in environment variables.
- Do not commit `.env` files.
- Apply request timeouts to external API calls.
- Restrict database credentials to the minimum required permissions.
- Validate and sanitize human feedback before using it in downstream prompts.
- Rotate any key that has accidentally been exposed.

---

## Contributing

Contributions, bug reports, and feature suggestions are welcome.

1. Fork the repository.
2. Create a feature branch:

```bash
git checkout -b feature/your-feature-name
```

3. Commit your changes:

```bash
git commit -m "Add your feature"
```

4. Push the branch:

```bash
git push origin feature/your-feature-name
```

5. Open a pull request.

---

## License

A license has not yet been selected.

Before distributing or accepting contributions, add a license such as the [MIT License](https://choosealicense.com/licenses/mit/) and update this section.

---

## Author

**Sonu Kumar**

- GitHub: [@Sonu0701](https://github.com/Sonu0701)
- Project: [Multi-Agent Travel Planner](https://github.com/Sonu0701/multi-agent-travel-planner)

---

<p align="center">
  Built with LangGraph, MCP, PostgreSQL, and Streamlit.
</p>