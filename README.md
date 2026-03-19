# RG Registered Users Agentic Chat

Standalone microservice for the ResonantGenesis Agentic Chat system — extracted from `agent_engine_service`.

## Architecture

- **FastAPI** with SSE streaming (`/agentic-chat/stream`)
- **Multi-provider LLM** — OpenAI, Anthropic, Gemini, Groq with automatic fallback
- **130+ tools** via `rg_tool_registry` (volume-mounted shared module)
- **Thin HTTP proxy handlers** — no service logic duplicated; all tools proxy to real microservices
- **Smart memory** — auto-retrieves relevant memories from `memory_service` before each conversation
- **Context window management** — token-aware trimming per provider
- **Persistent conversations** — PostgreSQL (shared `resonant_agents` DB)
- **BYOK** — users can bring their own API keys (fetched from `auth_service`)

## File Structure

```
app/
├── main.py                  # FastAPI app, streaming endpoint, conversation CRUD
├── config.py                # All env vars and provider config
├── handler_registry.py      # CUSTOM_HANDLERS + TOOL_DEFS mapping
├── llm.py                   # Multi-provider LLM calling (OpenAI/Anthropic/Gemini/Groq)
├── persistence.py           # Conversation + custom tools DB layer
├── handlers.py              # CV, Memory, Hash Sphere, local IDE handlers
├── handlers_agents.py       # Agent Engine proxy handlers
├── handlers_state_physics.py # State Physics proxy handlers
├── handlers_web.py          # Web search, browsing, Reddit, news
├── handlers_github.py       # GitHub API handlers
├── handlers_rabbit.py       # Community forum handlers
├── handlers_utilities.py    # Weather, image/places/YouTube search, stock, research, chart, email, wiki, SVG
├── handlers_orchestrator.py # Workspace snapshot, scheduling, run snapshot, custom tool CRUD
└── runtime/
    ├── context_manager.py   # Token-aware context window trimming
    └── smart_memory.py      # Memory scoring, dedup, ranking
```

## Volume Mounts (Required)

These shared modules are NOT bundled — they are mounted at runtime:

- `rg_llm` → `/app/rg_llm:ro` (from `RG_UnifiedLLMClient`)
- `rg_tool_registry` → `/app/rg_tool_registry:ro` (from `RG_Unified_Tool_Registry`)

## Running

```bash
# Local dev
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8095

# Docker
docker build -t rg_agentic_chat .
docker run -p 8095:8000 --env-file .env rg_agentic_chat
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/agentic-chat/stream` | SSE streaming agentic chat |
| GET | `/agentic-chat/conversations` | List user conversations |
| POST | `/agentic-chat/conversations` | Create conversation |
| GET | `/agentic-chat/conversations/{id}` | Load conversation |
| DELETE | `/agentic-chat/conversations/{id}` | Delete conversation |
| GET | `/agentic-chat/health` | Health check |

## Gateway Integration

Update gateway to proxy `/api/v1/agentic-chat/*` → `http://rg_agentic_chat:8000` instead of `agent_engine_service`.
