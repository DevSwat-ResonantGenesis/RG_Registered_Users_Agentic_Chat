"""
Web Search / Browsing / Reddit handlers.
Each handler: async def handler(args: dict, ctx: dict) -> dict
"""

import os
import re
import json
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

_WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _extract_page_content(html: str, url: str, max_length: int = 15000, extract_links: bool = True) -> dict:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        from html import unescape
        text = re.sub(r"(?is)<(script|style|nav|footer|header).*?>.*?</\1>", " ", html)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return {"url": url, "title": "", "content": text[:max_length], "links": []}
    try:
        import lxml  # noqa: F401
        parser = "lxml"
    except ImportError:
        parser = "html.parser"
    soup = BeautifulSoup(html, parser)
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript", "svg", "form"]):
        tag.decompose()
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    main = soup.find("article") or soup.find("main") or soup.find(role="main") or soup.body or soup
    parts = []
    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "pre", "code", "blockquote"]):
        text = el.get_text(separator=" ", strip=True)
        if not text or len(text) < 3:
            continue
        tag = el.name
        if tag in ("h1", "h2", "h3", "h4"):
            level = int(tag[1])
            parts.append(f"\n{'#' * level} {text}\n")
        elif tag == "li":
            parts.append(f"  • {text}")
        elif tag == "blockquote":
            parts.append(f"> {text}")
        elif tag in ("pre", "code"):
            parts.append(f"```\n{text}\n```")
        else:
            parts.append(text)
    content = "\n".join(parts).strip()
    if not content:
        content = main.get_text(separator="\n", strip=True)
    links = []
    if extract_links:
        for a in (main.find_all("a", href=True) if main else []):
            href = a["href"]
            link_text = a.get_text(strip=True)
            if href.startswith("http") and link_text and len(link_text) > 2:
                links.append({"text": link_text[:100], "url": href})
            if len(links) >= 20:
                break
    return {"url": url, "title": title, "content": content[:max_length], "content_length": len(content), "links": links}


async def _fetch_and_extract(url: str, max_length: int = 15000, extract_links: bool = True) -> dict:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=_WEB_HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                return {"url": url, "error": f"HTTP {resp.status_code}"}
            ct = (resp.headers.get("content-type") or "").lower()
            if "json" in ct:
                try:
                    return {"url": url, "content": json.dumps(resp.json(), indent=2)[:max_length], "content_type": "json"}
                except Exception:
                    pass
            html = resp.text
            if len(html) > 2_000_000:
                html = html[:2_000_000]
            return _extract_page_content(html, url, max_length, extract_links)
    except Exception as e:
        return {"url": url, "error": str(e)[:300]}


async def _custom_web_search(args: dict, ctx: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    max_results = min(int(args.get("max_results", 5)), 10)
    tavily_raw = os.getenv("TAVILY_API_KEY", "")
    tavily_keys = [k.strip() for k in tavily_raw.split(",") if k.strip()]
    if not tavily_keys:
        return {"error": "Web search API not configured."}
    data = None
    last_error = ""
    for key in tavily_keys:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post("https://api.tavily.com/search", json={
                    "api_key": key, "query": query, "max_results": max_results,
                    "search_depth": "advanced", "include_answer": True, "include_raw_content": False,
                })
                if resp.status_code == 200:
                    data = resp.json()
                    break
                last_error = f"HTTP {resp.status_code}"
        except Exception as e:
            last_error = str(e)[:200]
    if data is None:
        return {"error": f"Web search failed: {last_error}"}
    results = [{"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("content", "")[:400], "published_date": item.get("published_date")} for item in data.get("results", [])]
    out = {"query": query, "results": results, "count": len(results)}
    if data.get("answer"):
        out["ai_summary"] = data["answer"]
    return out


async def _custom_read_webpage(args: dict, ctx: dict) -> dict:
    url = (args.get("url") or "").strip()
    if not url:
        return {"error": "url is required"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    max_length = int(args.get("max_length", 15000))
    extract_links = args.get("extract_links", True)
    if isinstance(extract_links, str):
        extract_links = extract_links.lower() not in ("false", "0", "no")
    return await _fetch_and_extract(url, max_length, extract_links)


async def _custom_read_many_pages(args: dict, ctx: dict) -> dict:
    urls = args.get("urls", [])
    if isinstance(urls, str):
        try:
            urls = json.loads(urls)
        except Exception:
            urls = [u.strip() for u in urls.split(",") if u.strip()]
    if not urls or not isinstance(urls, list):
        return {"error": "urls is required — provide a list of URLs"}
    if len(urls) > 5:
        urls = urls[:5]
    max_length = int(args.get("max_length_per_page", 8000))
    clean_urls = []
    for u in urls:
        u = str(u).strip()
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        clean_urls.append(u)
    results = await asyncio.gather(*[_fetch_and_extract(u, max_length, False) for u in clean_urls])
    return {"pages": list(results), "total": len(results), "succeeded": sum(1 for r in results if "error" not in r), "failed": sum(1 for r in results if "error" in r)}


async def _custom_reddit_search(args: dict, ctx: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    subreddit = (args.get("subreddit") or "").strip()
    limit = min(int(args.get("limit", 10)), 25)
    tavily_raw = os.getenv("TAVILY_API_KEY", "")
    tavily_keys = [k.strip() for k in tavily_raw.split(",") if k.strip()]
    if not tavily_keys:
        return {"error": "Search API not configured."}
    search_query = f"{query} reddit"
    if subreddit:
        search_query = f"{query} r/{subreddit} reddit"
    data = None
    last_error = ""
    for key in tavily_keys:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post("https://api.tavily.com/search", json={
                    "api_key": key, "query": search_query, "max_results": limit,
                    "search_depth": "basic", "include_domains": ["reddit.com"],
                    "include_answer": True, "include_raw_content": False,
                })
                if resp.status_code == 200:
                    data = resp.json()
                    break
                last_error = f"HTTP {resp.status_code}"
        except Exception as e:
            last_error = str(e)[:200]
    if data is None:
        return {"error": f"All search API keys failed. Last error: {last_error}"}
    posts = []
    for item in data.get("results", []):
        url = item.get("url", "")
        title = item.get("title", "").replace(" : r/", " | r/").replace(" - Reddit", "").strip()
        snippet = item.get("content", "")[:500]
        sr_match = re.search(r"reddit\.com/r/(\w+)", url)
        sr_name = sr_match.group(1) if sr_match else ""
        posts.append({"title": title, "subreddit": sr_name, "url": url, "snippet": snippet})
    result = {"query": query, "subreddit": subreddit or "all", "results": posts, "count": len(posts)}
    if data.get("answer"):
        result["ai_summary"] = data["answer"]
    return result


async def _custom_news_search(args: dict, ctx: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    max_results = min(int(args.get("max_results", 5)), 10)
    tavily_raw = os.getenv("TAVILY_API_KEY", "")
    tavily_keys = [k.strip() for k in tavily_raw.split(",") if k.strip()]
    if not tavily_keys:
        return {"error": "News search not configured."}
    for key in tavily_keys:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post("https://api.tavily.com/search", json={
                    "api_key": key, "query": query, "max_results": max_results,
                    "search_depth": "advanced", "topic": "news", "include_answer": True,
                })
                if resp.status_code == 200:
                    data = resp.json()
                    articles = [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")[:400], "published_date": r.get("published_date"), "source": r.get("url", "").split("/")[2] if "/" in r.get("url", "") else ""} for r in data.get("results", [])[:max_results]]
                    out = {"query": query, "articles": articles, "count": len(articles)}
                    if data.get("answer"):
                        out["ai_summary"] = data["answer"]
                    return out
        except Exception as e:
            logger.warning(f"[NEWS] Tavily key failed: {e}")
    return {"error": "News search temporarily unavailable."}
