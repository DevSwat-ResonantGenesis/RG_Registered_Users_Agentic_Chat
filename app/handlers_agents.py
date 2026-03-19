"""
Agent Engine handlers — proxy to agent_engine_service.
Each handler: async def handler(args: dict, ctx: dict) -> dict
"""

import httpx
import logging
from typing import Dict, Any

from .config import AGENT_ENGINE_URL

logger = logging.getLogger(__name__)


def _agent_headers(ctx: dict) -> dict:
    return {
        "x-user-id": ctx.get("user_id", ""),
        "x-user-role": ctx.get("user_role", "user"),
        "x-is-superuser": "true" if ctx.get("is_superuser") else "false",
        "x-unlimited-credits": "true" if ctx.get("unlimited_credits") else "false",
    }


async def _custom_agents_list(args: dict, ctx: dict) -> dict:
    headers = _agent_headers(ctx)
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers, params={"limit": 50})
            if resp.status_code != 200:
                return {"error": f"Agents list error {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            agents = data if isinstance(data, list) else data.get("agents", data.get("items", []))
            return {
                "agents": [{"id": a.get("id"), "name": a.get("name"), "status": a.get("status"), "goal": (a.get("goal") or "")[:100]} for a in agents[:20]],
                "count": len(agents),
            }
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_create(args: dict, ctx: dict) -> dict:
    name = args.get("name", "").strip()
    goal = args.get("goal", "").strip()
    if not name or not goal:
        return {"error": "Both 'name' and 'goal' are required"}
    tools_str = args.get("tools", "")
    tools = [t.strip() for t in tools_str.split(",") if t.strip()] if tools_str else ["web_search", "memory.read"]
    headers = _agent_headers(ctx)
    payload = {"name": name, "goal": goal, "tools": tools, "model": "groq/llama-3.3-70b-versatile"}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(f"{AGENT_ENGINE_URL}/agents/", json=payload, headers=headers)
            if resp.status_code not in (200, 201):
                return {"error": f"Create agent error {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            return {"success": True, "agent_id": data.get("id"), "name": data.get("name"), "status": data.get("status"), "panel_url": f"/agents?agent={data.get('id')}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_start(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id") or args.get("agent_name", "")
    goal = args.get("goal") or args.get("message") or "Execute your configured task autonomously"
    if not agent_id:
        return {"error": "Provide agent_id or agent_name"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user"), "x-org-id": ctx.get("org_id", "")}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.post(f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions", json={"goal": goal, "context": {}}, headers=headers)
            if resp.status_code in (200, 201):
                data = resp.json()
                return {"success": True, "message": f"Agent {agent_id} started", "session": data}
            return {"error": f"Start error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_stop(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id") or args.get("agent_name", "")
    session_id = args.get("session_id", "")
    if not agent_id and not session_id:
        return {"error": "Provide agent_id, agent_name, or session_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            if session_id:
                resp = await client.post(f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}/cancel", headers=headers)
                if resp.status_code == 200:
                    return {"success": True, "message": f"Session {session_id} cancelled"}
                return {"error": f"Cancel error {resp.status_code}: {resp.text[:300]}"}
            else:
                resp = await client.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions", headers=headers)
                if resp.status_code != 200:
                    return {"error": f"Could not get sessions: {resp.status_code}: {resp.text[:300]}"}
                sessions = resp.json() if isinstance(resp.json(), list) else resp.json().get("sessions", resp.json().get("items", []))
                cancelled = []
                for s in sessions:
                    if s.get("status") in ("running", "pending"):
                        sid = s.get("id")
                        cr = await client.post(f"{AGENT_ENGINE_URL}/agents/sessions/{sid}/cancel", headers=headers)
                        if cr.status_code == 200:
                            cancelled.append(sid)
                if cancelled:
                    return {"success": True, "message": f"Cancelled {len(cancelled)} session(s)", "cancelled_sessions": cancelled}
                return {"info": "No running sessions found for this agent"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_delete(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id") or args.get("agent_name", "")
    if not agent_id:
        return {"error": "Provide agent_id or agent_name"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.delete(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers=headers)
            if resp.status_code not in (200, 204):
                return {"error": f"Delete error {resp.status_code}: {resp.text[:300]}"}
            return {"success": True, "message": f"Agent {agent_id} deleted"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_status(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id") or args.get("agent_name", "")
    if not agent_id:
        return {"error": "Provide agent_id or agent_name"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers=headers)
            if resp.status_code != 200:
                return {"error": f"Status error {resp.status_code}: {resp.text[:300]}"}
            return resp.json()
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_sessions(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id") or args.get("agent_name", "")
    status_filter = args.get("status", "")
    limit = int(args.get("limit", 20))
    if not agent_id:
        return {"error": "Provide agent_id or agent_name"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            params = {"limit": limit}
            if status_filter:
                params["status_filter"] = status_filter
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions", params=params, headers=headers)
            if resp.status_code != 200:
                return {"error": f"Sessions error {resp.status_code}: {resp.text[:300]}"}
            return {"sessions": resp.json()}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_session_steps(args: dict, ctx: dict) -> dict:
    session_id = args.get("session_id", "")
    if not session_id:
        return {"error": "Provide session_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}/steps", headers=headers)
            if resp.status_code != 200:
                return {"error": f"Steps error {resp.status_code}: {resp.text[:300]}"}
            return {"steps": resp.json()}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_session_trace(args: dict, ctx: dict) -> dict:
    session_id = args.get("session_id", "")
    if not session_id:
        return {"error": "Provide session_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}/trace", headers=headers)
            if resp.status_code != 200:
                return {"error": f"Trace error {resp.status_code}: {resp.text[:300]}"}
            return resp.json()
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_metrics(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id") or args.get("agent_name", "")
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            if agent_id:
                resp = await client.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}/metrics", headers=headers)
            else:
                resp = await client.get(f"{AGENT_ENGINE_URL}/agents/metrics/summary", headers=headers)
            if resp.status_code != 200:
                return {"error": f"Metrics error {resp.status_code}: {resp.text[:300]}"}
            return resp.json()
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_session_detail(args: dict, ctx: dict) -> dict:
    session_id = args.get("session_id", "")
    if not session_id:
        return {"error": "Provide session_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}", headers=headers)
            if resp.status_code != 200:
                return {"error": f"Session detail error {resp.status_code}: {resp.text[:300]}"}
            return resp.json()
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_session_cancel(args: dict, ctx: dict) -> dict:
    session_id = args.get("session_id", "")
    if not session_id:
        return {"error": "Provide session_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(f"{AGENT_ENGINE_URL}/agents/sessions/{session_id}/cancel", headers=headers)
            if resp.status_code == 200:
                return {"success": True, "message": f"Session {session_id} cancelled", "data": resp.json()}
            return {"error": f"Cancel error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_update(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id", "")
    if not agent_id:
        return {"error": "Provide agent_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user"), "Content-Type": "application/json"}
    patch_body = {}
    for key in ("name", "description", "goal", "system_prompt", "model", "tools",
                "allowed_actions", "blocked_actions", "temperature", "max_tokens", "is_active"):
        if key in args:
            patch_body[key] = args[key]
    if not patch_body:
        return {"error": "Provide at least one field to update"}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.patch(f"{AGENT_ENGINE_URL}/agents/{agent_id}", json=patch_body, headers=headers)
            if resp.status_code == 200:
                return {"success": True, "agent": resp.json()}
            return {"error": f"Update error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_available_tools(args: dict, ctx: dict) -> dict:
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/available-tools", headers=headers)
            if resp.status_code != 200:
                return {"error": f"Tools error {resp.status_code}: {resp.text[:300]}"}
            return {"tools": resp.json()}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_templates(args: dict, ctx: dict) -> dict:
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/templates", headers=headers)
            if resp.status_code != 200:
                return {"error": f"Templates error {resp.status_code}: {resp.text[:300]}"}
            return {"templates": resp.json()}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agents_versions(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id", "")
    if not agent_id:
        return {"error": "Provide agent_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}/versions", headers=headers)
            if resp.status_code != 200:
                return {"error": f"Versions error {resp.status_code}: {resp.text[:300]}"}
            return resp.json()
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_agent_snapshot(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id", "")
    agent_name = args.get("agent_name", "")
    user_id = ctx.get("user_id", "anonymous")
    headers = {"x-user-id": user_id, "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if not agent_id and agent_name:
                resp = await client.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers)
                if resp.status_code == 200:
                    agents = resp.json() if isinstance(resp.json(), list) else resp.json().get("agents", [])
                    for a in agents:
                        if agent_name.lower() in (a.get("name") or "").lower():
                            agent_id = a.get("id", "")
                            break
                if not agent_id:
                    return {"error": f"No agent found matching '{agent_name}'"}
            resp = await client.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}", headers=headers)
            if resp.status_code != 200:
                return {"error": f"Agent not found: {resp.status_code}"}
            agent = resp.json()
            sess_resp = await client.get(f"{AGENT_ENGINE_URL}/agents/{agent_id}/sessions?limit=5", headers=headers)
            sessions = []
            if sess_resp.status_code == 200:
                sess_data = sess_resp.json()
                raw = sess_data if isinstance(sess_data, list) else sess_data.get("sessions", [])
                for s in raw[:5]:
                    sessions.append({"id": s.get("id", ""), "status": s.get("status", ""), "loops": s.get("loop_count", 0), "goal": (s.get("goal") or "")[:100], "created_at": s.get("created_at", "")})
            return {
                "_type": "agent_snapshot", "id": agent.get("id", ""), "name": agent.get("name", ""),
                "status": agent.get("status", ""), "goal": agent.get("goal", ""),
                "instructions": (agent.get("instructions") or "")[:500], "model": agent.get("model", ""),
                "tools": agent.get("tools", []), "schedule": agent.get("schedule", agent.get("trigger", None)),
                "created_at": agent.get("created_at", ""), "updated_at": agent.get("updated_at", ""),
                "recent_runs": sessions, "total_runs": len(sessions),
            }
    except Exception as e:
        return {"error": f"Agent snapshot failed: {str(e)[:300]}"}


async def _custom_run_agent(args: dict, ctx: dict) -> dict:
    agent_id = args.get("agent_id", "")
    agent_name = args.get("agent_name", "")
    goal = args.get("goal", "")
    user_id = ctx.get("user_id", "anonymous")
    headers = {"x-user-id": user_id, "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if not agent_id and agent_name:
                resp = await client.get(f"{AGENT_ENGINE_URL}/agents/", headers=headers)
                if resp.status_code == 200:
                    agents = resp.json() if isinstance(resp.json(), list) else resp.json().get("agents", [])
                    for a in agents:
                        if agent_name.lower() in (a.get("name") or "").lower():
                            agent_id = a.get("id", "")
                            break
                if not agent_id:
                    return {"error": f"No agent found matching '{agent_name}'"}
            payload = {}
            if goal:
                payload["goal"] = goal
            resp = await client.post(f"{AGENT_ENGINE_URL}/agents/{agent_id}/start", json=payload, headers=headers)
            if resp.status_code not in (200, 201, 202):
                return {"error": f"Failed to start agent: {resp.status_code} — {resp.text[:200]}"}
            data = resp.json()
            return {"_type": "agent_run_started", "agent_id": agent_id, "session_id": data.get("session_id", data.get("id", "")), "status": data.get("status", "started"), "message": "Agent started successfully."}
    except Exception as e:
        return {"error": f"Run agent failed: {str(e)[:300]}"}
