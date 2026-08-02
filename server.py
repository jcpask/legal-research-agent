"""
Legal Research MCP server for classroom use.

Exposes three tools over Streamable HTTP so students can add this as a
remote connector in Claude.ai and ask plain-English questions that get
answered from real, citable sources:

- search_case_law     -> CourtListener v4 search API (US case law, free, no
                         token required for basic search)
- get_opinion_text    -> CourtListener cluster/opinion detail (requires a
                         free API token; degrades gracefully without one)
- lookup_legal_term   -> Cornell Law School's Wex legal dictionary

Run locally:
    python server.py

Environment variables:
    COURTLISTENER_API_TOKEN   optional, raises rate limits and unlocks
                               full opinion text (see README.md)
    PORT                       port to bind for streamable-http (default 8000)
"""

import difflib
import os
import re
from functools import lru_cache

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

COURTLISTENER_BASE = "https://www.courtlistener.com"
COURTLISTENER_API = f"{COURTLISTENER_BASE}/api/rest/v4"
CORNELL_WEX_BASE = "https://www.law.cornell.edu/wex"

USER_AGENT = "legal-research-classroom-agent/1.0 (educational use)"

mcp = FastMCP(
    "legal-research-assistant",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
)


def _courtlistener_headers() -> dict:
    token = os.environ.get("COURTLISTENER_API_TOKEN")
    return {"Authorization": f"Token {token}"} if token else {}


def _clean_snippet(snippet: str) -> str:
    text = re.sub(r"</?(mark|span)[^>]*>", "", snippet or "")
    return re.sub(r"\s+", " ", text).strip()


def _slugify(term: str) -> str:
    slug = term.strip().lower()
    slug = re.sub(r"\s+", "_", slug)
    slug = re.sub(r"[^a-z0-9_.\-]", "", slug)
    return slug


@lru_cache(maxsize=256)
def _fetch_wex_page(url: str) -> tuple[int, str]:
    resp = httpx.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True
    )
    return resp.status_code, resp.text


def _format_wex_page(html: str, url: str, note: str | None = None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else "Wex entry"

    content = (
        soup.find(id="main-content")
        or soup.find("div", class_=re.compile("field-name-body|node-content"))
        or soup.body
    )
    paragraphs = []
    if content:
        for p in content.find_all("p"):
            text = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
            text = re.sub(r"\s+([.,;:)])", r"\1", text)
            if text:
                paragraphs.append(text)
            if len(paragraphs) >= 4:
                break
    body = "\n\n".join(paragraphs) if paragraphs else (
        "(Could not extract definition text automatically -- view the page directly.)"
    )
    prefix = f"{note}\n\n" if note else ""
    return (
        f"{prefix}**{title}** -- Cornell Law School Legal Information Institute (Wex)\n\n"
        f"{body}\n\nSource: {url}"
    )


@mcp.tool()
def search_case_law(
    query: str,
    court: str | None = None,
    filed_after: str | None = None,
    filed_before: str | None = None,
    max_results: int = 5,
) -> str:
    """Search real US case law via CourtListener (free.law).

    Args:
        query: Search terms, e.g. a case name, topic, or citation.
        court: Optional court identifier to filter by, e.g. "scotus".
        filed_after: Optional ISO date (YYYY-MM-DD) lower bound on filing date.
        filed_before: Optional ISO date (YYYY-MM-DD) upper bound on filing date.
        max_results: Number of results to return (default 5, max 20).

    Returns a formatted list of matching cases with citation, court, date,
    a snippet, and a link to the full case on courtlistener.com. Use the
    returned cluster_id with get_opinion_text to fetch full opinion text.
    """
    max_results = max(1, min(max_results, 20))
    params = {"q": query, "type": "o"}
    if court:
        params["court"] = court
    if filed_after:
        params["filed_after"] = filed_after
    if filed_before:
        params["filed_before"] = filed_before

    resp = httpx.get(
        f"{COURTLISTENER_API}/search/",
        params=params,
        headers=_courtlistener_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])[:max_results]

    if not results:
        return f"No cases found for query: {query!r}. Try a broader search term."

    lines = [f"Found {data.get('count', len(results))} total result(s); showing top {len(results)}:\n"]
    for r in results:
        citations = ", ".join(r.get("citation") or []) or "no reported citation on file"
        absolute_url = r.get("absolute_url") or ""
        opinions = r.get("opinions") or [{}]
        snippet = _clean_snippet(opinions[0].get("snippet") or r.get("snippet") or "")
        lines.append(
            f"- **{r.get('caseName')}** ({citations})\n"
            f"  Court: {r.get('court')} | Filed: {r.get('dateFiled')}\n"
            f"  Docket: {r.get('docketNumber') or 'n/a'}\n"
            f"  Snippet: {snippet or '(no snippet available)'}\n"
            f"  Full case: {COURTLISTENER_BASE}{absolute_url}\n"
            f"  cluster_id: {r.get('cluster_id')} (pass to get_opinion_text for the full opinion)\n"
        )
    return "\n".join(lines)


@mcp.tool()
def get_opinion_text(cluster_id: int) -> str:
    """Fetch the full opinion text for a case, by its CourtListener cluster_id.

    Get cluster_id from search_case_law results first. This endpoint requires
    a free CourtListener API token (set COURTLISTENER_API_TOKEN) -- without
    one, this returns instructions instead of the opinion text.
    """
    if not os.environ.get("COURTLISTENER_API_TOKEN"):
        return (
            "Full opinion text requires a free CourtListener API token. "
            "Sign up at https://www.courtlistener.com and set the "
            "COURTLISTENER_API_TOKEN environment variable on this server. "
            "In the meantime, use the 'Full case' link returned by search_case_law "
            "to read the opinion directly on courtlistener.com."
        )

    headers = _courtlistener_headers()
    op_resp = httpx.get(
        f"{COURTLISTENER_API}/opinions/",
        params={"cluster": cluster_id},
        headers=headers,
        timeout=20,
    )
    if op_resp.status_code == 401:
        return "CourtListener rejected the configured API token (401 Unauthorized). Check COURTLISTENER_API_TOKEN."
    op_resp.raise_for_status()
    results = op_resp.json().get("results", [])
    if not results:
        return f"No opinion text found for cluster_id {cluster_id}."

    preferred_types = ["combined-opinion", "lead-opinion", "majority", "unanimous-opinion"]
    opinion = next(
        (o for t in preferred_types for o in results if o.get("type") == t),
        results[0],
    )
    raw = (
        opinion.get("html_with_citations")
        or opinion.get("plain_text")
        or opinion.get("html")
        or opinion.get("html_lawbox")
        or opinion.get("html_columbia")
        or opinion.get("xml_harvard")
        or opinion.get("html_anon_2020")
        or ""
    )
    text = BeautifulSoup(raw, "html.parser").get_text("\n", strip=True) if raw else ""
    if not text:
        return f"Opinion text not available in a readable format for cluster_id {cluster_id}."

    max_chars = 6000
    truncated = len(text) > max_chars
    text = text[:max_chars]
    suffix = "\n\n[...truncated; read the full opinion on courtlistener.com...]" if truncated else ""
    return f"{text}{suffix}"


@mcp.tool()
def lookup_legal_term(term: str) -> str:
    """Look up a legal term's definition in Cornell Law School's Wex dictionary.

    Args:
        term: The legal term to define, e.g. "tort" or "habeas corpus".

    Tries the term's direct Wex page first; if not found, browses Wex's
    alphabetical index for the closest matching term.
    """
    slug = _slugify(term)
    if not slug:
        return f"'{term}' doesn't look like a valid search term."

    direct_url = f"{CORNELL_WEX_BASE}/{slug}"
    status, html = _fetch_wex_page(direct_url)
    if status == 200:
        return _format_wex_page(html, direct_url)

    first_letter = next((c for c in term.strip().lower() if c.isalpha()), None)
    if first_letter is None:
        return f"Could not find a Wex definition for {term!r}."

    browse_url = f"{CORNELL_WEX_BASE}/all/{first_letter}"
    browse_status, browse_html = _fetch_wex_page(browse_url)
    if browse_status != 200:
        return f"Could not find a Wex definition for {term!r}, and couldn't browse the index either."

    soup = BeautifulSoup(browse_html, "html.parser")
    candidates: dict[str, str] = {}
    for a in soup.select("li a[href^='/wex/']"):
        label = a.get_text(strip=True)
        href = a.get("href")
        if label and href:
            candidates[label.lower()] = href

    if not candidates:
        return f"Could not find a Wex definition for {term!r}."

    matches = difflib.get_close_matches(term.lower(), candidates.keys(), n=1, cutoff=0.6)
    if not matches:
        suggestions = ", ".join(list(candidates.keys())[:8])
        return (
            f"No exact Wex page found for {term!r}. Terms starting with '{first_letter}' "
            f"include: {suggestions}, ... See {browse_url} for the full list."
        )

    best = matches[0]
    match_url = "https://www.law.cornell.edu" + candidates[best]
    match_status, match_html = _fetch_wex_page(match_url)
    if match_status != 200:
        return f"Found a likely match ('{best}') but couldn't load it: {match_url}"

    return _format_wex_page(match_html, match_url, note=f"(No exact page for {term!r}; closest match was '{best}'.)")


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
