"""
Orchestrator tool handlers — workspace snapshot, scheduling, run snapshot,
session log, present options, custom tool CRUD.
Each handler: async def handler(args: dict, ctx: dict) -> dict
"""

import json
import time
import logging
from typing import Dict, Any

import httpx

from .config import AGENT_ENGINE_URL
from .handlers_agents import _agent_headers

logger = logging.getLogger(__name__)


async def _custom_present_options(args: dict, ctx: dict) -> dict:
    title = (args.get("title") or args.get("question") or "").strip()
    options = args.get("options", [])
    if not title:
        return {"error": "title/question is required"}
    if not options or not isinstance(options, list):
        return {"error": "options must be a non-empty list of choices"}
    normalized = []
    for i, opt in enumerate(options):
        if isinstance(opt, str):
            normalized.append({"label": opt, "value": opt, "description": ""})
        elif isinstance(opt, dict):
            normalized.append({"label": opt.get("label", opt.get("text", f"Option {i+1}")), "value": opt.get("value", opt.get("label", opt.get("text", f"option_{i+1}"))), "description": opt.get("description", opt.get("desc", "")), "icon": opt.get("icon", "")})
        else:
            normalized.append({"label": str(opt), "value": str(opt), "description": ""})
    return {"_type": "present_options", "title": title, "options": normalized[:8], "allow_custom": args.get("allow_custom", True)}


async def _custom_workspace_snapshot(args: dict, ctx: dict) -> dict:
    headers = _agent_headers(ctx)
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers, params={"limit": 50})
            if resp.status_code != 200:
                return {"error": f"Failed to fetch agents: {resp.status_code}"}
            data = resp.json()
            agents = data if isinstance(data, list) else data.get("agents", data.get("items", []))
            agent_summaries = []
            active_count = 0
            total_sessions = 0
            for a in agents[:30]:
                agent_id = a.get("id", "")
                is_active = a.get("is_active") or a.get("status") == "active"
                if is_active:
                    active_count += 1
                summary = {"id": agent_id, "name": a.get("name", "Unnamed"), "goal": (a.get("goal") or "")[:120], "status": "active" if is_active else a.get("status", "inactive"), "model": a.get("model", ""), "tools_count": len(a.get("tools", [])), "created": a.get("created_at", "")[:10]}
                try:
                    sess_resp = await client.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions", headers=headers, params={"limit": 3})
                    if sess_resp.status_code == 200:
                        sessions = sess_resp.json() if isinstance(sess_resp.json(), list) else sess_resp.json().get("sessions", sess_resp.json().get("items", []))
                        total_sessions += len(sessions)
                        summary["recent_runs"] = [{"id": s.get("id", "")[:8], "status": s.get("status", ""), "goal": (s.get("goal") or "")[:60], "loops": s.get("loop_count", 0)} for s in sessions[:3]]
                except Exception:
                    pass
                agent_summaries.append(summary)
            return {"_type": "workspace_snapshot", "agents": agent_summaries, "stats": {"total_agents": len(agents), "active_agents": active_count, "total_recent_sessions": total_sessions}, "user_id": ctx.get("user_id", "")}
    except Exception as e:
        return {"error": f"Workspace snapshot failed: {str(e)[:300]}"}


async def _custom_schedule_agent(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id", "").strip()
    agent_name = args.get("agent_name", "").strip()
    schedule = args.get("schedule", "").strip()
    goal = args.get("goal", "").strip()
    if not agent_id and not agent_name:
        return {"error": "Provide agent_id or agent_name"}
    if not schedule:
        return {"error": "schedule is required — e.g. 'every 1h', 'daily', 'cron: 0 */2 * * *'"}
    cron_expr = ""
    schedule_lower = schedule.lower().strip()
    if schedule_lower.startswith("cron:"):
        cron_expr = schedule_lower.replace("cron:", "").strip()
    elif "every 1h" in schedule_lower or "hourly" in schedule_lower or "every hour" in schedule_lower:
        cron_expr = "0 * * * *"
    elif "every 2h" in schedule_lower:
        cron_expr = "0 */2 * * *"
    elif "every 4h" in schedule_lower:
        cron_expr = "0 */4 * * *"
    elif "every 6h" in schedule_lower:
        cron_expr = "0 */6 * * *"
    elif "every 12h" in schedule_lower:
        cron_expr = "0 */12 * * *"
    elif "daily" in schedule_lower or "every day" in schedule_lower:
        cron_expr = "0 9 * * *"
    elif "weekly" in schedule_lower or "every week" in schedule_lower:
        cron_expr = "0 9 * * 1"
    elif "every 30m" in schedule_lower or "every 30 min" in schedule_lower:
        cron_expr = "*/30 * * * *"
    elif "every 15m" in schedule_lower or "every 15 min" in schedule_lower:
        cron_expr = "*/15 * * * *"
    else:
        return {"error": f"Could not parse schedule '{schedule}'."}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    if not agent_id and agent_name:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers, params={"limit": 50})
                if resp.status_code == 200:
                    data = resp.json()
                    agents = data if isinstance(data, list) else data.get("agents", data.get("items", []))
                    for a in agents:
                        if (a.get("name") or "").lower() == agent_name.lower():
                            agent_id = a.get("id", "")
                            break
                if not agent_id:
                    return {"error": f"Agent '{agent_name}' not found"}
        except Exception as e:
            return {"error": f"Failed to resolve agent name: {str(e)[:200]}"}
    trigger_payload = {"name": goal[:80] if goal else f"Schedule: {schedule}", "trigger_type": "cron", "cron_expression": cron_expr, "goal": goal or f"Run agent on schedule: {schedule}", "enabled": True}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(f"{AGENT_ENGINE_URL}/agents/{agent_id}/triggers", json=trigger_payload, headers=headers)
            if resp.status_code in (200, 201):
                return {"success": True, "agent_id": agent_id, "schedule": schedule, "cron": cron_expr, "message": f"Agent scheduled: {schedule} (cron: {cron_expr})"}
            elif resp.status_code == 404:
                patch_resp = await client.patch(f"{AGENT_ENGINE_URL}/agents/{agent_id}", json={"description": f"[SCHEDULED: {cron_expr}] {goal or ''}".strip()}, headers=headers)
                return {"success": True, "agent_id": agent_id, "schedule": schedule, "cron": cron_expr, "message": f"Schedule saved to agent config."}
            return {"error": f"Schedule error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": f"Schedule failed: {str(e)[:300]}"}


async def _custom_run_snapshot(args: dict, ctx: dict) -> dict:
    session_id = args.get("session_id", "").strip()
    if not session_id:
        return {"error": "session_id is required"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            detail_resp = await client.get(f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}", headers=headers)
            if detail_resp.status_code != 200:
                return {"error": f"Session not found: {detail_resp.status_code}"}
            session = detail_resp.json()
            steps_resp = await client.get(f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}/steps", headers=headers)
            steps = []
            if steps_resp.status_code == 200:
                steps_data = steps_resp.json()
                raw_steps = steps_data if isinstance(steps_data, list) else steps_data.get("steps", steps_data.get("items", []))
                for s in raw_steps:
                    steps.append({"step": s.get("step_number", 0), "tool": s.get("tool_name", s.get("action", "")), "reasoning": (s.get("reasoning") or "")[:150], "output": (str(s.get("output") or s.get("result", ""))[:200]), "status": s.get("status", ""), "duration_ms": s.get("duration_ms", 0)})
            return {
                "_type": "run_snapshot", "session_id": session_id, "agent_id": session.get("agent_id", ""),
                "status": session.get("status", ""), "goal": session.get("goal", ""),
                "loops": session.get("loop_count", 0), "tokens_used": session.get("total_tokens", 0),
                "final_output": (str(session.get("final_output") or session.get("output", ""))[:500]),
                "error": session.get("error_message", ""), "started_at": session.get("created_at", ""),
                "steps": steps[:20], "total_steps": len(steps),
            }
    except Exception as e:
        return {"error": f"Run snapshot failed: {str(e)[:300]}"}


async def _custom_session_log(args: dict, ctx: dict) -> dict:
    tracker = ctx.get("_session_tracker", {})
    return {
        "_type": "session_log", "tools_called": tracker.get("tools_called", []),
        "total_tool_calls": tracker.get("total_tool_calls", 0),
        "total_loops": tracker.get("total_loops", 0),
        "total_tokens": tracker.get("total_tokens", 0),
        "elapsed_seconds": tracker.get("elapsed_seconds", 0),
        "skills_used": tracker.get("skills_used", []),
    }


# ── Dynamic Custom Tool CRUD + Execution ──

_db_engine = None
_custom_tools_cache: Dict[str, Dict[str, Any]] = {}
_custom_tools_cache_ts: Dict[str, float] = {}
CUSTOM_TOOLS_CACHE_TTL = 60


def set_db_engine(engine):
    global _db_engine
    _db_engine = engine


async def load_user_custom_tools(user_id: str) -> Dict[str, Any]:
    now = time.time()
    cached_ts = _custom_tools_cache_ts.get(user_id, 0)
    if user_id in _custom_tools_cache and (now - cached_ts) < CUSTOM_TOOLS_CACHE_TTL:
        return _custom_tools_cache[user_id]
    tools = {}
    if not _db_engine:
        return tools
    try:
        from sqlalchemy import text as sa_text
        async with _db_engine.begin() as conn:
            rows = await conn.execute(sa_text(
                "SELECT tool_name, description, category, parameters, http_method, "
                "endpoint_url, request_body_template, headers_template "
                "FROM agentic_custom_tools WHERE user_id = :uid AND is_active = TRUE"
            ), {"uid": user_id})
            for row in rows:
                tname = row[0]
                tools[tname] = {
                    "desc": row[1], "category": row[2] or "custom",
                    "params": row[3] if isinstance(row[3], dict) else {},
                    "handler": f"_dynamic_custom_tool:{tname}",
                    "_http_method": row[4] or "GET", "_endpoint_url": row[5],
                    "_request_body_template": row[6],
                    "_headers_template": row[7] if isinstance(row[7], dict) else {},
                }
    except Exception as e:
        logger.warning(f"[HANDLERS] Failed to load custom tools for {user_id}: {e}")
    _custom_tools_cache[user_id] = tools
    _custom_tools_cache_ts[user_id] = now
    return tools


def invalidate_custom_tools_cache(user_id: str):
    _custom_tools_cache.pop(user_id, None)
    _custom_tools_cache_ts.pop(user_id, None)


def _substitute_params(template: str, args: dict) -> str:
    result = template
    for k, v in args.items():
        result = result.replace(f"{{{k}}}", str(v))
    return result


async def execute_dynamic_custom_tool(tool_name: str, args: dict, ctx: dict) -> dict:
    user_id = ctx.get("user_id", "")
    user_tools = await load_user_custom_tools(user_id)
    tool_def = user_tools.get(tool_name)
    if not tool_def:
        return {"error": f"Custom tool '{tool_name}' not found"}
    method = (tool_def.get("_http_method") or "GET").upper()
    url = tool_def.get("_endpoint_url", "")
    if not url:
        return {"error": f"Tool '{tool_name}' has no endpoint URL configured"}
    url = _substitute_params(url, args)
    headers_template = tool_def.get("_headers_template") or {}
    headers = {k: _substitute_params(v, args) for k, v in headers_template.items()}
    body_template = tool_def.get("_request_body_template")
    body = None
    if body_template:
        if isinstance(body_template, dict):
            body = json.loads(_substitute_params(json.dumps(body_template), args))
        elif isinstance(body_template, str):
            body = json.loads(_substitute_params(body_template, args))
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=args)
            elif method == "POST":
                resp = await client.post(url, json=body or args, headers=headers)
            elif method == "PUT":
                resp = await client.put(url, json=body or args, headers=headers)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers)
            elif method == "PATCH":
                resp = await client.patch(url, json=body or args, headers=headers)
            else:
                return {"error": f"Unsupported HTTP method: {method}"}
            try:
                return resp.json()
            except Exception:
                return {"status_code": resp.status_code, "text": resp.text[:2000]}
    except Exception as e:
        return {"error": f"Custom tool '{tool_name}' execution failed: {str(e)[:300]}"}


async def _custom_create_tool(args: dict, ctx: dict) -> dict:
    user_id = ctx.get("user_id", "")
    if not user_id:
        return {"error": "Authentication required to create tools"}
    tool_name = (args.get("tool_name") or "").strip().lower().replace(" ", "_").replace("-", "_")
    description = (args.get("description") or "").strip()
    endpoint_url = (args.get("endpoint_url") or "").strip()
    if not tool_name:
        return {"error": "tool_name is required"}
    if not description:
        return {"error": "description is required"}
    if not endpoint_url:
        return {"error": "endpoint_url is required"}
    parameters = args.get("parameters", {})
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except Exception:
            parameters = {}
    http_method = (args.get("http_method") or "GET").upper()
    if http_method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        http_method = "GET"
    request_body = args.get("request_body")
    if isinstance(request_body, str):
        try:
            request_body = json.loads(request_body)
        except Exception:
            request_body = None
    category = (args.get("category") or "custom").strip()
    if not _db_engine:
        return {"error": "Database not configured"}
    try:
        from sqlalchemy import text as sa_text
        async with _db_engine.begin() as conn:
            await conn.execute(sa_text("""
                INSERT INTO agentic_custom_tools (user_id, tool_name, description, category,
                    parameters, http_method, endpoint_url, request_body_template)
                VALUES (:uid, :name, :desc, :cat, CAST(:params AS jsonb), :method, :url, CAST(:body AS jsonb))
                ON CONFLICT (user_id, tool_name) DO UPDATE SET
                    description = EXCLUDED.description, category = EXCLUDED.category,
                    parameters = EXCLUDED.parameters, http_method = EXCLUDED.http_method,
                    endpoint_url = EXCLUDED.endpoint_url, request_body_template = EXCLUDED.request_body_template,
                    is_active = TRUE, updated_at = NOW()
            """), {"uid": user_id, "name": tool_name, "desc": description, "cat": category, "params": json.dumps(parameters) if not isinstance(parameters, str) else parameters, "method": http_method, "url": endpoint_url, "body": json.dumps(request_body) if request_body else None})
        invalidate_custom_tools_cache(user_id)
        return {"success": True, "message": f"Tool '{tool_name}' created!", "tool": {"name": tool_name, "description": description, "category": category, "parameters": parameters, "http_method": http_method, "endpoint_url": endpoint_url}}
    except Exception as e:
        return {"error": f"Failed to create tool: {str(e)[:300]}"}


async def _custom_list_tools(args: dict, ctx: dict) -> dict:
    user_id = ctx.get("user_id", "")
    if not user_id:
        return {"error": "Authentication required"}
    if not _db_engine:
        return {"error": "Database not configured"}
    try:
        from sqlalchemy import text as sa_text
        tools = []
        async with _db_engine.begin() as conn:
            rows = await conn.execute(sa_text(
                "SELECT tool_name, description, category, parameters, http_method, "
                "endpoint_url, request_body_template, created_at, is_active "
                "FROM agentic_custom_tools WHERE user_id = :uid ORDER BY created_at DESC"
            ), {"uid": user_id})
            for row in rows:
                tools.append({"name": row[0], "description": row[1], "category": row[2], "parameters": row[3], "http_method": row[4], "endpoint_url": row[5], "request_body": row[6], "created_at": str(row[7]) if row[7] else None, "is_active": row[8]})
        return {"tools": tools, "count": len(tools)}
    except Exception as e:
        return {"error": f"Failed to list tools: {str(e)[:300]}"}


async def _custom_delete_tool(args: dict, ctx: dict) -> dict:
    user_id = ctx.get("user_id", "")
    tool_name = (args.get("tool_name") or "").strip()
    if not user_id:
        return {"error": "Authentication required"}
    if not tool_name:
        return {"error": "tool_name is required"}
    if not _db_engine:
        return {"error": "Database not configured"}
    try:
        from sqlalchemy import text as sa_text
        async with _db_engine.begin() as conn:
            result = await conn.execute(sa_text("DELETE FROM agentic_custom_tools WHERE user_id = :uid AND tool_name = :name"), {"uid": user_id, "name": tool_name})
            if result.rowcount == 0:
                return {"error": f"Tool '{tool_name}' not found"}
        invalidate_custom_tools_cache(user_id)
        return {"success": True, "message": f"Tool '{tool_name}' deleted."}
    except Exception as e:
        return {"error": f"Failed to delete tool: {str(e)[:300]}"}


async def _custom_update_tool(args: dict, ctx: dict) -> dict:
    user_id = ctx.get("user_id", "")
    tool_name = (args.get("tool_name") or "").strip()
    if not user_id:
        return {"error": "Authentication required"}
    if not tool_name:
        return {"error": "tool_name is required"}
    if not _db_engine:
        return {"error": "Database not configured"}
    updates = []
    params: Dict[str, Any] = {"uid": user_id, "name": tool_name}
    if "description" in args and args["description"]:
        updates.append("description = :desc")
        params["desc"] = args["description"]
    if "parameters" in args and args["parameters"]:
        updates.append("parameters = CAST(:params AS jsonb)")
        p = args["parameters"]
        params["params"] = json.dumps(p) if not isinstance(p, str) else p
    if "http_method" in args and args["http_method"]:
        updates.append("http_method = :method")
        params["method"] = args["http_method"].upper()
    if "endpoint_url" in args and args["endpoint_url"]:
        updates.append("endpoint_url = :url")
        params["url"] = args["endpoint_url"]
    if "request_body" in args:
        updates.append("request_body_template = CAST(:body AS jsonb)")
        rb = args["request_body"]
        params["body"] = json.dumps(rb) if not isinstance(rb, str) else rb
    if "is_active" in args:
        updates.append("is_active = :active")
        params["active"] = bool(args["is_active"])
    if not updates:
        return {"error": "Provide at least one field to update"}
    updates.append("updated_at = NOW()")
    set_clause = ", ".join(updates)
    try:
        from sqlalchemy import text as sa_text
        async with _db_engine.begin() as conn:
            result = await conn.execute(sa_text(f"UPDATE agentic_custom_tools SET {set_clause} WHERE user_id = :uid AND tool_name = :name"), params)
            if result.rowcount == 0:
                return {"error": f"Tool '{tool_name}' not found"}
        invalidate_custom_tools_cache(user_id)
        return {"success": True, "message": f"Tool '{tool_name}' updated."}
    except Exception as e:
        return {"error": f"Failed to update tool: {str(e)[:300]}"}
