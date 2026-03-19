# RG Registered Users Agentic Chat

> **Part of the [ResonantGenesis](https://dev-swat.com) platform** — standalone microservice for authenticated AI assistant chat.

Full-featured agentic AI assistant for **registered users** on the ResonantGenesis platform. Provides multi-provider LLM conversations with 130+ tools, persistent memory, BYOK API keys, and real-time SSE streaming — extracted from the monolith `agent_engine_service` as a clean standalone module.

## Architecture

```
User → Nginx → Gateway (auth) → rg_agentic_chat (this service)
                                     ├── LLM Providers (OpenAI / Anthropic / Gemini / Groq)
                                     ├── rg_llm (volume-mounted shared LLM client)
                                     ├── rg_tool_registry (volume-mounted tool registry)
                                     ├── memory_service (smart memory retrieval)
                                     ├── auth_service (BYOK key fetching)
                                     ├── code_visualizer_service
                                     ├── agent_engine_service
                                     ├── state_physics_service
                                     └── 15+ other platform microservices (via HTTP proxy)
```

**Key design decisions:**
- **FastAPI** with SSE streaming (`/agentic-chat/stream`)
- **Multi-provider LLM** — OpenAI, Anthropic, Gemini, Groq with automatic fallback chain
- **130+ tools** via `rg_tool_registry` (volume-mounted shared module)
- **Thin HTTP proxy handlers** — no service logic duplicated; all tools proxy to real microservices
- **Smart memory** — auto-retrieves and ranks relevant memories from `memory_service` before each turn
- **Context window management** — token-aware trimming per provider (120K–1M context)
- **Persistent conversations** — PostgreSQL (`resonant_agents` database)
- **BYOK (Bring Your Own Key)** — users can bring their own API keys, fetched from `auth_service` (encrypted, DB-backed)
- **Custom user tools** — users can define their own tools stored in the database
- **JSON-mode fallback** — if native function calling fails (e.g., Groq `tool_use_failed`), falls back to JSON action format

## Quick Start

```bash
# Clone
git clone git@github-devswat:DevSwat-ResonantGenesis/RG_Registered_Users_Agentic_Chat.git
cd RG_Registered_Users_Agentic_Chat

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — requires DATABASE_URL and at least one LLM API key

# Run locally (requires PostgreSQL + platform services for full functionality)
uvicorn app.main:app --host 0.0.0.0 --port 8095 --reload
```

## Docker

```bash
# Build
docker build -t rg-agentic-chat .

# Run (standalone — needs network access to other services)
docker run -p 8095:8000 --env-file .env rg-agentic-chat
```

### Docker Compose Integration

Add this snippet to `docker-compose.unified.yml`:

```yaml
rg_agentic_chat:
  build:
    context: ./RG_Registered_Users_Agentic_Chat
    dockerfile: Dockerfile
  container_name: rg_agentic_chat
  restart: unless-stopped
  ports:
    - "8095:8000"
  environment:
    - DATABASE_URL=postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@db:5432/resonant_agents
    - GROQ_API_KEY=${GROQ_API_KEY}
    - OPENAI_API_KEY=${OPENAI_API_KEY}
    - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    - GEMINI_API_KEY=${GEMINI_API_KEY}
    # ... see .env.example for full list
  volumes:
    - /home/deploy/RG_UnifiedLLMClient/src/rg_llm:/app/rg_llm:ro
    - /home/deploy/RG_Unified_Tool_Registry/rg_tool_registry:/app/rg_tool_registry:ro
  depends_on:
    - db
    - memory_service
    - auth_service
  networks:
    - resonant-network
```

## Volume Mounts (Required)

These shared modules are **NOT bundled** — they are mounted read-only at runtime:

| Mount | Source Repo | Path in Container |
|-------|-----------|-------------------|
| `rg_llm` | `RG_UnifiedLLMClient` | `/app/rg_llm:ro` |
| `rg_tool_registry` | `RG_Unified_Tool_Registry-Observability_Module` | `/app/rg_tool_registry:ro` |

Both use `PYTHONPATH=/app` so imports work as `from rg_llm import ...` and `from rg_tool_registry import ...`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/agentic-chat/stream` | SSE streaming agentic chat (main endpoint) |
| `GET` | `/agentic-chat/conversations` | List user conversations |
| `POST` | `/agentic-chat/conversations` | Create new conversation |
| `GET` | `/agentic-chat/conversations/{id}` | Load conversation with messages |
| `DELETE` | `/agentic-chat/conversations/{id}` | Delete conversation |
| `GET` | `/agentic-chat/health` | Health check — tools, providers, handlers |

### Request Body (`POST /agentic-chat/stream`)

```json
{
  "message": "Analyze the GitHub repo louienemesh/RG_UnifiedLLMClient",
  "user_id": "uuid-or-set-via-header",
  "conversation_id": "optional-uuid",
  "conversation_history": [],
  "enabled_tools": ["web_search.*", "code_visualizer.*", "memory.*"],
  "model": "gpt-4o",
  "preferred_provider": "openai",
  "max_loops": 50,
  "user_api_keys": {"anthropic": "sk-ant-..."},
  "system_prompt": "Optional additional system context"
}
```

### SSE Events

| Event | Description |
|-------|-------------|
| `status` | Session started — tools count, conversation_id, provider, model |
| `thinking` | Loop N reasoning (with provider info) |
| `tool_call` | Tool invoked — name, args, loop |
| `tool_result` | Tool returned — name, result (truncated to 4KB), loop |
| `response` | Final assistant text response with token/provider info |
| `done` | Session complete — loops, tokens, elapsed, tools_called_count |
| `error` | Error occurred |

## LLM Providers

| Provider | Model | Context Window | Tool Calling |
|----------|-------|---------------|-------------|
| **OpenAI** | `gpt-4o` | 120K tokens | Native |
| **Anthropic** | `claude-sonnet-4-20250514` | 180K tokens | Native |
| **Gemini** | `gemini-2.0-flash` | 1M tokens | Native |
| **Groq** | `llama-3.3-70b-versatile` | 120K tokens | Native + JSON fallback |

**Fallback order**: OpenAI → Anthropic → Gemini → Groq

Provider selection: BYOK keys take priority → platform keys → fallback chain.

## Tool Categories (130+)

| Category | Examples | Handler File |
|----------|---------|-------------|
| **Web & Search** | web_search, fetch_url, read_webpage, reddit_search, news_search | `handlers_web.py` |
| **Code & Analysis** | code_visualizer_*, github_* | `handlers.py`, `handlers_github.py` |
| **Memory** | memory_store, memory_retrieve, memory_search | `handlers.py` |
| **Agents** | agent_create, agent_execute, team_* | `handlers_agents.py` |
| **State Physics** | universe_state, simulate, invariants | `handlers_state_physics.py` |
| **Community** | rabbit_post, rabbit_search, rabbit_vote | `handlers_rabbit.py` |
| **Utilities** | weather, stock_crypto, email, chart, wiki, SVG | `handlers_utilities.py` |
| **Orchestration** | workspace_snapshot, scheduling, custom_tool_* | `handlers_orchestrator.py` |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | **Yes** | PostgreSQL async connection string |
| `GROQ_API_KEY` | No | Groq API key |
| `OPENAI_API_KEY` | No | OpenAI API key |
| `ANTHROPIC_API_KEY` | No | Anthropic API key |
| `GEMINI_API_KEY` | No | Google Gemini API key |
| `TAVILY_API_KEY` | No | Tavily web search API key |
| `SERPAPI_KEY` | No | SerpAPI key (images, YouTube, places) |
| `PERPLEXITY_API_KEY` | No | Perplexity API key |
| `AUTH_INTERNAL_SERVICE_KEY` | No | Internal service-to-service auth key |
| `MEMORY_SERVICE_URL` | No | Memory service URL (default: `http://memory_service:8000`) |
| `AUTH_SERVICE_URL` | No | Auth service URL (default: `http://auth_service:8000`) |

See `.env.example` for the full list of 20+ internal service URLs.

## File Structure

```
app/
├── main.py                    # FastAPI app, SSE streaming endpoint, conversation CRUD
├── config.py                  # All env vars, provider config, context budgets
├── handler_registry.py        # CUSTOM_HANDLERS + TOOL_DEFS mapping (from rg_tool_registry)
├── llm.py                     # Multi-provider LLM calling (OpenAI/Anthropic/Gemini/Groq)
├── persistence.py             # Conversation + custom tools DB layer (async PostgreSQL)
├── handlers.py                # Code Visualizer, Memory, Hash Sphere, BYOK key fetching
├── handlers_agents.py         # Agent Engine proxy handlers
├── handlers_state_physics.py  # State Physics / Hash Sphere SIM proxy handlers
├── handlers_web.py            # Web search, browsing, Reddit, news, Perplexity
├── handlers_github.py         # GitHub API handlers
├── handlers_rabbit.py         # Community forum (Rabbit) handlers
├── handlers_utilities.py      # Weather, image/places/YouTube search, stock, chart, email, wiki, SVG
├── handlers_orchestrator.py   # Workspace snapshot, scheduling, custom tool CRUD
└── runtime/
    ├── context_manager.py     # Token-aware context window trimming per provider
    └── smart_memory.py        # Memory scoring, deduplication, ranking
docker-compose.snippet.yml     # Docker Compose snippet for integration
.env.example                   # Environment variable template
Dockerfile                     # Production Docker image
requirements.txt               # Python dependencies
```

## Gateway Integration

Update gateway to proxy agentic chat to this service:
```
/api/v1/agentic-chat/* → http://rg_agentic_chat:8000/agentic-chat/*
```

This replaces the current routing to `agent_engine_service`.

## Security

- **Authenticated only** — requires user identity via `x-user-id` header (set by gateway after auth)
- **BYOK keys encrypted** — fetched from `auth_service` DB, never stored locally
- **Per-user conversations** — users can only access their own conversations
- **Tool scoping** — tools can be enabled/disabled per request via `enabled_tools`
- **Context trimming** — prevents token overflow per provider limits

## Related Modules

| Module | Repo | Relationship |
|--------|------|-------------|
| Public Guest Chat | `RG_Public-Guest-Agentic_Chat` | Unauthenticated variant (14 tools, no DB) |
| Unified LLM Client | `RG_UnifiedLLMClient` | Shared LLM provider abstraction (volume-mounted) |
| Unified Tool Registry | `RG_Unified_Tool_Registry-Observability_Module` | Tool definitions + observability (volume-mounted) |
| Resonant IDE | `RG_IDE` | IDE client that calls this service for AI chat |

## Deployment Status

- **Extracted from**: `genesis2026_production_backend/agent_engine_service` (agentic chat router)
- **Production**: Not yet deployed as standalone — currently runs inside `agent_engine_service`
- **Target**: Replace the agentic chat router in `agent_engine_service` with this standalone service
- **Database**: Shares `resonant_agents` PostgreSQL database with `agent_engine_service`

---

**Organization**: [DevSwat-ResonantGenesis](https://github.com/DevSwat-ResonantGenesis)
**Platform**: [dev-swat.com](https://dev-swat.com)
