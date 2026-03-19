"""
Conversation Persistence
========================
Database layer for agentic chat conversations and messages.
Uses the same PostgreSQL database as agent_engine_service.
"""

import json
import logging
from typing import Dict, Any, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from .config import DATABASE_URL

logger = logging.getLogger(__name__)

_db_engine = create_async_engine(DATABASE_URL, echo=False, poolclass=NullPool)

_DDL_DONE = False


async def _ensure_tables():
    """Create agentic chat tables if they don't exist (runs once)."""
    global _DDL_DONE
    if _DDL_DONE:
        return
    try:
        async with _db_engine.begin() as conn:
            await conn.execute(sa_text("""
                CREATE TABLE IF NOT EXISTS agentic_chat_conversations (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL,
                    title TEXT DEFAULT 'New conversation',
                    model TEXT DEFAULT 'llama-3.3-70b-versatile',
                    message_count INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await conn.execute(sa_text("""
                CREATE INDEX IF NOT EXISTS idx_acc_user_id ON agentic_chat_conversations(user_id)
            """))
            await conn.execute(sa_text("""
                CREATE INDEX IF NOT EXISTS idx_acc_updated ON agentic_chat_conversations(updated_at DESC)
            """))
            await conn.execute(sa_text("""
                CREATE TABLE IF NOT EXISTS agentic_chat_messages (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    conversation_id UUID NOT NULL REFERENCES agentic_chat_conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls JSONB DEFAULT '[]'::jsonb,
                    tool_results JSONB DEFAULT '[]'::jsonb,
                    tokens_used INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await conn.execute(sa_text("""
                CREATE INDEX IF NOT EXISTS idx_acm_conv_id ON agentic_chat_messages(conversation_id)
            """))
            # Dynamic custom tools created by the AI assistant at runtime
            await conn.execute(sa_text("""
                CREATE TABLE IF NOT EXISTS agentic_custom_tools (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT DEFAULT 'custom',
                    parameters JSONB DEFAULT '{}'::jsonb,
                    http_method TEXT DEFAULT 'GET',
                    endpoint_url TEXT NOT NULL,
                    request_body_template JSONB DEFAULT NULL,
                    headers_template JSONB DEFAULT '{}'::jsonb,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, tool_name)
                )
            """))
            await conn.execute(sa_text("""
                CREATE INDEX IF NOT EXISTS idx_act_user_id ON agentic_custom_tools(user_id)
            """))
        _DDL_DONE = True
        logger.info("[PERSISTENCE] DB tables ready")
    except Exception as e:
        logger.warning(f"[PERSISTENCE] DDL error (non-fatal): {e}")
        _DDL_DONE = True  # Don't retry on every request


async def list_conversations(user_id: str) -> dict:
    """List user's conversations."""
    await _ensure_tables()
    if not user_id or user_id == "anonymous":
        return {"conversations": [], "error": "Not authenticated"}
    try:
        async with _db_engine.begin() as conn:
            result = await conn.execute(sa_text("""
                SELECT id, title, model, message_count, created_at, updated_at
                FROM agentic_chat_conversations
                WHERE user_id = :uid
                ORDER BY updated_at DESC
                LIMIT 50
            """), {"uid": user_id})
            rows = result.fetchall()
            return {"conversations": [
                {
                    "id": str(r[0]),
                    "title": r[1],
                    "model": r[2],
                    "message_count": r[3],
                    "created_at": r[4].isoformat() if r[4] else None,
                    "updated_at": r[5].isoformat() if r[5] else None,
                }
                for r in rows
            ]}
    except Exception as e:
        return {"conversations": [], "error": str(e)[:200]}


async def create_conversation(user_id: str, title: str = "New conversation") -> dict:
    """Create a new conversation."""
    await _ensure_tables()
    if not user_id or user_id == "anonymous":
        return {"error": "Not authenticated"}
    try:
        async with _db_engine.begin() as conn:
            result = await conn.execute(sa_text("""
                INSERT INTO agentic_chat_conversations (user_id, title)
                VALUES (:uid, :title)
                RETURNING id, title, created_at
            """), {"uid": user_id, "title": title})
            row = result.fetchone()
            return {"id": str(row[0]), "title": row[1], "created_at": row[2].isoformat()}
    except Exception as e:
        return {"error": str(e)[:200]}


async def load_conversation(conv_id: str, user_id: str) -> dict:
    """Load a conversation with all messages."""
    await _ensure_tables()
    try:
        async with _db_engine.begin() as conn:
            conv = await conn.execute(sa_text("""
                SELECT id, title, model, message_count, created_at
                FROM agentic_chat_conversations
                WHERE id = :cid AND user_id = :uid
            """), {"cid": conv_id, "uid": user_id})
            conv_row = conv.fetchone()
            if not conv_row:
                return {"error": "Conversation not found"}

            msgs = await conn.execute(sa_text("""
                SELECT id, role, content, tool_calls, tool_results, tokens_used, created_at
                FROM agentic_chat_messages
                WHERE conversation_id = :cid
                ORDER BY created_at ASC
            """), {"cid": conv_id})
            rows = msgs.fetchall()
            return {
                "conversation": {
                    "id": str(conv_row[0]),
                    "title": conv_row[1],
                    "model": conv_row[2],
                    "message_count": conv_row[3],
                    "created_at": conv_row[4].isoformat() if conv_row[4] else None,
                },
                "messages": [
                    {
                        "id": str(r[0]),
                        "role": r[1],
                        "content": r[2],
                        "tool_calls": r[3] or [],
                        "tool_results": r[4] or [],
                        "tokens_used": r[5] or 0,
                        "created_at": r[6].isoformat() if r[6] else None,
                    }
                    for r in rows
                ],
            }
    except Exception as e:
        return {"error": str(e)[:200]}


async def delete_conversation(conv_id: str, user_id: str) -> dict:
    """Delete a conversation."""
    await _ensure_tables()
    try:
        async with _db_engine.begin() as conn:
            await conn.execute(sa_text("""
                DELETE FROM agentic_chat_conversations
                WHERE id = :cid AND user_id = :uid
            """), {"cid": conv_id, "uid": user_id})
            return {"deleted": True}
    except Exception as e:
        return {"error": str(e)[:200]}


async def save_message(conv_id: str, user_id: str, role: str, content: str,
                       tool_calls: list = None, tool_results: list = None, tokens: int = 0):
    """Save a message to the DB (fire-and-forget)."""
    try:
        await _ensure_tables()
        async with _db_engine.begin() as conn:
            await conn.execute(sa_text("""
                INSERT INTO agentic_chat_messages (conversation_id, role, content, tool_calls, tool_results, tokens_used)
                VALUES (:cid, :role, :content, CAST(:tc AS jsonb), CAST(:tr AS jsonb), :tokens)
            """), {
                "cid": conv_id, "role": role, "content": content,
                "tc": json.dumps(tool_calls or []),
                "tr": json.dumps(tool_results or []),
                "tokens": tokens,
            })
            await conn.execute(sa_text("""
                UPDATE agentic_chat_conversations
                SET message_count = message_count + 1, updated_at = NOW(),
                    title = CASE WHEN message_count = 0 AND :role = 'user'
                                 THEN LEFT(:content, 80) ELSE title END
                WHERE id = :cid
            """), {"cid": conv_id, "role": role, "content": content})
    except Exception as e:
        logger.warning(f"[SAVE_MSG] Error: {e}")


async def auto_create_conversation(user_id: str, first_message: str) -> str:
    """Auto-create a conversation and return its ID."""
    try:
        await _ensure_tables()
        async with _db_engine.begin() as conn:
            result = await conn.execute(sa_text("""
                INSERT INTO agentic_chat_conversations (user_id, title)
                VALUES (:uid, :title)
                RETURNING id
            """), {"uid": user_id, "title": first_message[:80]})
            row = result.fetchone()
            return str(row[0])
    except Exception as e:
        logger.warning(f"[AUTO_CREATE_CONV] Error: {e}")
        return ""


# ── Custom tools DB operations ──

async def load_user_custom_tools(user_id: str) -> Dict[str, Any]:
    """Load user's dynamic custom tools from DB."""
    if not user_id or user_id == "anonymous":
        return {}
    await _ensure_tables()
    try:
        async with _db_engine.begin() as conn:
            result = await conn.execute(sa_text("""
                SELECT tool_name, description, parameters, http_method,
                       endpoint_url, request_body_template, headers_template
                FROM agentic_custom_tools
                WHERE user_id = :uid AND is_active = TRUE
            """), {"uid": user_id})
            rows = result.fetchall()
            tools = {}
            for r in rows:
                params = r[2] if isinstance(r[2], dict) else {}
                tools[r[0]] = {
                    "desc": r[1],
                    "params": params,
                    "method": r[3],
                    "url": r[4],
                    "body_template": r[5],
                    "headers_template": r[6] if isinstance(r[6], dict) else {},
                }
            return tools
    except Exception as e:
        logger.warning(f"[CUSTOM_TOOLS] Load error: {e}")
        return {}


async def create_custom_tool(user_id: str, tool_name: str, description: str,
                             parameters: dict, http_method: str, endpoint_url: str,
                             request_body_template: dict = None,
                             headers_template: dict = None) -> dict:
    """Create a new custom tool for the user."""
    await _ensure_tables()
    try:
        async with _db_engine.begin() as conn:
            await conn.execute(sa_text("""
                INSERT INTO agentic_custom_tools (user_id, tool_name, description, parameters,
                    http_method, endpoint_url, request_body_template, headers_template)
                VALUES (:uid, :name, :desc, CAST(:params AS jsonb), :method, :url,
                        CAST(:body AS jsonb), CAST(:headers AS jsonb))
                ON CONFLICT (user_id, tool_name) DO UPDATE SET
                    description = EXCLUDED.description,
                    parameters = EXCLUDED.parameters,
                    http_method = EXCLUDED.http_method,
                    endpoint_url = EXCLUDED.endpoint_url,
                    request_body_template = EXCLUDED.request_body_template,
                    headers_template = EXCLUDED.headers_template,
                    updated_at = NOW()
            """), {
                "uid": user_id, "name": tool_name, "desc": description,
                "params": json.dumps(parameters),
                "method": http_method, "url": endpoint_url,
                "body": json.dumps(request_body_template) if request_body_template else None,
                "headers": json.dumps(headers_template or {}),
            })
            return {"success": True, "tool_name": tool_name}
    except Exception as e:
        return {"error": str(e)[:300]}


async def delete_custom_tool(user_id: str, tool_name: str) -> dict:
    """Delete a custom tool."""
    await _ensure_tables()
    try:
        async with _db_engine.begin() as conn:
            result = await conn.execute(sa_text("""
                DELETE FROM agentic_custom_tools
                WHERE user_id = :uid AND tool_name = :name
            """), {"uid": user_id, "name": tool_name})
            return {"deleted": True, "tool_name": tool_name}
    except Exception as e:
        return {"error": str(e)[:300]}


async def list_custom_tools(user_id: str) -> dict:
    """List user's custom tools."""
    tools = await load_user_custom_tools(user_id)
    return {
        "tools": [
            {"name": k, "description": v["desc"], "method": v["method"], "url": v["url"]}
            for k, v in tools.items()
        ],
        "count": len(tools),
    }


async def update_custom_tool(user_id: str, tool_name: str, updates: dict) -> dict:
    """Update a custom tool."""
    await _ensure_tables()
    try:
        set_parts = []
        params = {"uid": user_id, "name": tool_name}
        if "description" in updates:
            set_parts.append("description = :desc")
            params["desc"] = updates["description"]
        if "parameters" in updates:
            set_parts.append("parameters = CAST(:params AS jsonb)")
            params["params"] = json.dumps(updates["parameters"])
        if "http_method" in updates:
            set_parts.append("http_method = :method")
            params["method"] = updates["http_method"]
        if "endpoint_url" in updates:
            set_parts.append("endpoint_url = :url")
            params["url"] = updates["endpoint_url"]
        if not set_parts:
            return {"error": "No fields to update"}
        set_parts.append("updated_at = NOW()")
        set_clause = ", ".join(set_parts)
        async with _db_engine.begin() as conn:
            await conn.execute(sa_text(f"""
                UPDATE agentic_custom_tools SET {set_clause}
                WHERE user_id = :uid AND tool_name = :name
            """), params)
            return {"updated": True, "tool_name": tool_name}
    except Exception as e:
        return {"error": str(e)[:300]}
