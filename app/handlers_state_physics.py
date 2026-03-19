"""
State Physics handlers — proxy to state_physics_service.
Each handler: async def handler(args: dict, ctx: dict) -> dict
"""

import httpx
import logging

from .config import STATE_PHYSICS_URL

logger = logging.getLogger(__name__)


def _sp_headers(ctx: dict) -> dict:
    return {"x-user-id": ctx.get("user_id", "anonymous"), "x-org-id": ctx.get("org_id", ""), "x-user-role": ctx.get("user_role", "user")}


async def _custom_sp_state(args: dict, ctx: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{STATE_PHYSICS_URL}/api/state", headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_reset(args: dict, ctx: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/reset", headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_nodes(args: dict, ctx: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{STATE_PHYSICS_URL}/api/nodes", headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_metrics(args: dict, ctx: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{STATE_PHYSICS_URL}/api/metrics", headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_identity(args: dict, ctx: dict) -> dict:
    dsid = args.get("dsid") or args.get("id") or args.get("name", "")
    if not dsid:
        return {"error": "Provide dsid (unique identity ID)"}
    body = {"dsid": dsid, "node_type": args.get("node_type", "user"), "trust": float(args.get("trust", 0.5)), "value": float(args.get("value", 0))}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/identity", json=body, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_simulate(args: dict, ctx: dict) -> dict:
    steps = int(args.get("steps", 1))
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/simulate", json={"steps": steps}, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_galaxy(args: dict, ctx: dict) -> dict:
    body = {
        "num_users": int(args.get("num_users", 500)),
        "num_transactions": int(args.get("num_transactions", 1500)),
        "num_services": int(args.get("num_services", 10)),
        "enable_agent": bool(args.get("enable_agent", True)),
        "enable_entropy": bool(args.get("enable_entropy", True)),
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/galaxy", json=body, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_demo(args: dict, ctx: dict) -> dict:
    params = {"num_users": int(args.get("num_users", 30)), "num_transactions": int(args.get("num_transactions", 80))}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/demo", params=params, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_asymmetry(args: dict, ctx: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{STATE_PHYSICS_URL}/api/asymmetry", headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_physics_config(args: dict, ctx: dict) -> dict:
    body = {}
    for k in ("gravity_constant", "repulsion_constant", "spring_constant", "damping"):
        if k in args and args[k] is not None:
            body[k] = float(args[k])
    if not body:
        return {"error": "Provide at least one: gravity_constant, repulsion_constant, spring_constant, damping"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/physics/config", json=body, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_entropy_config(args: dict, ctx: dict) -> dict:
    body = {}
    for k in ("position_noise", "velocity_noise", "trust_decay", "value_decay", "activity_probability"):
        if k in args and args[k] is not None:
            body[k] = float(args[k])
    if not body:
        return {"error": "Provide at least one entropy parameter"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/entropy/config", json=body, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_entropy_toggle(args: dict, ctx: dict) -> dict:
    enabled = args.get("enabled", True)
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/entropy/toggle", params={"enabled": str(enabled).lower()}, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_entropy_perturbation(args: dict, ctx: dict) -> dict:
    magnitude = float(args.get("magnitude", 1.0))
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/entropy/perturbation", params={"magnitude": magnitude}, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_agent_spawn(args: dict, ctx: dict) -> dict:
    budget = float(args.get("budget", 5000))
    action_prob = float(args.get("action_probability", 0.3))
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/agent/spawn", params={"budget": budget, "action_probability": action_prob}, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_agent_step(args: dict, ctx: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/agent/step", headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_agent_kill(args: dict, ctx: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/agent/kill", headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_agents_spawn(args: dict, ctx: dict) -> dict:
    count = int(args.get("count", 3))
    budget = float(args.get("budget", 1000))
    action_prob = float(args.get("action_probability", 0.3))
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/agents/spawn", params={"count": count, "budget": budget, "action_probability": action_prob}, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_agents_kill_all(args: dict, ctx: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/agents/kill_all", headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_experiment(args: dict, ctx: dict) -> dict:
    experiment = args.get("experiment", "")
    if not experiment:
        return {"error": "Provide experiment name: zero_agent, stress_test, or long_run"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/experiment/setup", params={"experiment": experiment}, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_memory_cost(args: dict, ctx: dict) -> dict:
    cost_multiplier = float(args.get("cost_multiplier", 1.0))
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/memory/cost", params={"cost_multiplier": cost_multiplier}, headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_sp_metrics_record(args: dict, ctx: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{STATE_PHYSICS_URL}/api/metrics/record", headers=_sp_headers(ctx))
            return r.json() if r.status_code == 200 else {"error": r.text[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}
