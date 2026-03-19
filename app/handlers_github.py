"""
GitHub API handlers — proxy to GitHub REST API using user tokens.
Each handler: async def handler(args: dict, ctx: dict) -> dict
"""

import base64
import logging

import httpx

from .handlers import fetch_user_key
from .config import ED_SERVICE_URL

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


async def _custom_github_create_repo(args: dict, ctx: dict) -> dict:
    token = await fetch_user_key(ctx.get("user_id", ""), "github")
    if not token:
        return {"error": "No GitHub token configured. Add your GitHub Personal Access Token in Settings > API Keys."}
    name = args.get("name", "").strip()
    if not name:
        return {"error": "Missing 'name' parameter"}
    payload = {"name": name, "auto_init": True}
    if args.get("description"):
        payload["description"] = args["description"]
    if args.get("private"):
        payload["private"] = True
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{GITHUB_API}/user/repos", json=payload, headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
            if resp.status_code not in (200, 201):
                return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            return {"success": True, "full_name": data.get("full_name"), "url": data.get("html_url"), "clone_url": data.get("clone_url"), "private": data.get("private")}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_github_list_repos(args: dict, ctx: dict) -> dict:
    token = await fetch_user_key(ctx.get("user_id", ""), "github")
    if not token:
        return {"error": "No GitHub token configured."}
    owner = args.get("owner", "")
    limit = int(args.get("limit", 30))
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            url = f"{GITHUB_API}/users/{owner}/repos?per_page={limit}&sort=updated" if owner else f"{GITHUB_API}/user/repos?per_page={limit}&sort=updated"
            resp = await client.get(url, headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
            if resp.status_code != 200:
                return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
            repos = resp.json()
            return {"repos": [{"name": r.get("name"), "full_name": r.get("full_name"), "url": r.get("html_url"), "private": r.get("private"), "language": r.get("language"), "updated_at": r.get("updated_at")} for r in repos[:limit]], "count": len(repos)}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_github_list_files(args: dict, ctx: dict) -> dict:
    token = await fetch_user_key(ctx.get("user_id", ""), "github")
    if not token:
        return {"error": "No GitHub token configured."}
    owner, repo, path = args.get("owner", ""), args.get("repo", ""), args.get("path", "")
    ref = args.get("ref", "main")
    if not owner or not repo:
        return {"error": "Both 'owner' and 'repo' are required"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}?ref={ref}", headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
            if resp.status_code != 200:
                return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
            items = resp.json()
            if isinstance(items, list):
                return {"files": [{"name": i.get("name"), "type": i.get("type"), "size": i.get("size"), "path": i.get("path")} for i in items]}
            return {"file": {"name": items.get("name"), "type": items.get("type"), "size": items.get("size"), "path": items.get("path")}}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_github_download_file(args: dict, ctx: dict) -> dict:
    token = await fetch_user_key(ctx.get("user_id", ""), "github")
    if not token:
        return {"error": "No GitHub token configured."}
    owner, repo, path = args.get("owner", ""), args.get("repo", ""), args.get("path", "")
    ref = args.get("ref", "main")
    if not owner or not repo or not path:
        return {"error": "'owner', 'repo', and 'path' are required"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}?ref={ref}", headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
            if resp.status_code != 200:
                return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace") if data.get("encoding") == "base64" else data.get("content", "")
            return {"path": path, "sha": data.get("sha"), "size": data.get("size"), "content": content[:10000]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_github_upload_file(args: dict, ctx: dict) -> dict:
    token = await fetch_user_key(ctx.get("user_id", ""), "github")
    if not token:
        return {"error": "No GitHub token configured."}
    owner, repo, path = args.get("owner", ""), args.get("repo", ""), args.get("path", "")
    content = args.get("content", "")
    message = args.get("message", "Update file")
    branch = args.get("branch", "main")
    sha = args.get("sha")
    if not owner or not repo or not path or not content:
        return {"error": "'owner', 'repo', 'path', and 'content' are required"}
    payload = {"message": message, "content": base64.b64encode(content.encode()).decode(), "branch": branch}
    if sha:
        payload["sha"] = sha
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.put(f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}", json=payload, headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
            if resp.status_code not in (200, 201):
                return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            return {"success": True, "path": path, "sha": data.get("content", {}).get("sha"), "commit_sha": data.get("commit", {}).get("sha")}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_github_commits(args: dict, ctx: dict) -> dict:
    token = await fetch_user_key(ctx.get("user_id", ""), "github")
    if not token:
        return {"error": "No GitHub token configured."}
    owner, repo = args.get("owner", ""), args.get("repo", "")
    sha = args.get("sha", "")
    limit = int(args.get("limit", 10))
    if not owner or not repo:
        return {"error": "'owner' and 'repo' are required"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if sha:
                resp = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}/commits/{sha}", headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
                if resp.status_code != 200:
                    return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
                c = resp.json()
                return {"commit": {"sha": c.get("sha"), "message": c.get("commit", {}).get("message"), "author": c.get("commit", {}).get("author", {}).get("name"), "date": c.get("commit", {}).get("author", {}).get("date"), "files_changed": len(c.get("files", []))}}
            else:
                resp = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}/commits?per_page={limit}", headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
                if resp.status_code != 200:
                    return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
                commits = resp.json()
                return {"commits": [{"sha": c.get("sha")[:8], "message": c.get("commit", {}).get("message", "")[:100], "author": c.get("commit", {}).get("author", {}).get("name"), "date": c.get("commit", {}).get("author", {}).get("date")} for c in commits[:limit]]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_github_pull_request(args: dict, ctx: dict) -> dict:
    token = await fetch_user_key(ctx.get("user_id", ""), "github")
    if not token:
        return {"error": "No GitHub token configured."}
    owner, repo = args.get("owner", ""), args.get("repo", "")
    action = args.get("action", "list")
    if not owner or not repo:
        return {"error": "'owner' and 'repo' are required"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if action == "create":
                payload = {"title": args.get("title", ""), "body": args.get("body", ""), "head": args.get("head", ""), "base": args.get("base", "main")}
                resp = await client.post(f"{GITHUB_API}/repos/{owner}/{repo}/pulls", json=payload, headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
                if resp.status_code not in (200, 201):
                    return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
                pr = resp.json()
                return {"success": True, "number": pr.get("number"), "url": pr.get("html_url"), "title": pr.get("title")}
            else:
                state = args.get("state", "open")
                resp = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}/pulls?state={state}&per_page=20", headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
                if resp.status_code != 200:
                    return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
                prs = resp.json()
                return {"pull_requests": [{"number": p.get("number"), "title": p.get("title"), "state": p.get("state"), "user": p.get("user", {}).get("login"), "url": p.get("html_url")} for p in prs[:20]]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_github_issue(args: dict, ctx: dict) -> dict:
    token = await fetch_user_key(ctx.get("user_id", ""), "github")
    if not token:
        return {"error": "No GitHub token configured."}
    owner, repo = args.get("owner", ""), args.get("repo", "")
    action = args.get("action", "list")
    if not owner or not repo:
        return {"error": "'owner' and 'repo' are required"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if action == "create":
                payload = {"title": args.get("title", ""), "body": args.get("body", "")}
                labels = args.get("labels", "")
                if labels:
                    payload["labels"] = [l.strip() for l in labels.split(",") if l.strip()]
                resp = await client.post(f"{GITHUB_API}/repos/{owner}/{repo}/issues", json=payload, headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
                if resp.status_code not in (200, 201):
                    return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
                issue = resp.json()
                return {"success": True, "number": issue.get("number"), "url": issue.get("html_url"), "title": issue.get("title")}
            else:
                state = args.get("state", "open")
                resp = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}/issues?state={state}&per_page=20", headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
                if resp.status_code != 200:
                    return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
                issues = resp.json()
                return {"issues": [{"number": i.get("number"), "title": i.get("title"), "state": i.get("state"), "user": i.get("user", {}).get("login"), "labels": [l.get("name") for l in i.get("labels", [])]} for i in issues[:20]]}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_github_comment(args: dict, ctx: dict) -> dict:
    token = await fetch_user_key(ctx.get("user_id", ""), "github")
    if not token:
        return {"error": "No GitHub token configured."}
    owner, repo = args.get("owner", ""), args.get("repo", "")
    issue_number = args.get("issue_number")
    body = args.get("body", "")
    if not owner or not repo or not issue_number or not body:
        return {"error": "'owner', 'repo', 'issue_number', and 'body' are required"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments", json={"body": body}, headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"})
            if resp.status_code not in (200, 201):
                return {"error": f"GitHub API {resp.status_code}: {resp.text[:300]}"}
            return {"success": True, "url": resp.json().get("html_url")}
    except Exception as e:
        return {"error": str(e)[:300]}


async def _custom_git_proxy(args: dict, ctx: dict) -> dict:
    tool_name = args.pop("_tool_name", "git_status")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{ED_SERVICE_URL}/tools/execute", json={"tool": tool_name, "args": args}, headers={"x-user-id": ctx.get("user_id", ""), "x-user-role": ctx.get("user_role", "user")})
            if resp.status_code != 200:
                return {"error": f"ED service {resp.status_code}: {resp.text[:300]}"}
            return resp.json()
    except Exception as e:
        return {"info": f"Git operation '{tool_name}' — ed_service not available: {str(e)[:200]}. Use GitHub API tools instead."}
