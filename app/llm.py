"""
LLM client for RG Registered Users Agentic Chat.
Uses rg_llm.UnifiedLLMClient — same unified path as all platform services.
No direct HTTP calls. No JSON mode fallback. No per-provider spaghetti.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ── rg_llm volume mount (shared module — single source of truth) ──
try:
    from rg_llm import UnifiedLLMClient, LLMRequest, LLMResponse
    from rg_llm.models import ToolCall
    llm_client = UnifiedLLMClient(fallback_order=["openai", "anthropic", "google", "groq"])
    HAS_RG_LLM = True
    logger.info("[LLM] rg_llm UnifiedLLMClient ready (openai → anthropic → google → groq)")
except ImportError:
    llm_client = None
    LLMRequest = None
    LLMResponse = None
    ToolCall = None
    HAS_RG_LLM = False
    logger.error("[LLM] rg_llm not found — agentic chat will not work")
