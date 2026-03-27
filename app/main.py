"""
RG Registered Users Agentic Chat — Standalone Microservice
============================================================
FastAPI + SSE streaming + multi-provider tool calling loop.
Uses rg_llm + rg_tool_registry via Docker volume mount.
"""

import json
import logging
import os

import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, APIRouter, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from .config import (
    MEMORY_SERVICE_URL, BILLING_SERVICE_URL,
    PROVIDER_MAX_CONTEXT, BUDGET_SYSTEM, BUDGET_HISTORY,
)
from .persistence import (
    list_conversations, create_conversation, load_conversation,
    delete_conversation, save_message, auto_create_conversation, _ensure_tables,
)
from .llm import llm_client, HAS_RG_LLM, LLMRequest
from .runtime.context_manager import ContextWindowManager
from .runtime.smart_memory import filter_and_rank_memories, format_memories_for_prompt
from .handlers import fetch_user_byok_keys
from .handler_registry import CUSTOM_HANDLERS, TOOL_DEFS, _registry, _agentic_observer, _HAS_REGISTRY

# Smart tool cap — 30 works across all providers (Groq limit)
MAX_TOOLS_CAP = 30

# Credit cost per LLM call (platform key usage)
CREDIT_COST_LLM_CALL = 20
CREDIT_COST_TOOL_CALL = 2


async def _check_credits(user_id: str) -> dict:
    """Check user's credit balance. Returns {balance, has_credits, unlimited}."""
    if not user_id or user_id == "anonymous":
        return {"balance": 0, "has_credits": False, "unlimited": False}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{BILLING_SERVICE_URL}/billing/credits/balance/{user_id}",
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "balance": data.get("balance", 0),
                    "has_credits": data.get("balance", 0) > 0,
                    "unlimited": False,
                }
    except Exception as e:
        logger.warning(f"[Credits] Balance check failed: {e}")
    # If billing service is down, allow the request
    return {"balance": -1, "has_credits": True, "unlimited": False}


async def _deduct_credits(
    user_id: str,
    amount: int,
    action: str,
    description: str,
    user_role: str = "user",
    is_superuser: bool = False,
    unlimited_credits: bool = False,
) -> dict:
    """Deduct credits via billing service. Returns {balance, deducted, warning}."""
    if not user_id or user_id == "anonymous":
        return {"balance": 0, "deducted": 0}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{BILLING_SERVICE_URL}/billing/credits/deduct",
                json={
                    "amount": amount,
                    "reference_type": action,
                    "description": description,
                },
                headers={
                    "X-User-Id": user_id,
                    "X-User-Role": user_role,
                    "X-Is-Superuser": str(is_superuser).lower(),
                    "X-Unlimited-Credits": str(unlimited_credits).lower(),
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                balance = data.get("balance_after", 0)
                warning = None
                if isinstance(balance, (int, float)):
                    if balance <= 0:
                        warning = "zero"
                    elif balance < 3000:
                        warning = "low"
                logger.info(f"\U0001f4b3 Deducted {amount} credits from {user_id[:8]}... balance={balance}")
                return {"balance": balance, "deducted": amount, "warning": warning}
            elif resp.status_code == 402:
                logger.warning(f"\u274c Insufficient credits for {user_id[:8]}...")
                return {"balance": 0, "deducted": 0, "error": "insufficient_credits"}
            else:
                logger.warning(f"[Credits] Deduction returned {resp.status_code}")
    except Exception as e:
        logger.warning(f"[Credits] Deduction failed: {e}")
    return {"balance": -1, "deducted": 0}

app = FastAPI(title="RG Registered Users Agentic Chat", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
router = APIRouter(prefix="/agentic-chat", tags=["agentic-chat"])


@app.on_event("startup")
async def startup():
    await _ensure_tables()
    from .persistence import _db_engine
    from .handlers_orchestrator import set_db_engine
    set_db_engine(_db_engine)
    logger.info(f"[STARTUP] Agentic Chat ready — {len(TOOL_DEFS)} tools, {len(CUSTOM_HANDLERS)} handlers")


# ── Helpers ──

def _estimate_tokens(text: str) -> int:
    return len(text) // 4 if text else 0

def _trim_msg(content: str, max_tokens: int) -> str:
    mc = max_tokens * 4
    return content if len(content) <= mc else content[:mc - 20] + "\n...[trimmed]"

def _expand_skill_ids(enabled: List[str]) -> List[str]:
    if not _HAS_REGISTRY:
        return enabled
    expanded = set()
    for sid in enabled:
        if sid.endswith(".*"):
            prefix = sid[:-2]
            for t in _registry.get_all():
                if t.name.startswith(prefix):
                    expanded.add(t.name)
        else:
            expanded.add(sid)
    return list(expanded)

def _build_native_tools(enabled: List[str], custom_tools: Dict[str, Any] = None) -> List[dict]:
    tools = _registry.to_openai(tools=[t for t in _registry.get_all() if t.name in enabled]) if _HAS_REGISTRY else []
    if custom_tools:
        for tid, tdef in custom_tools.items():
            props = {p: {"type": "string", "description": d} for p, d in tdef.get("params", {}).items()}
            tools.append({"type": "function", "function": {"name": tid, "description": tdef.get("desc", "")[:200], "parameters": {"type": "object", "properties": props}}})
    return tools

def _filter_tools_by_priority(tools: List[dict], max_tools: int = MAX_TOOLS_CAP) -> List[dict]:
    """Sort tools by registry priority and cap at max_tools.
    Ensures all providers (including Groq) get a manageable set."""
    if len(tools) <= max_tools:
        return tools
    def _priority(t):
        name = t.get("function", {}).get("name", "")
        if _HAS_REGISTRY and _registry:
            tdef = _registry.get(name)
            return tdef.priority if tdef else 99
        return 99
    return sorted(tools, key=_priority)[:max_tools]

def _build_context_window(system: str, history: list, user_message: str, provider: str) -> list:
    max_ctx = PROVIDER_MAX_CONTEXT.get(provider, 120000)
    sb = int(max_ctx * BUDGET_SYSTEM)
    hb = int(max_ctx * BUDGET_HISTORY)
    msgs = []
    if _estimate_tokens(system) > sb:
        system = _trim_msg(system, sb)
    msgs.append({"role": "system", "content": system})
    if history:
        entries = []
        for m in history:
            c = m.get("content", "")
            if isinstance(c, list):
                c = " ".join(b.get("text", str(b)) for b in c if isinstance(b, dict))
            entries.append((m, _estimate_tokens(c or "")))
        total = sum(t for _, t in entries)
        if total <= hb:
            for m, _ in entries:
                msgs.append(m)
        else:
            keep = min(10, len(entries))
            for m, _ in entries[-keep:]:
                msgs.append(m)
    msgs.append({"role": "user", "content": user_message})
    return msgs

async def _auto_retrieve_memories(user_id: str, message: str, history: list = None) -> str:
    if not user_id or user_id == "anonymous":
        return ""
    all_mems = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{MEMORY_SERVICE_URL}/memory/retrieve", json={"query": message[:500], "limit": 12, "user_id": user_id, "use_vector_search": True, "retrieval_mode": "hybrid"}, headers={"x-user-id": user_id})
            if resp.status_code == 200:
                data = resp.json()
                mems = data if isinstance(data, list) else data.get("memories", data.get("results", []))
                for mem in mems:
                    content = mem.get("content", mem.get("text", ""))[:500] if isinstance(mem, dict) else str(mem)[:500]
                    score = float(mem.get("score", mem.get("similarity", 0.5))) if isinstance(mem, dict) else 0.5
                    all_mems.append({"content": content, "score": score})
    except Exception as e:
        logger.warning(f"[SmartMemory] {e}")
    if not all_mems:
        return ""
    ranked = filter_and_rank_memories(memories=all_mems, query=message, history=history, min_score=0.15, max_results=5)
    return format_memories_for_prompt(ranked)


SYSTEM_TEMPLATE = """You are a powerful AI assistant on the ResonantGenesis platform with access to real tools.

{memory_context}

RULES:
1. When the user asks something that needs real data, USE YOUR TOOLS. Don't guess.
2. You can call multiple tools in sequence — call one, see the result, then decide next.
3. For current info: use web_search. For user data: use memory tools.
4. When you have enough information from tools, synthesize into a clear response.
5. If a tool fails, explain the error to the user.
6. Be concise. Show tool results clearly. Use Markdown formatting.

You are NOT a basic chatbot. You are an agentic AI that ACTIVELY uses tools to solve problems."""


class AgenticChatRequest(BaseModel):
    message: str
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None
    enabled_tools: Optional[List[str]] = None
    model: Optional[str] = None
    preferred_provider: Optional[str] = None
    max_loops: int = 50
    user_api_keys: Optional[Dict[str, str]] = None
    system_prompt: Optional[str] = None


# ━━━ Streaming Endpoint ━━━

@router.post("/stream")
async def agentic_chat_stream(body: AgenticChatRequest, request: Request):
    async def _stream():
        start_time = time.time()
        loop_count = 0
        total_tokens = 0
        provider = "unknown"
        model = body.model or "default"
        session_tracker = {"tools_called": [], "total_tool_calls": 0, "total_loops": 0, "total_tokens": 0, "elapsed_seconds": 0, "skills_used": []}

        if not HAS_RG_LLM or not llm_client:
            yield f"event: error\ndata: {json.dumps({'error': 'LLM client not available (rg_llm not found).'})}\n\n"
            return

        enabled = _expand_skill_ids(body.enabled_tools) if body.enabled_tools else list(TOOL_DEFS.keys())
        user_id = body.user_id or request.headers.get("x-user-id", "anonymous")

        from .handlers_orchestrator import load_user_custom_tools, execute_dynamic_custom_tool
        user_custom_tools = await load_user_custom_tools(user_id) if user_id != "anonymous" else {}

        native_tools = _filter_tools_by_priority(_build_native_tools(enabled, user_custom_tools))

        memory_context = await _auto_retrieve_memories(user_id, body.message, body.conversation_history)
        system = SYSTEM_TEMPLATE.format(memory_context=memory_context)
        if body.system_prompt:
            system = body.system_prompt + "\n\n" + system

        _pre_provider = (body.preferred_provider or "openai").lower()
        messages = _build_context_window(system, body.conversation_history or [], body.message, _pre_provider)

        tool_context = {
            "user_id": user_id, "org_id": request.headers.get("x-org-id", ""),
            "user_role": request.headers.get("x-user-role", "user"),
            "is_superuser": request.headers.get("x-is-superuser", "false") == "true",
            "unlimited_credits": request.headers.get("x-unlimited-credits", "false") == "true",
            "user_api_keys": body.user_api_keys or {}, "_session_tracker": session_tracker,
        }

        conv_id = body.conversation_id or ""
        if not conv_id and user_id != "anonymous":
            conv_id = await auto_create_conversation(user_id, body.message)
        if conv_id:
            await save_message(conv_id, user_id, "user", body.message)

        byok_keys = await fetch_user_byok_keys(user_id)
        merged_keys = {**byok_keys, **(body.user_api_keys or {})}

        # Determine if user is privileged (skip credit checks)
        user_role = request.headers.get("x-user-role", "user")
        is_superuser = request.headers.get("x-is-superuser", "false") == "true"
        unlimited = request.headers.get("x-unlimited-credits", "false") == "true"
        is_privileged = is_superuser or unlimited or user_role.lower() in {"owner", "platform_owner", "admin", "superuser"}

        # BYOK: user has their own LLM key for the chosen provider — skip LLM credits
        _norm_prov = _pre_provider.replace("chatgpt", "openai").replace("claude", "anthropic")
        has_byok_for_provider = bool(merged_keys.get(_norm_prov))

        # Pre-check credits (skip for privileged users)
        if not is_privileged and user_id != "anonymous":
            credit_info = await _check_credits(user_id)
            if credit_info["balance"] == 0 and not credit_info["has_credits"]:
                yield f"event: credit_warning\ndata: {json.dumps({'type': 'zero', 'balance': 0, 'message': 'You have no credits remaining. Please upgrade your plan or purchase credits.'})}\n\n"
                yield f"event: error\ndata: {json.dumps({'error': 'Insufficient credits. Please upgrade your plan or purchase credits to continue using the AI assistant.'})}\n\n"
                return
            elif isinstance(credit_info["balance"], (int, float)) and 0 < credit_info["balance"] < 3000:
                yield f"event: credit_warning\ndata: {json.dumps({'type': 'low', 'balance': credit_info['balance'], 'message': f'Low credit balance: {credit_info["balance"]} credits remaining.'})}\n\n"

        logger.info(f"[AgenticChat] preferred={_pre_provider} tools={len(native_tools)} user={user_id} byok={list(merged_keys.keys())} byok_active={has_byok_for_provider}")
        yield f"event: status\ndata: {json.dumps({'status': 'started', 'tools_available': len(native_tools), 'conversation_id': conv_id, 'provider': _pre_provider})}\n\n"

        try:
            while loop_count < body.max_loops:
                loop_count += 1
                yield f"event: thinking\ndata: {json.dumps({'loop': loop_count, 'message': 'Reasoning...'})}\n\n"

                llm_request = LLMRequest(
                    messages=messages,
                    provider=_pre_provider,
                    model=body.model or None,
                    temperature=0.3,
                    max_tokens=4096,
                    tools=native_tools if native_tools else None,
                    tool_choice="auto" if native_tools else None,
                    user_id=user_id,
                )

                response = await llm_client.complete(llm_request, user_keys=merged_keys)
                provider = response.provider or _pre_provider
                model = response.model or model

                if response.content and response.content.startswith("Error:"):
                    yield f"event: error\ndata: {json.dumps({'error': response.content})}\n\n"
                    break

                usage = response.usage or {}
                total_tokens += usage.get("total_tokens", usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
                text_content = response.content or ""
                tool_calls = response.tool_calls or []

                # Deduct credits for LLM call (skip for BYOK users + privileged)
                if not is_privileged and user_id != "anonymous":
                    llm_cost = 0 if has_byok_for_provider else CREDIT_COST_LLM_CALL
                    if llm_cost > 0:
                        cr = await _deduct_credits(
                            user_id, llm_cost, "chat_message",
                            f"AI Assistant: {_pre_provider}/{model} loop {loop_count}",
                            user_role=user_role, is_superuser=is_superuser, unlimited_credits=unlimited,
                        )
                        if cr.get("error") == "insufficient_credits":
                            yield f"event: credit_warning\ndata: {json.dumps({'type': 'zero', 'balance': 0, 'message': 'Credits exhausted during conversation.'})}\n\n"
                            yield f"event: error\ndata: {json.dumps({'error': 'Insufficient credits. Your balance reached zero.'})}\n\n"
                            break
                        if cr.get("warning"):
                            yield f"event: credit_warning\ndata: {json.dumps({'type': cr['warning'], 'balance': cr['balance'], 'message': f'Credit balance: {cr["balance"]} remaining' if cr['warning'] == 'low' else 'Credits exhausted!'})}\n\n"

                if tool_calls:
                    # Append assistant message in OpenAI format (rg_llm handles conversion)
                    messages.append({
                        "role": "assistant",
                        "content": text_content or None,
                        "tool_calls": [{
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": tc.arguments},
                        } for tc in tool_calls],
                    })

                    # Execute each tool
                    for tc in tool_calls:
                        tool_name = tc.name
                        try:
                            tool_args = json.loads(tc.arguments)
                        except Exception:
                            tool_args = {}

                        yield f"event: tool_call\ndata: {json.dumps({'tool': tool_name, 'args': tool_args, 'loop': loop_count})}\n\n"

                        tdef_cat = TOOL_DEFS.get(tool_name, {}).get("category", "custom")
                        session_tracker["tools_called"].append({"tool": tool_name, "category": tdef_cat, "loop": loop_count})
                        session_tracker["total_tool_calls"] += 1
                        session_tracker["total_loops"] = loop_count
                        session_tracker["total_tokens"] = total_tokens
                        session_tracker["elapsed_seconds"] = round(time.time() - start_time, 2)

                        # Execute handler
                        tdef = TOOL_DEFS.get(tool_name)
                        is_custom = tool_name in user_custom_tools
                        if not tdef and not is_custom:
                            tool_result = {"error": f"Tool '{tool_name}' not found."}
                        elif is_custom:
                            try:
                                tool_result = await execute_dynamic_custom_tool(tool_name, tool_args, tool_context)
                            except Exception as e:
                                tool_result = {"error": str(e)[:500]}
                        elif tool_name not in enabled:
                            tool_result = {"error": f"Tool '{tool_name}' not enabled."}
                        else:
                            handler_key = tdef["handler"]
                            if handler_key in CUSTOM_HANDLERS:
                                try:
                                    tool_result = await CUSTOM_HANDLERS[handler_key](tool_args, tool_context)
                                except Exception as e:
                                    tool_result = {"error": str(e)[:500]}
                            else:
                                tool_result = {"error": f"No handler for '{tool_name}'"}

                        result_str = json.dumps(tool_result, default=str)
                        if len(result_str) > 8000:
                            result_str = result_str[:8000] + "...(truncated)"

                        yield f"event: tool_result\ndata: {json.dumps({'tool': tool_name, 'result': result_str[:4000], 'loop': loop_count})}\n\n"

                        # OpenAI-format tool result (rg_llm converts for Anthropic/Gemini)
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

                    # Trim context after tool results
                    try:
                        cm = ContextWindowManager(model)
                        messages = cm.trim_to_fit(messages, cm.estimate_tools_tokens(native_tools))
                    except Exception:
                        pass
                    continue

                else:
                    content = text_content or "No response from model."
                    if conv_id and content:
                        await save_message(conv_id, user_id, "assistant", content, tokens=total_tokens)
                    yield f"event: response\ndata: {json.dumps({'content': content, 'loop': loop_count, 'tokens': total_tokens, 'provider': provider, 'model': model})}\n\n"
                    break

            elapsed = round(time.time() - start_time, 2)
            # Final balance check for done event
            final_balance = None
            if not is_privileged and user_id != "anonymous":
                final_info = await _check_credits(user_id)
                final_balance = final_info.get("balance")
            yield f"event: done\ndata: {json.dumps({'loops': loop_count, 'tokens': total_tokens, 'elapsed_seconds': elapsed, 'provider': provider, 'model': model, 'tools_called_count': session_tracker['total_tool_calls'], 'credits_balance': final_balance, 'byok_active': has_byok_for_provider})}\n\n"
        except Exception as e:
            logger.exception("Agentic chat error")
            yield f"event: error\ndata: {json.dumps({'error': str(e)[:500]})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


# ━━━ Conversation CRUD ━━━

@router.get("/conversations")
async def api_list_conversations(request: Request):
    user_id = request.headers.get("x-user-id", "")
    return await list_conversations(user_id)

@router.post("/conversations")
async def api_create_conversation(request: Request):
    user_id = request.headers.get("x-user-id", "")
    body = await request.json()
    return await create_conversation(user_id, body.get("title", "New conversation"))

@router.get("/conversations/{conv_id}")
async def api_load_conversation(conv_id: str, request: Request):
    return await load_conversation(conv_id, request.headers.get("x-user-id", ""))

@router.delete("/conversations/{conv_id}")
async def api_delete_conversation(conv_id: str, request: Request):
    return await delete_conversation(conv_id, request.headers.get("x-user-id", ""))


# ━━━ Health ━━━

@router.get("/health")
async def health():
    return {
        "status": "healthy", "tools_available": len(TOOL_DEFS),
        "tool_categories": list(set(t.get("category", "") for t in TOOL_DEFS.values())),
        "custom_handlers": len(CUSTOM_HANDLERS),
        "rg_llm_available": HAS_RG_LLM,
        "max_tools_cap": MAX_TOOLS_CAP,
        "mode": "rg_llm_unified",
    }

app.include_router(router)
