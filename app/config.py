"""
Configuration for RG Registered Users Agentic Chat Service.
All settings via environment variables.
"""

import os


# ── Internal Docker service URLs ──
CV_SERVICE_URL = os.getenv("CODE_VISUALIZER_SERVICE_URL", "http://code_visualizer_service:8000")
MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://memory_service:8000")
AGENT_ENGINE_URL = os.getenv("AGENT_ENGINE_URL", "http://agent_engine_service:8000")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth_service:8000")
STATE_PHYSICS_URL = os.getenv("STATE_PHYSICS_URL", "http://state_physics_service:8091")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8000")
ED_SERVICE_URL = os.getenv("ED_SERVICE_URL", "http://ed_service:8000")
RABBIT_SERVICE_URL = os.getenv("RABBIT_SERVICE_URL", "http://rabbit_api_service:8000")
CHAT_SERVICE_URL = os.getenv("CHAT_SERVICE_URL", "http://chat_service:8000")
WORKFLOW_SERVICE_URL = os.getenv("WORKFLOW_SERVICE_URL", "http://workflow_service:8000")
BILLING_SERVICE_URL = os.getenv("BILLING_SERVICE_URL", "http://billing_service:8000")
BLOCKCHAIN_SERVICE_URL = os.getenv("BLOCKCHAIN_SERVICE_URL", "http://blockchain_service:8000")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification_service:8000")
IDE_SERVICE_URL = os.getenv("IDE_SERVICE_URL", "http://ide_service:8080")
CODE_EXEC_SERVICE_URL = os.getenv("CODE_EXECUTION_SERVICE_URL", "http://code_execution_service:8000")
STORAGE_SERVICE_URL = os.getenv("STORAGE_SERVICE_URL", "http://storage_service:8000")
ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://ml_service:8000")
MARKETPLACE_SERVICE_URL = os.getenv("MARKETPLACE_SERVICE_URL", "http://marketplace_service:8000")
CRYPTO_SERVICE_URL = os.getenv("CRYPTO_SERVICE_URL", "http://crypto_service:8000")
USER_MEMORY_SERVICE_URL = os.getenv("USER_MEMORY_SERVICE_URL", "http://user_memory_service:8000")
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user_service:8000")

# ── Database ──
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/resonant_agents")

# ── API Keys (sourced from rg_llm at runtime, but also accept direct env) ──
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
SENDGRID_API_KEY = os.getenv("AUTH_SENDGRID_API_KEY", "")
SMTP_USER = os.getenv("AUTH_SMTP_USER", "noreply@resonantgenesis.com")

# ── Internal service key ──
INTERNAL_SERVICE_KEY = os.getenv("AUTH_INTERNAL_SERVICE_KEY") or os.getenv("INTERNAL_SERVICE_KEY") or ""

# ── Provider config ──
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta"

PROVIDER_MODELS = {
    "openai": "gpt-4o",
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-sonnet-4-20250514",
    "gemini": "gemini-2.0-flash",
}
PROVIDER_URLS = {
    "openai": OPENAI_API_URL,
    "groq": GROQ_API_URL,
}
PROVIDER_KEYS = {
    "openai": OPENAI_API_KEY,
    "groq": GROQ_API_KEY,
    "anthropic": ANTHROPIC_API_KEY,
    "gemini": GEMINI_API_KEY,
}
PROVIDER_FALLBACK_ORDER = ["openai", "anthropic", "gemini", "groq"]

# ── Limits ──
MAX_TOOLS_DEFAULT = 50
MAX_TOOLS_GROQ = 30
GROQ_MAX_TOOLS = 30
CUSTOM_TOOLS_CACHE_TTL = 60

# ── Context window budgets ──
PROVIDER_MAX_CONTEXT = {
    "openai": 120000,
    "anthropic": 180000,
    "groq": 120000,
    "gemini": 1000000,
}
BUDGET_SYSTEM = 0.15
BUDGET_HISTORY = 0.55
BUDGET_TOOLS = 0.10
BUDGET_RESPONSE = 0.20

# ── Platform API service URLs map ──
SERVICE_URLS = {
    "agent_engine": AGENT_ENGINE_URL,
    "chat": CHAT_SERVICE_URL,
    "workflow": WORKFLOW_SERVICE_URL,
    "memory": MEMORY_SERVICE_URL,
    "billing": BILLING_SERVICE_URL,
    "auth": AUTH_SERVICE_URL,
    "blockchain": BLOCKCHAIN_SERVICE_URL,
    "notification": NOTIFICATION_SERVICE_URL,
    "ide": IDE_SERVICE_URL,
    "code_execution": CODE_EXEC_SERVICE_URL,
    "storage": STORAGE_SERVICE_URL,
    "ml": ML_SERVICE_URL,
    "marketplace": MARKETPLACE_SERVICE_URL,
    "crypto": CRYPTO_SERVICE_URL,
    "rabbit": RABBIT_SERVICE_URL,
    "user_memory": USER_MEMORY_SERVICE_URL,
    "user": USER_SERVICE_URL,
}
