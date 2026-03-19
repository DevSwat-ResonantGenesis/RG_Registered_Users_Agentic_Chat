"""
Utility tool handlers — weather, image/places/YouTube search, stock/crypto,
deep research, chart generation, email, Wikipedia, SVG visualization.
Each handler: async def handler(args: dict, ctx: dict) -> dict
"""

import os
import re
import json
import logging
from datetime import datetime, timezone as tz

import httpx

logger = logging.getLogger(__name__)


async def _custom_get_current_time(args: dict, ctx: dict) -> dict:
    try:
        import zoneinfo
        tzname = args.get("timezone", "UTC")
        try:
            zi = zoneinfo.ZoneInfo(tzname)
        except Exception:
            zi = tz.utc
            tzname = "UTC"
        now = datetime.now(zi)
    except ImportError:
        now = datetime.now(tz.utc)
        tzname = "UTC"
    return {
        "datetime": now.isoformat(), "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"), "day_of_week": now.strftime("%A"),
        "timezone": tzname, "unix_timestamp": int(now.timestamp()),
    }


async def _custom_get_system_info(args: dict, ctx: dict) -> dict:
    return {
        "platform": "Resonant Genesis", "version": "2026.3",
        "user_id": ctx.get("user_id", "anonymous"), "user_role": ctx.get("user_role", "user"),
        "is_superuser": ctx.get("is_superuser", False),
    }


async def _custom_weather(args: dict, ctx: dict) -> dict:
    location = (args.get("location") or "").strip()
    if not location:
        return {"error": "location is required"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://wttr.in/{location}", params={"format": "j1"}, headers={"User-Agent": "ResonantGenesis/1.0"})
            if resp.status_code != 200:
                return {"error": f"Weather service returned {resp.status_code}"}
            data = resp.json()
            current = data.get("current_condition", [{}])[0]
            area = data.get("nearest_area", [{}])[0]
            forecast = data.get("weather", [])
            city = area.get("areaName", [{}])[0].get("value", location)
            country = area.get("country", [{}])[0].get("value", "")
            result = {
                "location": f"{city}, {country}",
                "current": {
                    "temp_c": current.get("temp_C"), "temp_f": current.get("temp_F"),
                    "feels_like_c": current.get("FeelsLikeC"),
                    "condition": current.get("weatherDesc", [{}])[0].get("value", ""),
                    "humidity": current.get("humidity"), "wind_kmph": current.get("windspeedKmph"),
                    "wind_dir": current.get("winddir16Point"), "uv_index": current.get("uvIndex"),
                    "visibility_km": current.get("visibility"), "cloud_cover": current.get("cloudcover"),
                },
                "forecast": [],
            }
            for day in forecast[:3]:
                result["forecast"].append({
                    "date": day.get("date"), "max_c": day.get("maxtempC"), "min_c": day.get("mintempC"),
                    "max_f": day.get("maxtempF"), "min_f": day.get("mintempF"),
                    "condition": day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "") if day.get("hourly") else "",
                    "chance_of_rain": day.get("hourly", [{}])[4].get("chanceofrain", "") if day.get("hourly") else "",
                })
            return result
    except Exception as e:
        return {"error": f"Weather lookup failed: {str(e)[:300]}"}


async def _custom_image_search(args: dict, ctx: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    limit = min(int(args.get("limit", 8)), 20)
    serpapi_key = os.getenv("SERPAPI_KEY", "")
    if not serpapi_key:
        return {"error": "Image search not configured."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://serpapi.com/search.json", params={"engine": "google_images", "q": query, "num": limit, "api_key": serpapi_key})
            if resp.status_code != 200:
                return {"error": f"Image search failed: HTTP {resp.status_code}"}
            data = resp.json()
            images = [{"title": img.get("title", ""), "url": img.get("original", img.get("link", "")), "thumbnail": img.get("thumbnail", ""), "source": img.get("source", ""), "width": img.get("original_width"), "height": img.get("original_height")} for img in data.get("images_results", [])[:limit]]
            return {"query": query, "images": images, "count": len(images)}
    except Exception as e:
        return {"error": f"Image search failed: {str(e)[:300]}"}


async def _custom_places_search(args: dict, ctx: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    location = (args.get("location") or "").strip()
    limit = min(int(args.get("limit", 5)), 20)
    serpapi_key = os.getenv("SERPAPI_KEY", "")
    if not serpapi_key:
        return {"error": "Places search not configured."}
    try:
        params = {"engine": "google_maps", "q": query, "api_key": serpapi_key, "type": "search"}
        if location:
            params["q"] = f"{query} in {location}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://serpapi.com/search.json", params=params)
            if resp.status_code != 200:
                return {"error": f"Places search failed: HTTP {resp.status_code}"}
            data = resp.json()
            places = [{"name": p.get("title", ""), "address": p.get("address", ""), "rating": p.get("rating"), "reviews": p.get("reviews"), "phone": p.get("phone", ""), "type": p.get("type", ""), "hours": p.get("hours", ""), "website": p.get("website", ""), "gps": p.get("gps_coordinates", {}), "thumbnail": p.get("thumbnail", "")} for p in data.get("local_results", [])[:limit]]
            return {"query": query, "location": location or "auto", "places": places, "count": len(places)}
    except Exception as e:
        return {"error": f"Places search failed: {str(e)[:300]}"}


async def _custom_youtube_search(args: dict, ctx: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    limit = min(int(args.get("limit", 5)), 15)
    serpapi_key = os.getenv("SERPAPI_KEY", "")
    if not serpapi_key:
        return {"error": "YouTube search not configured."}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://serpapi.com/search.json", params={"engine": "youtube", "search_query": query, "api_key": serpapi_key})
            if resp.status_code != 200:
                return {"error": f"YouTube search failed: HTTP {resp.status_code}"}
            data = resp.json()
            videos = [{"title": v.get("title", ""), "url": v.get("link", ""), "channel": v.get("channel", {}).get("name", ""), "views": v.get("views"), "published": v.get("published_date", ""), "duration": v.get("length", ""), "thumbnail": v.get("thumbnail", {}).get("static", ""), "description": v.get("description", "")[:200]} for v in data.get("video_results", [])[:limit]]
            return {"query": query, "videos": videos, "count": len(videos)}
    except Exception as e:
        return {"error": f"YouTube search failed: {str(e)[:300]}"}


async def _custom_stock_crypto(args: dict, ctx: dict) -> dict:
    symbol = (args.get("symbol") or "").strip().upper()
    if not symbol:
        return {"error": "symbol is required (e.g. AAPL, BTC-USD, ETH-USD, TSLA)"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}", params={"interval": "1d", "range": "5d"}, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return {"error": f"Could not find symbol '{symbol}'."}
            data = resp.json()
            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
            indicators = data.get("chart", {}).get("result", [{}])[0].get("indicators", {})
            closes = indicators.get("quote", [{}])[0].get("close", [])
            timestamps = data.get("chart", {}).get("result", [{}])[0].get("timestamp", [])
            price = meta.get("regularMarketPrice", 0)
            prev_close = meta.get("previousClose") or meta.get("chartPreviousClose", 0)
            change = round(price - prev_close, 2) if prev_close else 0
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0
            history = []
            for i, ts in enumerate(timestamps[-5:]):
                if i < len(closes) and closes[-(5-i)] is not None:
                    history.append({"date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"), "close": round(closes[-(5-i)], 2)})
            return {
                "symbol": symbol, "name": meta.get("shortName", meta.get("symbol", symbol)),
                "currency": meta.get("currency", "USD"), "exchange": meta.get("exchangeName", ""),
                "price": round(price, 2), "previous_close": round(prev_close, 2) if prev_close else None,
                "change": change, "change_percent": change_pct, "market_state": meta.get("marketState", ""),
                "day_high": meta.get("regularMarketDayHigh"), "day_low": meta.get("regularMarketDayLow"),
                "52w_high": meta.get("fiftyTwoWeekHigh"), "52w_low": meta.get("fiftyTwoWeekLow"),
                "history_5d": history,
            }
    except Exception as e:
        return {"error": f"Stock/crypto lookup failed: {str(e)[:300]}"}


async def _custom_deep_research(args: dict, ctx: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    detail = (args.get("detail") or "detailed").strip()
    pplx_key = os.getenv("PERPLEXITY_API_KEY", "")
    if not pplx_key:
        return {"error": "Deep research not configured."}
    try:
        system_msg = "You are a research assistant. Provide comprehensive, well-sourced answers with citations."
        if detail == "brief":
            system_msg = "You are a research assistant. Provide concise, well-sourced answers."
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("https://api.perplexity.ai/chat/completions", json={
                "model": "sonar", "messages": [{"role": "system", "content": system_msg}, {"role": "user", "content": query}], "max_tokens": 4000,
            }, headers={"Authorization": f"Bearer {pplx_key}", "Content-Type": "application/json"})
            if resp.status_code != 200:
                return {"error": f"Research API error: HTTP {resp.status_code}: {resp.text[:300]}"}
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            citations = data.get("citations", [])
            return {"query": query, "research": content, "citations": citations[:20], "model": data.get("model", "sonar"), "tokens_used": data.get("usage", {}).get("total_tokens", 0)}
    except Exception as e:
        return {"error": f"Deep research failed: {str(e)[:300]}"}


async def _custom_generate_chart(args: dict, ctx: dict) -> dict:
    chart_type = (args.get("type") or "bar").strip().lower()
    labels = args.get("labels", [])
    datasets = args.get("datasets", [])
    title = (args.get("title") or "").strip()
    if not labels or not datasets:
        return {"error": "Both 'labels' and 'datasets' are required."}
    chart_config = {"type": chart_type, "data": {"labels": labels, "datasets": datasets}}
    if title:
        chart_config["options"] = {"plugins": {"title": {"display": True, "text": title}}}
    try:
        import urllib.parse
        chart_json = json.dumps(chart_config)
        encoded = urllib.parse.quote(chart_json)
        chart_url = f"https://quickchart.io/chart?c={encoded}&w=600&h=400&bkg=white"
        if len(chart_url) > 8000:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post("https://quickchart.io/chart/create", json={"chart": chart_config, "width": 600, "height": 400, "backgroundColor": "white"})
                if resp.status_code == 200:
                    chart_url = resp.json().get("url", chart_url)
        return {"chart_url": chart_url, "type": chart_type, "title": title, "note": "Open the chart_url to view the chart image."}
    except Exception as e:
        return {"error": f"Chart generation failed: {str(e)[:300]}"}


async def _custom_send_email(args: dict, ctx: dict) -> dict:
    to_email = (args.get("to") or "").strip()
    subject = (args.get("subject") or "").strip()
    body = (args.get("body") or "").strip()
    if not to_email or not subject or not body:
        return {"error": "to, subject, and body are all required"}
    sendgrid_key = os.getenv("AUTH_SENDGRID_API_KEY", "")
    if not sendgrid_key:
        return {"error": "Email sending not configured."}
    from_email = os.getenv("AUTH_SMTP_USER", "noreply@resonantgenesis.com")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post("https://api.sendgrid.com/v3/mail/send", json={
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": from_email, "name": "Resonant Assistant"},
                "subject": subject, "content": [{"type": "text/html", "value": body}],
            }, headers={"Authorization": f"Bearer {sendgrid_key}", "Content-Type": "application/json"})
            if resp.status_code in (200, 201, 202):
                return {"success": True, "to": to_email, "subject": subject, "message": "Email sent successfully!"}
            return {"error": f"SendGrid error: HTTP {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"error": f"Email send failed: {str(e)[:300]}"}


async def _custom_wikipedia(args: dict, ctx: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    action = (args.get("action") or "summary").strip()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if action == "search":
                resp = await client.get("https://en.wikipedia.org/w/api.php", params={"action": "opensearch", "search": query, "limit": 10, "format": "json"})
                if resp.status_code == 200:
                    data = resp.json()
                    titles = data[1] if len(data) > 1 else []
                    descs = data[2] if len(data) > 2 else []
                    urls = data[3] if len(data) > 3 else []
                    results = [{"title": t, "description": descs[i] if i < len(descs) else "", "url": urls[i] if i < len(urls) else ""} for i, t in enumerate(titles)]
                    return {"query": query, "results": results, "count": len(results)}
            else:
                resp = await client.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}")
                if resp.status_code == 200:
                    data = resp.json()
                    return {"title": data.get("title", ""), "extract": data.get("extract", ""), "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""), "thumbnail": data.get("thumbnail", {}).get("source", ""), "description": data.get("description", "")}
                elif resp.status_code == 404:
                    search_resp = await client.get("https://en.wikipedia.org/w/api.php", params={"action": "opensearch", "search": query, "limit": 5, "format": "json"})
                    if search_resp.status_code == 200:
                        suggestions = search_resp.json()[1] if len(search_resp.json()) > 1 else []
                        return {"error": f"Article '{query}' not found.", "suggestions": suggestions}
                    return {"error": f"Article '{query}' not found."}
            return {"error": f"Wikipedia API error: HTTP {resp.status_code}"}
    except Exception as e:
        return {"error": f"Wikipedia lookup failed: {str(e)[:300]}"}


_SVG_SYSTEM_PROMPT = """You are an SVG diagram generator. You ONLY output valid SVG markup — no explanation, no markdown, no code fences.

Rules:
- Output ONLY the <svg>...</svg> element. Nothing else.
- Use viewBox for responsive sizing, e.g. viewBox="0 0 800 500"
- Use clean, modern design: rounded rects, soft colors, clear labels
- Color palette: #3b82f6 blue, #10b981 green, #f59e0b amber, #ef4444 red, #8b5cf6 purple, #06b6d4 cyan, #64748b slate
- Text: font-family="system-ui, -apple-system, sans-serif"
- For flowcharts: rounded rectangles connected by lines/arrows with arrowhead markers
- Always include a <defs> section for arrow markers if using arrows
- Max width 800px, max height 600px via viewBox
- Make text readable (min 12px equivalent)"""


async def _custom_visualize(args: dict, ctx: dict) -> dict:
    description = (args.get("description") or args.get("prompt") or "").strip()
    diagram_type = (args.get("type") or "auto").strip().lower()
    if not description:
        return {"error": "description is required"}
    groq_key = os.getenv("GROQ_API_KEY", "").split(",")[0].strip()
    if not groq_key:
        return {"error": "Visualization service not configured."}
    user_prompt = f"Generate an SVG {diagram_type} diagram for: {description}"
    if diagram_type == "auto":
        user_prompt = f"Generate an SVG diagram (choose the best type) for: {description}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post("https://api.groq.com/openai/v1/chat/completions", json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "system", "content": _SVG_SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
                "temperature": 0.3, "max_tokens": 4096,
            }, headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"})
            if resp.status_code != 200:
                return {"error": f"SVG generation failed: HTTP {resp.status_code}"}
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            svg_match = re.search(r'(<svg[\s\S]*?</svg>)', content, re.IGNORECASE)
            if not svg_match:
                return {"error": "Failed to generate valid SVG.", "raw": content[:500]}
            svg_code = svg_match.group(1)
            svg_code = re.sub(r'<script[\s\S]*?</script>', '', svg_code, flags=re.IGNORECASE)
            svg_code = re.sub(r'\bon\w+\s*=\s*["\'][^"\']*["\']', '', svg_code)
            return {"svg": svg_code, "type": diagram_type, "description": description}
    except Exception as e:
        return {"error": f"Visualization failed: {str(e)[:300]}"}
