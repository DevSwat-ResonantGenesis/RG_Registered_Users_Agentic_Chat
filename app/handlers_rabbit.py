"""
Rabbit (Community Forum) handlers — proxy to rabbit_service.
Each handler: async def handler(args: dict, ctx: dict) -> dict
"""

import httpx
import logging

from .config import RABBIT_SERVICE_URL

logger = logging.getLogger(__name__)


async def _custom_rabbit_create_community(args: dict, ctx: dict) -> dict:
    slug = (args.get("slug") or "").strip()
    name = (args.get("name") or "").strip()
    description = args.get("description") or ""
    if not slug or not name:
        return {"error": "Both 'slug' (url-friendly id) and 'name' are required."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{RABBIT_SERVICE_URL}/rabbit/communities", json={"slug": slug, "name": name, "description": description}, headers={"x-user-id": ctx.get("user_id", "anonymous")})
            if resp.status_code in (200, 201):
                return resp.json()
            return {"error": f"Failed ({resp.status_code}): {resp.text[:500]}"}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_list_communities(args: dict, ctx: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{RABBIT_SERVICE_URL}/rabbit/communities", headers={"x-user-id": ctx.get("user_id", "anonymous")})
            return resp.json() if resp.status_code == 200 else {"error": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_get_community(args: dict, ctx: dict) -> dict:
    slug = (args.get("slug") or args.get("community_slug") or "").strip()
    if not slug:
        return {"error": "Missing 'slug' parameter."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{RABBIT_SERVICE_URL}/rabbit/communities/{slug}", headers={"x-user-id": ctx.get("user_id", "anonymous")})
            return resp.json() if resp.status_code == 200 else {"error": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_create_post(args: dict, ctx: dict) -> dict:
    title = (args.get("title") or "").strip()
    body = args.get("body") or ""
    community_slug = (args.get("community_slug") or args.get("slug") or "").strip()
    image_url = args.get("image_url")
    if not title:
        return {"error": "Missing 'title' parameter."}
    payload = {"title": title, "body": body, "community_slug": community_slug}
    if image_url:
        payload["image_url"] = image_url
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{RABBIT_SERVICE_URL}/rabbit/posts", json=payload, headers={"x-user-id": ctx.get("user_id", "anonymous")})
            if resp.status_code in (200, 201):
                return resp.json()
            return {"error": f"Failed ({resp.status_code}): {resp.text[:500]}"}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_list_posts(args: dict, ctx: dict) -> dict:
    slug = (args.get("community_slug") or args.get("slug") or "").strip()
    limit = int(args.get("limit", 20))
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            url = f"{RABBIT_SERVICE_URL}/rabbit/communities/{slug}/posts" if slug else f"{RABBIT_SERVICE_URL}/rabbit/posts"
            resp = await client.get(url, params={"limit": limit}, headers={"x-user-id": ctx.get("user_id", "anonymous")})
            return resp.json() if resp.status_code == 200 else {"error": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_search_posts(args: dict, ctx: dict) -> dict:
    q = (args.get("query") or args.get("q") or "").strip()
    if not q:
        return {"error": "Missing 'query' parameter."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{RABBIT_SERVICE_URL}/rabbit/posts/search", params={"q": q, "limit": int(args.get("limit", 20))}, headers={"x-user-id": ctx.get("user_id", "anonymous")})
            return resp.json() if resp.status_code == 200 else {"error": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_get_post(args: dict, ctx: dict) -> dict:
    post_id = args.get("post_id") or args.get("id")
    if not post_id:
        return {"error": "Missing 'post_id' parameter."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{RABBIT_SERVICE_URL}/rabbit/posts/{post_id}", headers={"x-user-id": ctx.get("user_id", "anonymous")})
            return resp.json() if resp.status_code == 200 else {"error": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_delete_post(args: dict, ctx: dict) -> dict:
    post_id = args.get("post_id") or args.get("id")
    if not post_id:
        return {"error": "Missing 'post_id' parameter."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.delete(f"{RABBIT_SERVICE_URL}/rabbit/posts/{post_id}", headers={"x-user-id": ctx.get("user_id", "anonymous")})
            return resp.json() if resp.status_code == 200 else {"error": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_create_comment(args: dict, ctx: dict) -> dict:
    post_id = args.get("post_id")
    body = (args.get("body") or args.get("text") or args.get("content") or "").strip()
    parent_comment_id = args.get("parent_comment_id")
    if not post_id or not body:
        return {"error": "Both 'post_id' and 'body' are required."}
    payload = {"body": body}
    if parent_comment_id:
        payload["parent_comment_id"] = int(parent_comment_id)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{RABBIT_SERVICE_URL}/rabbit/posts/{post_id}/comments", json=payload, headers={"x-user-id": ctx.get("user_id", "anonymous")})
            if resp.status_code in (200, 201):
                return resp.json()
            return {"error": f"Failed ({resp.status_code}): {resp.text[:500]}"}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_list_comments(args: dict, ctx: dict) -> dict:
    post_id = args.get("post_id")
    if not post_id:
        return {"error": "Missing 'post_id' parameter."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{RABBIT_SERVICE_URL}/rabbit/posts/{post_id}/comments", headers={"x-user-id": ctx.get("user_id", "anonymous")})
            return resp.json() if resp.status_code == 200 else {"error": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_delete_comment(args: dict, ctx: dict) -> dict:
    comment_id = args.get("comment_id") or args.get("id")
    if not comment_id:
        return {"error": "Missing 'comment_id' parameter."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.delete(f"{RABBIT_SERVICE_URL}/rabbit/comments/{comment_id}", headers={"x-user-id": ctx.get("user_id", "anonymous")})
            return resp.json() if resp.status_code == 200 else {"error": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)[:500]}


async def _custom_rabbit_vote(args: dict, ctx: dict) -> dict:
    target_type = (args.get("target_type") or "post").strip()
    target_id = args.get("target_id") or args.get("post_id") or args.get("comment_id")
    value = args.get("value", 1)
    if not target_id:
        return {"error": "Missing 'target_id' (the post or comment ID)."}
    if target_type not in ("post", "comment"):
        return {"error": "target_type must be 'post' or 'comment'."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.put(f"{RABBIT_SERVICE_URL}/rabbit/votes", json={"target_type": target_type, "target_id": int(target_id), "value": int(value)}, headers={"x-user-id": ctx.get("user_id", "anonymous")})
            return resp.json() if resp.status_code == 200 else {"error": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)[:500]}
