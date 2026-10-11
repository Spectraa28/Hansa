"""The agent's one tool: fetch a public page and return its visible text."""
import re

import httpx

MAX_CHARS = 6000


def fetch_page(url: str) -> str:
    print(f"[tool] fetching {url}")
    try:
        response = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "web-lookup-agent/0.1"})
        response.raise_for_status()
    except httpx.HTTPError as error:
        return f"Fetch failed: {type(error).__name__}"
    text = re.sub(r"(?s)<(script|style).*?</\1>", " ", response.text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:MAX_CHARS]


TOOL_SPEC = [{"type": "function", "function": {
    "name": "fetch_page", "description": "Fetch a public web page and return its text.",
    "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}}]
