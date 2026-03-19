"""
LLM calling functions — multi-provider tool calling (OpenAI, Anthropic, Gemini, Groq).
Extracted from routers_agentic_chat.py for the standalone service.
"""

import json
import re
import logging
from typing import Dict, List, Any

import httpx

from .config import (
    GROQ_API_KEY, GROQ_API_URL, OPENAI_API_URL, ANTHROPIC_API_URL,
    GEMINI_API_URL, PROVIDER_URLS, PROVIDER_MODELS, PROVIDER_KEYS,
    PROVIDER_FALLBACK_ORDER, GROQ_MAX_TOOLS,
)

logger = logging.getLogger(__name__)

# ── rg_llm volume mount (shared module) ──
try:
    from rg_llm import UnifiedLLMClient, LLMRequest
    _llm_client = UnifiedLLMClient(fallback_order=["openai", "anthropic", "google", "groq"])
    _HAS_RG_LLM = True
except ImportError:
    _llm_client = None
    _HAS_RG_LLM = False
    logger.warning("[LLM] rg_llm not found — using direct HTTP calls only")


def resolve_provider(preferred: str = None, user_api_keys: Dict[str, str] = None) -> tuple:
    """Resolve provider, model, and API key. Returns (provider, model, api_key)."""
    alias_map = {"chatgpt": "openai", "gpt": "openai", "claude": "anthropic", "google": "gemini"}
    normalized = alias_map.get((preferred or "").lower(), (preferred or "").lower())
    user_keys = user_api_keys or {}

    if normalized and normalized in PROVIDER_MODELS:
        key = user_keys.get(normalized) or PROVIDER_KEYS.get(normalized, "")
        if key:
            return normalized, PROVIDER_MODELS[normalized], key

    for prov in PROVIDER_FALLBACK_ORDER:
        key = user_keys.get(prov) or PROVIDER_KEYS.get(prov, "")
        if key:
            return prov, PROVIDER_MODELS[prov], key

    return "groq", PROVIDER_MODELS["groq"], GROQ_API_KEY


def build_anthropic_tools(openai_tools: List[dict]) -> List[dict]:
    """Convert OpenAI-format tools to Anthropic format."""
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in openai_tools
    ]


def limit_tools_for_groq(tools: List[dict], registry=None) -> List[dict]:
    """Sort tools by registry priority and cap at GROQ_MAX_TOOLS."""
    if len(tools) <= GROQ_MAX_TOOLS:
        return tools

    def _priority(t):
        name = t.get("function", {}).get("name", "")
        if registry:
            tdef = registry.get(name)
            return tdef.priority if tdef else 99
        return 99
    return sorted(tools, key=_priority)[:GROQ_MAX_TOOLS]


async def call_llm_json_mode(
    client: httpx.AsyncClient, api_key: str, messages: list,
    tools_prompt: str, temperature: float = 0.3,
) -> dict:
    """Fallback: JSON-mode prompt-based tool calling via rg_llm or direct Groq."""
    json_system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    json_system += f"\n\nAVAILABLE TOOLS:\n{tools_prompt}\n\n"
    json_system += (
        "RESPONSE FORMAT — respond with valid JSON only.\n"
        'To use a tool: {{"action": "tool_call", "tool": "<tool_name>", "args": {{...}}, "reasoning": "<why>"}}\n'
        'To respond: {{"action": "respond", "content": "<markdown response>"}}'
    )
    json_messages = [{"role": "system", "content": json_system}] + messages[1:]

    if _HAS_RG_LLM and _llm_client:
        try:
            response = await _llm_client.complete(LLMRequest(
                messages=json_messages, provider="groq",
                temperature=temperature, max_tokens=4096,
                response_format={"type": "json_object"},
            ))
            usage = response.usage
            content_str = response.content or ""
        except Exception as e:
            return {"error": f"JSON-mode LLM call failed: {e}"}
    else:
        try:
            resp = await client.post(
                GROQ_API_URL, json={
                    "model": PROVIDER_MODELS.get("groq", "llama-3.3-70b-versatile"),
                    "messages": json_messages, "temperature": temperature,
                    "max_tokens": 4096, "response_format": {"type": "json_object"},
                },
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=90.0,
            )
            if resp.status_code != 200:
                return {"error": f"JSON-mode LLM error {resp.status_code}: {resp.text[:400]}"}
            data = resp.json()
            content_str = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
        except Exception as e:
            return {"error": f"JSON-mode LLM call failed: {e}"}

    parsed = None
    try:
        parsed = json.loads(content_str)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content_str, flags=re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    if not parsed:
        return {"text": content_str or "No response.", "tool_calls": [], "usage": usage, "json_mode": True}
    action = parsed.get("action", "respond")
    if action == "tool_call":
        tool_name = parsed.get("tool", "")
        tool_args = parsed.get("args", {})
        return {
            "text": parsed.get("reasoning", ""),
            "tool_calls": [{"id": f"json_{tool_name}", "name": tool_name, "arguments": json.dumps(tool_args)}],
            "usage": usage, "json_mode": True,
        }
    else:
        return {"text": parsed.get("content", content_str), "tool_calls": [], "usage": usage, "json_mode": True}


async def call_llm_with_tools(
    client: httpx.AsyncClient, provider: str, model: str, api_key: str,
    messages: list, tools: list, temperature: float = 0.3,
) -> dict:
    """Call LLM with native tool calling. Returns unified result dict."""

    if provider in ("openai", "groq"):
        url = PROVIDER_URLS.get(provider, GROQ_API_URL)
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": 4096}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        resp = await client.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=90.0,
        )
        if resp.status_code != 200:
            return {"error": f"LLM error {resp.status_code}: {resp.text[:400]}"}
        data = resp.json()
        msg = data.get("choices", [{}])[0].get("message", {})
        text = msg.get("content") or ""
        raw_tool_calls = msg.get("tool_calls") or []
        tool_calls = []
        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            tool_calls.append({"id": tc.get("id", f"call_{len(tool_calls)}"), "name": fn.get("name", ""), "arguments": fn.get("arguments", "{}")})
        return {"text": text, "tool_calls": tool_calls, "usage": data.get("usage", {}), "raw_message": msg}

    elif provider == "anthropic":
        system_parts = []
        non_system = []
        for m in messages:
            if m["role"] == "system":
                c = m.get("content", "")
                system_parts.append(c if isinstance(c, str) else str(c))
            elif m.get("role") == "tool":
                tc_id = m.get("tool_call_id", "unknown")
                non_system.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": tc_id, "content": str(m.get("content", ""))}]})
            else:
                role = m.get("role", "user")
                content = m.get("content")
                if role == "assistant":
                    tc = m.get("tool_calls")
                    if isinstance(content, list):
                        valid_blocks = [blk for blk in content if isinstance(blk, dict) and blk.get("type") in ("text", "tool_use")]
                        content = valid_blocks if valid_blocks else str(content)
                    elif content is None or content == "":
                        if tc:
                            blocks = []
                            for t in tc:
                                fn = t.get("function", t) if isinstance(t, dict) else {}
                                try:
                                    inp = json.loads(fn.get("arguments", "{}"))
                                except (json.JSONDecodeError, TypeError):
                                    inp = {}
                                blocks.append({"type": "tool_use", "id": t.get("id", f"call_{len(blocks)}"), "name": fn.get("name", t.get("name", "unknown")), "input": inp})
                            content = blocks if blocks else "..."
                        else:
                            content = "..."
                    else:
                        content = str(content)
                else:
                    if isinstance(content, list):
                        pass
                    elif content is None:
                        content = ""
                    else:
                        content = str(content)
                non_system.append({"role": role, "content": content})

        # Merge consecutive same-role messages
        merged = []
        for msg in non_system:
            if merged and merged[-1]["role"] == msg["role"]:
                prev_c = merged[-1]["content"]
                cur_c = msg["content"]
                if isinstance(prev_c, str) and isinstance(cur_c, str):
                    merged[-1]["content"] = prev_c + "\n" + cur_c
                elif isinstance(prev_c, list) and isinstance(cur_c, list):
                    merged[-1]["content"] = prev_c + cur_c
                elif isinstance(prev_c, str) and isinstance(cur_c, list):
                    merged[-1]["content"] = [{"type": "text", "text": prev_c}] + cur_c
                elif isinstance(prev_c, list) and isinstance(cur_c, str):
                    merged[-1]["content"] = prev_c + [{"type": "text", "text": cur_c}]
            else:
                merged.append(msg)
        non_system = merged

        if non_system and non_system[0]["role"] != "user":
            non_system.insert(0, {"role": "user", "content": "Continue."})

        anthropic_tools = build_anthropic_tools(tools) if tools else []
        payload = {"model": model, "max_tokens": 4096, "temperature": temperature, "messages": non_system}
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        resp = await client.post(
            ANTHROPIC_API_URL, json=payload,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            timeout=90.0,
        )
        if resp.status_code != 200:
            return {"error": f"Anthropic error {resp.status_code}: {resp.text[:400]}"}
        data = resp.json()
        text = ""
        tool_calls = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({"id": block.get("id", f"call_{len(tool_calls)}"), "name": block.get("name", ""), "arguments": json.dumps(block.get("input", {}))})
        return {"text": text, "tool_calls": tool_calls, "usage": data.get("usage", {})}

    elif provider == "gemini":
        url = f"{GEMINI_API_URL}/models/{model}:generateContent?key={api_key}"
        contents = []
        system_text = ""
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(b.get("text", str(b)) for b in content if isinstance(b, dict))
            elif content is None:
                content = ""
            else:
                content = str(content)
            if role == "system":
                system_text += content + "\n"
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            elif role == "tool":
                contents.append({"role": "function", "parts": [{"functionResponse": {"name": m.get("name", m.get("tool_call_id", "unknown")), "response": {"result": content[:4000]}}}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})

        gemini_tools = []
        if tools:
            func_decls = []
            for t in tools:
                fn = t.get("function", {})
                params = fn.get("parameters", {})
                if not params.get("properties"):
                    params = {"type": "object", "properties": {"query": {"type": "string", "description": "input"}}}
                func_decls.append({"name": fn.get("name", ""), "description": fn.get("description", "")[:200], "parameters": params})
            gemini_tools = [{"function_declarations": func_decls}]

        payload = {"contents": contents, "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096}}
        if system_text.strip():
            payload["systemInstruction"] = {"parts": [{"text": system_text.strip()}]}
        if gemini_tools:
            payload["tools"] = gemini_tools

        resp = await client.post(url, json=payload, timeout=90.0)
        if resp.status_code != 200:
            return {"error": f"Gemini error {resp.status_code}: {resp.text[:400]}"}
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return {"error": "Gemini returned no candidates"}
        parts = candidates[0].get("content", {}).get("parts", [])
        text = ""
        tool_calls = []
        for part in parts:
            if "text" in part:
                text += part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({"id": f"gemini_call_{len(tool_calls)}", "name": fc.get("name", ""), "arguments": json.dumps(fc.get("args", {}))})
        usage = data.get("usageMetadata", {})
        return {"text": text, "tool_calls": tool_calls, "usage": {"input_tokens": usage.get("promptTokenCount", 0), "output_tokens": usage.get("candidatesTokenCount", 0), "total_tokens": usage.get("totalTokenCount", 0)}}

    return {"error": f"Unsupported provider: {provider}"}


def build_tool_result_messages(provider: str, tool_call_id: str, tool_name: str,
                                result_str: str, assistant_msg: dict = None) -> list:
    """Build the messages to append after a tool call for the given provider."""
    if provider == "anthropic":
        return [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_call_id, "content": result_str}]}]
    elif provider == "gemini":
        return [{"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result_str}]
    else:
        return [{"role": "tool", "tool_call_id": tool_call_id, "content": result_str}]
