"""
RG Registered Users Agentic Chat — Standalone Microservice
============================================================
FastAPI + SSE streaming + multi-provider tool calling loop.
Uses rg_llm + rg_tool_registry via Docker volume mount.
"""

import json
import logging
import os
import re
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
    GROQ_API_KEY, PROVIDER_MODELS, PROVIDER_KEYS, PROVIDER_FALLBACK_ORDER,
    MAX_TOOLS_DEFAULT, MAX_TOOLS_GROQ, GROQ_MAX_TOOLS, MEMORY_SERVICE_URL,
    PROVIDER_MAX_CONTEXT, BUDGET_SYSTEM, BUDGET_HISTORY,
)
from .persistence import (
    list_conversations, create_conversation, load_conversation,
    delete_conversation, save_message, auto_create_conversation, _ensure_tables,
)
from .llm import (
    resolve_provider, call_llm_with_tools, call_llm_json_mode,
    build_tool_result_messages, limit_tools_for_groq,
)
from .runtime.context_manager import ContextWindowManager
from .runtime.smart_memory import filter_and_rank_memories, format_memories_for_prompt
from .handlers import fetch_user_byok_keys
from .handler_registry import CUSTOM_HANDLERS, TOOL_DEFS, _registry, _agentic_observer, _HAS_REGISTRY

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

def _build_tools_prompt(enabled: List[str], custom_tools: Dict[str, Any] = None) -> str:
    text = _registry.to_prompt_text(tools=[t for t in _registry.get_all() if t.name in enabled]) if _HAS_REGISTRY else ""
    if custom_tools:
        lines = ["\n  [CUSTOM]"]
        for tid, tdef in custom_tools.items():
            ps = ", ".join(f"{k}: {v}" for k, v in tdef.get("params", {}).items())
            lines.append(f"  - {tid}({ps}): {tdef['desc']}")
        text += "\n".join(lines)
    return text

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
        _failed_auth = set()
        session_tracker = {"tools_called": [], "total_tool_calls": 0, "total_loops": 0, "total_tokens": 0, "elapsed_seconds": 0, "skills_used": []}

        enabled = _expand_skill_ids(body.enabled_tools) if body.enabled_tools else list(TOOL_DEFS.keys())
        user_id = body.user_id or request.headers.get("x-user-id", "anonymous")

        from .handlers_orchestrator import load_user_custom_tools
        user_custom_tools = await load_user_custom_tools(user_id) if user_id != "anonymous" else {}

        native_tools = _build_native_tools(enabled, user_custom_tools)
        tools_prompt = _build_tools_prompt(enabled, user_custom_tools)
        using_json_mode = False

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
        provider, model, api_key = resolve_provider(body.preferred_provider, merged_keys)
        if body.model:
            model = body.model
        if not api_key:
            yield f"event: error\ndata: {json.dumps({'error': 'No API key for any provider.'})}\n\n"
            return

        logger.info(f"[AgenticChat] provider={provider} model={model} tools={len(native_tools)} user={user_id}")
        yield f"event: status\ndata: {json.dumps({'status': 'started', 'tools_available': len(enabled), 'conversation_id': conv_id, 'provider': provider, 'model': model})}\n\n"

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                while loop_count < body.max_loops:
                    loop_count += 1
                    yield f"event: thinking\ndata: {json.dumps({'loop': loop_count, 'message': 'Reasoning...', 'provider': provider})}\n\n"

                    max_t = MAX_TOOLS_GROQ if provider == "groq" else MAX_TOOLS_DEFAULT
                    call_tools = native_tools if len(native_tools) <= max_t else native_tools[:max_t]

                    call_messages = messages
                    if using_json_mode:
                        flat = [{"role": m["role"], "content": (m.get("content") or "") if isinstance(m.get("content"), str) else " ".join(b.get("text", str(b)) for b in (m.get("content") or []) if isinstance(b, dict))} for m in messages if m.get("role") in ("system", "user", "assistant")]
                        call_messages = flat

                    if using_json_mode:
                        llm_result = await call_llm_json_mode(client, api_key, call_messages, tools_prompt)
                    else:
                        llm_result = await call_llm_with_tools(client, provider, model, api_key, call_messages, call_tools)

                    # Handle errors with fallback
                    if llm_result.get("error"):
                        err_str = llm_result["error"]
                        logger.warning(f"[AgenticChat] {provider} failed: {err_str[:200]}")
                        if provider == "groq" and "tool_use_failed" in err_str and not using_json_mode:
                            using_json_mode = True
                            llm_result = await call_llm_json_mode(client, api_key, call_messages, tools_prompt)
                        if llm_result.get("error"):
                            el = llm_result["error"].lower()
                            if "401" in el or "api key" in el or "unauthorized" in el:
                                _failed_auth.add(provider)
                            for fb in PROVIDER_FALLBACK_ORDER:
                                if fb == provider or fb in _failed_auth:
                                    continue
                                fb_key = merged_keys.get(fb) or PROVIDER_KEYS.get(fb, "")
                                if fb_key:
                                    provider, model, api_key = fb, PROVIDER_MODELS[fb], fb_key
                                    using_json_mode = False
                                    fb_tools = limit_tools_for_groq(call_tools, _registry) if fb == "groq" else call_tools
                                    llm_result = await call_llm_with_tools(client, provider, model, api_key, call_messages, fb_tools)
                                    if not llm_result.get("error"):
                                        break
                                    fe = llm_result.get("error", "").lower()
                                    if "401" in fe or "api key" in fe:
                                        _failed_auth.add(fb)
                        if llm_result.get("error"):
                            yield f"event: error\ndata: {json.dumps({'error': llm_result['error']})}\n\n"
                            break

                    usage = llm_result.get("usage", {})
                    total_tokens += usage.get("total_tokens", usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
                    text_content = llm_result.get("text", "")
                    tool_calls = llm_result.get("tool_calls", [])

                    # Safety net: detect JSON action in text
                    if not tool_calls and text_content:
                        try:
                            pa = json.loads(text_content)
                            if isinstance(pa, dict) and pa.get("action") == "tool_call":
                                tn = pa.get("tool", "")
                                if tn:
                                    tool_calls = [{"id": f"json_{tn}", "name": tn, "arguments": json.dumps(pa.get("args", {}))}]
                                    text_content = pa.get("reasoning", "")
                                    using_json_mode = True
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass

                    if tool_calls:
                        # Append assistant message
                        if using_json_mode or llm_result.get("json_mode"):
                            messages.append({"role": "assistant", "content": text_content or f"Calling {tool_calls[0]['name']}..."})
                        elif provider in ("openai", "groq"):
                            messages.append({"role": "assistant", "content": text_content or None, "tool_calls": [{"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}} for tc in tool_calls]})
                        elif provider == "anthropic":
                            blocks = []
                            if text_content:
                                blocks.append({"type": "text", "text": text_content})
                            for tc in tool_calls:
                                try:
                                    inp = json.loads(tc["arguments"])
                                except Exception:
                                    inp = {}
                                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": inp})
                            messages.append({"role": "assistant", "content": blocks})

                        # Execute each tool
                        for tc in tool_calls:
                            tool_name = tc["name"]
                            try:
                                tool_args = json.loads(tc["arguments"])
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

                            if using_json_mode or llm_result.get("json_mode"):
                                messages.append({"role": "user", "content": f"Tool result for {tool_name}:\n{result_str}"})
                            else:
                                for msg in build_tool_result_messages(provider, tc["id"], tool_name, result_str):
                                    messages.append(msg)

                        # Trim context after tool results
                        try:
                            cm = ContextWindowManager(model)
                            messages = cm.trim_to_fit(messages, cm.estimate_tools_tokens(call_tools))
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
            yield f"event: done\ndata: {json.dumps({'loops': loop_count, 'tokens': total_tokens, 'elapsed_seconds': elapsed, 'provider': provider, 'model': model, 'tools_called_count': session_tracker['total_tool_calls']})}\n\n"
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
    available = [p for p, k in PROVIDER_KEYS.items() if k]
    return {
        "status": "healthy", "tools_available": len(TOOL_DEFS),
        "tool_categories": list(set(t.get("category", "") for t in TOOL_DEFS.values())),
        "custom_handlers": len(CUSTOM_HANDLERS),
        "providers_available": available,
        "default_provider": PROVIDER_FALLBACK_ORDER[0] if available else "none",
        "mode": "native-tool-calling",
    }

app.include_router(router)
