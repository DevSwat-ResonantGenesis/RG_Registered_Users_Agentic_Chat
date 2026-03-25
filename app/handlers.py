"""
Tool Handlers — Thin HTTP proxy functions to platform microservices.
==================================================================
Each handler: async def handler(args: dict, ctx: dict) -> dict
- args: tool arguments from LLM
- ctx: user context (user_id, org_id, user_role, is_superuser, etc.)
- Returns: dict result (success data or {"error": "..."})

These do NOT contain service logic — they proxy to the real microservices via HTTP.
"""

import os
import re
import json
import copy
import time
import base64
import asyncio
import logging
from typing import Dict, Any, List
from datetime import datetime, timezone as tz

import httpx

from .config import (
    CV_SERVICE_URL, MEMORY_SERVICE_URL, AGENT_ENGINE_URL, AUTH_SERVICE_URL,
    STATE_PHYSICS_URL, GATEWAY_URL, ED_SERVICE_URL, RABBIT_SERVICE_URL,
    INTERNAL_SERVICE_KEY,
)

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Auth helper — fetch user API keys from auth_service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def fetch_user_key(user_id: str, provider: str) -> str:
    """Fetch a user's API key from auth_service."""
    if not user_id or user_id == "anonymous":
        return ""
    headers = {}
    if INTERNAL_SERVICE_KEY:
        headers["x-internal-service-key"] = INTERNAL_SERVICE_KEY
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{AUTH_SERVICE_URL}/auth/internal/user-api-keys/{user_id}?provider={provider}",
                headers=headers,
            )
            if resp.status_code == 200:
                for entry in resp.json().get("keys", []):
                    if entry.get("provider") == provider and entry.get("api_key"):
                        return entry["api_key"]
    except Exception as e:
        logger.warning(f"Failed to fetch {provider} key for {user_id}: {e}")
    return ""


async def fetch_user_byok_keys(user_id: str) -> Dict[str, str]:
    """Fetch all BYOK keys for a user from auth service."""
    if not user_id or user_id == "anonymous":
        return {}
    headers = {}
    if INTERNAL_SERVICE_KEY:
        headers["x-internal-service-key"] = INTERNAL_SERVICE_KEY
    keys = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{AUTH_SERVICE_URL}/auth/internal/user-api-keys/{user_id}",
                headers=headers,
            )
            if resp.status_code == 200:
                for entry in resp.json().get("keys", []):
                    provider = entry.get("provider", "")
                    api_key = entry.get("api_key", "")
                    if provider and api_key:
                        norm = provider.lower().replace("chat_gpt", "openai").replace("chatgpt", "openai")
                        keys[norm] = api_key
    except Exception as e:
        logger.warning(f"Failed to fetch BYOK keys for {user_id}: {e}")
    return keys


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AST Analysis handlers — proxy to standalone rg_ast_analysis service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _custom_cv_scan(args: dict, ctx: dict) -> dict:
    url = (args.get("repo_url") or args.get("github_url") or args.get("url") or "").strip()
    if not url:
        return {"error": "Missing repo_url parameter — provide a GitHub URL like https://github.com/owner/repo"}
    github_token = await fetch_user_key(ctx.get("user_id", ""), "github")
    headers = {
        "x-user-id": ctx.get("user_id", ""),
        "x-user-role": ctx.get("user_role", "user"),
        "x-is-superuser": "true" if ctx.get("is_superuser") else "false",
    }
    if github_token:
        headers["x-github-token"] = github_token
    parts = url.rstrip("/").split("/")
    project_name = parts[-1] if parts else "repo"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {"repo_url": url, "project_name": project_name}
            if github_token:
                payload["token"] = github_token
            resp = await client.post(f"{CV_SERVICE_URL}/api/v1/scan/github", json=payload, headers=headers)
            if resp.status_code != 200:
                return {"error": f"CV service error {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            analysis_id = data.get("analysis_id") or data.get("id", "")
            analysis = data.get("analysis", {})
            stats = analysis.get("stats", data.get("stats", {}))
            nodes = analysis.get("nodes", [])
            services = [n for n in nodes if n.get("type") == "service"]
            endpoints = [n for n in nodes if n.get("type") == "endpoint"]
            functions = [n for n in nodes if n.get("type") == "function"]
            imports = [n for n in nodes if n.get("type") == "import"]
            result = {
                "success": True, "analysis_id": analysis_id, "repo": url, "project_name": project_name,
                "stats": {
                    "total_files": stats.get("total_files", 0),
                    "total_services": stats.get("total_services", len(services)),
                    "total_functions": stats.get("total_functions", len(functions)),
                    "total_endpoints": stats.get("total_endpoints", len(endpoints)),
                    "total_connections": stats.get("total_connections", 0),
                    "broken_connections": stats.get("broken_connections", 0),
                    "total_imports": len(imports),
                },
                "services": [{"name": s.get("label", s.get("id", "")), "file": s.get("file", "")} for s in services[:20]],
                "top_endpoints": [{"method": e.get("method", ""), "route": e.get("route", e.get("path", "")), "service": e.get("service", "")} for e in endpoints[:15]],
                "sample_functions": [{"name": f.get("label", f.get("id", "")), "file": f.get("file", "")} for f in functions[:20]],
            }
            if stats.get("total_functions", len(functions)) == 0 and len(nodes) > 0:
                result["note"] = f"Analysis found {len(nodes)} nodes total. Use ast_analysis_report for full breakdown."
            return result
    except Exception as e:
        return {"error": f"AST Analysis scan failed: {str(e)[:300]}"}


async def _custom_cv_trace(args: dict, ctx: dict) -> dict:
    query = args.get("query", "")
    analysis_id = args.get("analysis_id", "")
    if not analysis_id:
        return {"error": "Missing analysis_id — run code_visualizer_scan first"}
    max_depth = int(args.get("max_depth", 10))
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/trace", json={"start_node": query, "max_depth": max_depth}, headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"CV trace error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": f"Trace failed: {str(e)[:300]}"}


async def _custom_cv_functions(args: dict, ctx: dict) -> dict:
    analysis_id = args.get("analysis_id", "")
    list_type = args.get("type", "functions")
    if not analysis_id:
        return {"error": "Missing analysis_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            endpoint = "functions" if list_type == "functions" else "endpoints"
            resp = await client.get(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/{endpoint}", headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"CV {endpoint} error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_cv_governance(args: dict, ctx: dict) -> dict:
    analysis_id = args.get("analysis_id", "")
    if not analysis_id:
        return {"error": "Missing analysis_id"}
    drift_threshold = float(args.get("drift_threshold", 20.0))
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user"), "x-is-superuser": "true" if ctx.get("is_superuser") else "false"}
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/governance", json={"drift_threshold": drift_threshold}, headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"Governance error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_cv_list(args: dict, ctx: dict) -> dict:
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{CV_SERVICE_URL}/api/analyses", headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"CV list error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_cv_full_analysis(args: dict, ctx: dict) -> dict:
    url = (args.get("repo_url") or args.get("github_url") or args.get("url") or "").strip()
    if not url:
        return {"error": "Missing repo_url"}
    trace_entry = args.get("trace_entry", "")
    result = {"repo": url, "steps": []}
    scan_result = await _custom_cv_scan({"repo_url": url}, ctx)
    result["steps"].append({"step": "scan", "success": scan_result.get("success", False)})
    if not scan_result.get("success"):
        result["error"] = scan_result.get("error", "Scan failed")
        return result
    analysis_id = scan_result.get("analysis_id", "")
    result["analysis_id"] = analysis_id
    result["scan"] = scan_result
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user"), "x-is-superuser": "true" if ctx.get("is_superuser") else "false"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.get(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/graph-structure", headers=headers)
            if resp.status_code == 200:
                graph = resp.json()
                result["graph"] = {"files": len(graph.get("files", [])), "modules": len(graph.get("modules", [])), "import_edges": len(graph.get("import_edges", graph.get("edges", [])))}
                result["steps"].append({"step": "graph", "success": True})
            else:
                result["steps"].append({"step": "graph", "success": False, "error": resp.text[:200]})
        except Exception as e:
            result["steps"].append({"step": "graph", "success": False, "error": str(e)[:200]})
        try:
            resp = await client.get(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/functions", headers=headers)
            if resp.status_code == 200:
                funcs = resp.json().get("functions", [])
                result["functions"] = {"total": len(funcs), "sample": [{"name": f.get("label", f.get("id", "")), "file": f.get("file", "")} for f in funcs[:30]]}
                result["steps"].append({"step": "functions", "success": True})
            else:
                result["steps"].append({"step": "functions", "success": False})
        except Exception as e:
            result["steps"].append({"step": "functions", "success": False, "error": str(e)[:200]})
        try:
            resp = await client.post(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/full-pipeline", json={"start_node": trace_entry or "", "max_depth": 30}, headers=headers)
            if resp.status_code == 200:
                trace_data = resp.json()
                trace_nodes = trace_data.get("trace", trace_data.get("nodes", []))
                if isinstance(trace_nodes, list):
                    result["pipeline"] = {"depth": len(trace_nodes), "nodes": [{"id": n.get("id", ""), "type": n.get("type", ""), "label": n.get("label", "")} for n in trace_nodes[:30]]}
                else:
                    result["pipeline"] = trace_data
                result["steps"].append({"step": "pipeline", "success": True})
            else:
                result["steps"].append({"step": "pipeline", "success": False, "error": resp.text[:200]})
        except Exception as e:
            result["steps"].append({"step": "pipeline", "success": False, "error": str(e)[:200]})
        try:
            resp = await client.post(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/governance", json={"drift_threshold": 20.0}, headers=headers)
            if resp.status_code == 200:
                gov = resp.json()
                result["governance"] = {"health_score": gov.get("governance", {}).get("health_score", gov.get("health_score")), "live_nodes": gov.get("live_count"), "invalid_nodes": gov.get("invalid_count"), "issues": gov.get("governance", {}).get("issues", [])[:10], "credits_deducted": gov.get("credits_deducted", 0)}
                result["steps"].append({"step": "governance", "success": True})
            else:
                result["steps"].append({"step": "governance", "success": False, "error": resp.text[:200]})
        except Exception as e:
            result["steps"].append({"step": "governance", "success": False, "error": str(e)[:200]})
    result["success"] = True
    return result


async def _custom_cv_report(args: dict, ctx: dict) -> dict:
    analysis_id = args.get("analysis_id", "")
    if not analysis_id:
        return {"error": "Missing analysis_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}", headers=headers)
            if resp.status_code != 200:
                return {"error": f"CV report error {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            nodes = data.get("nodes") or []
            connections = data.get("connections") or []
            return {
                "analysis_id": analysis_id, "total_nodes": len(nodes), "total_connections": len(connections),
                "node_types": {t: sum(1 for n in nodes if n.get("type") == t) for t in set(n.get("type", "unknown") for n in nodes)},
                "files": list(set(n.get("file", "") for n in nodes if n.get("file")))[:50],
                "sample_nodes": nodes[:20],
            }
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_cv_graph(args: dict, ctx: dict) -> dict:
    analysis_id = args.get("analysis_id", "")
    if not analysis_id:
        return {"error": "Missing analysis_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/graph-structure", headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"CV graph error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_cv_pipeline(args: dict, ctx: dict) -> dict:
    analysis_id = args.get("analysis_id", "")
    if not analysis_id:
        return {"error": "Missing analysis_id"}
    start_node = args.get("start_node", "")
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/full-pipeline", json={"start_node": start_node, "max_depth": 50}, headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"CV pipeline error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_cv_filter(args: dict, ctx: dict) -> dict:
    analysis_id = args.get("analysis_id", "")
    if not analysis_id:
        return {"error": "Missing analysis_id"}
    payload = {}
    if args.get("file_path"):
        payload["file_path"] = args["file_path"]
    if args.get("node_type"):
        payload["node_type"] = args["node_type"]
    if args.get("keyword"):
        payload["keyword"] = args["keyword"]
    if not payload:
        return {"error": "Provide at least one of: file_path, node_type, keyword"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/filter", json=payload, headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"CV filter error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_cv_by_type(args: dict, ctx: dict) -> dict:
    analysis_id = args.get("analysis_id", "")
    node_type = args.get("node_type", "function")
    if not analysis_id:
        return {"error": "Missing analysis_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{CV_SERVICE_URL}/api/analysis/{analysis_id}/by-type/{node_type}", headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"CV by-type error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_cv_compare(args: dict, ctx: dict) -> dict:
    id_a = args.get("analysis_id_a", "")
    id_b = args.get("analysis_id_b", "")
    if not id_a or not id_b:
        return {"error": "Both analysis_id_a and analysis_id_b are required"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{CV_SERVICE_URL}/api/compare-by-analysis", json={"analysis_id_a": id_a, "analysis_id_b": id_b}, headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"CV compare error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_cv_delete(args: dict, ctx: dict) -> dict:
    analysis_id = args.get("analysis_id", "")
    if not analysis_id:
        return {"error": "Missing analysis_id"}
    headers = {"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.delete(f"{CV_SERVICE_URL}/api/v1/analyses/{analysis_id}", headers=headers)
            if resp.status_code not in (200, 204):
                return {"error": f"CV delete error {resp.status_code}: {resp.text[:300]}"}
            return {"success": True, "message": f"Analysis {analysis_id} deleted"}
    except Exception as e:
        return {"error": str(e)[:300]}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Memory & Hash Sphere handlers — proxy to memory_service
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _custom_memory_search(args: dict, ctx: dict) -> dict:
    query = args.get("query", "")
    if not query:
        return {"error": "Missing query"}
    limit = int(args.get("limit", 10))
    headers = {"x-user-id": ctx.get("user_id", "")}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{MEMORY_SERVICE_URL}/memory/search", json={"query": query, "limit": limit, "user_id": ctx.get("user_id", "")}, headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"Memory search error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_memory_stats(args: dict, ctx: dict) -> dict:
    headers = {"x-user-id": ctx.get("user_id", "")}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{MEMORY_SERVICE_URL}/memory/stats", headers=headers, params={"user_id": ctx.get("user_id", "")})
            return resp.json() if resp.status_code == 200 else {"error": f"Memory stats error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_hs_search(args: dict, ctx: dict) -> dict:
    query = args.get("query", "")
    if not query:
        return {"error": "Missing query"}
    limit = int(args.get("limit", 10))
    headers = {"x-user-id": ctx.get("user_id", "")}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{MEMORY_SERVICE_URL}/memory/hash-sphere/search", json={"query": query, "limit": limit, "user_id": ctx.get("user_id", "")}, headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"Hash Sphere search error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_hs_anchor(args: dict, ctx: dict) -> dict:
    content_val = args.get("content", "")
    if not content_val:
        return {"error": "Missing content to anchor"}
    label = args.get("label", "")
    metadata = args.get("metadata", {})
    headers = {"x-user-id": ctx.get("user_id", "")}
    payload = {"content": content_val, "user_id": ctx.get("user_id", "")}
    if label:
        payload["label"] = label
    if metadata and isinstance(metadata, dict):
        payload["metadata"] = metadata
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{MEMORY_SERVICE_URL}/memory/hash-sphere/anchors", json=payload, headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"Anchor creation error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_hs_list_anchors(args: dict, ctx: dict) -> dict:
    limit = int(args.get("limit", 20))
    headers = {"x-user-id": ctx.get("user_id", "")}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{MEMORY_SERVICE_URL}/memory/hash-sphere/anchors", headers=headers, params={"user_id": ctx.get("user_id", ""), "limit": limit})
            return resp.json() if resp.status_code == 200 else {"error": f"List anchors error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_hs_hash(args: dict, ctx: dict) -> dict:
    content_val = args.get("content", "")
    if not content_val:
        return {"error": "Missing content"}
    headers = {"x-user-id": ctx.get("user_id", "")}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{MEMORY_SERVICE_URL}/memory/hash-sphere/hash", json={"content": content_val}, headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"Hash error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_hs_resonance(args: dict, ctx: dict) -> dict:
    a = args.get("content_a", "")
    b = args.get("content_b", "")
    if not a or not b:
        return {"error": "Both content_a and content_b required"}
    headers = {"x-user-id": ctx.get("user_id", "")}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{MEMORY_SERVICE_URL}/memory/hash-sphere/resonance", json={"content_a": a, "content_b": b}, headers=headers)
            return resp.json() if resp.status_code == 200 else {"error": f"Resonance error {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": str(e)[:300]}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Local IDE file placeholders (executed client-side)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _local_file_read(args: dict, ctx: dict) -> dict:
    return {"_local_tool": True, "tool": "file_read", "args": args, "message": "This tool executes locally in the Resonant IDE desktop app."}

async def _local_file_write(args: dict, ctx: dict) -> dict:
    return {"_local_tool": True, "tool": "file_write", "args": args, "message": "This tool executes locally in the Resonant IDE desktop app."}

async def _local_file_edit(args: dict, ctx: dict) -> dict:
    return {"_local_tool": True, "tool": "file_edit", "args": args, "message": "This tool executes locally in the Resonant IDE desktop app."}

async def _local_file_list(args: dict, ctx: dict) -> dict:
    return {"_local_tool": True, "tool": "file_list", "args": args, "message": "This tool executes locally in the Resonant IDE desktop app."}

async def _local_file_delete(args: dict, ctx: dict) -> dict:
    return {"_local_tool": True, "tool": "file_delete", "args": args, "message": "This tool executes locally in the Resonant IDE desktop app."}
