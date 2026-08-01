# Legal Research Agent

A small [MCP](https://modelcontextprotocol.io) server that gives students a
Claude-based research assistant backed by **real, citable, free legal
sources** — no Westlaw/Lexis login required:

- **[CourtListener](https://www.courtlistener.com)** (run by the nonprofit
  [Free Law Project](https://free.law)) — full-text US case law search and
  opinion text.
- **[Cornell Law School's Wex](https://www.law.cornell.edu/wex)** — a free,
  authoritative legal dictionary/encyclopedia.

Students connect to it as a **remote connector** in Claude.ai — no local
install, no API keys of their own. You (the instructor) host one server;
every student in the class points Claude at the same URL.

## Tools it exposes

| Tool | What it does |
|---|---|
| `search_case_law(query, court, filed_after, filed_before, max_results)` | Searches CourtListener's case law index. Returns case name, citation, court, date, a snippet, a link to the full case, and a `cluster_id`. |
| `get_opinion_text(cluster_id)` | Fetches the full opinion text for a case found via `search_case_law`. **Requires a free CourtListener API token** (see below) — without one it tells the student to use the link instead. |
| `lookup_legal_term(term)` | Looks up a term in Cornell's Wex dictionary. Tries the exact page first, then falls back to browsing Wex's alphabetical index for the closest match (handles typos/variants). |

Every response includes its source URL so students can (and should) verify
and cite the original.

## 1. Run it locally first (sanity check)

```bash
cd law
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

This starts a Streamable HTTP server on `http://127.0.0.1:8000/mcp`. This
step is just to confirm it boots on your machine — students won't run this
themselves.

## 2. Deploy it somewhere it can stay running

Students need a stable URL, so this needs a real (if tiny) host — GitHub
Pages alone can't run a Python process. **Render's free tier** is the
easiest option and needs no code changes:

1. Push this repo to GitHub (see below).
2. In [Render](https://render.com), **New > Blueprint**, point it at your
   GitHub repo — it will read `render.yaml` and configure everything.
   (Or: **New > Web Service**, build command `pip install -r requirements.txt`,
   start command `python server.py`.)
3. Deploy. Render gives you a URL like `https://legal-research-agent.onrender.com`.
4. Your MCP endpoint is that URL **plus `/mcp`**:
   `https://legal-research-agent.onrender.com/mcp`

Note: Render's free tier sleeps after inactivity, so the first request after
a quiet period takes ~30-50 seconds to wake up. Fine for a classroom tool;
worth mentioning to students so they don't think it's broken.

### Getting a free CourtListener API token (recommended)

Unauthenticated search works out of the box at a low rate limit — fine for
trying it out, risky for a whole class hitting it during an assignment.

1. Create a free account at [courtlistener.com](https://www.courtlistener.com).
2. Go to your profile settings > **API** and copy your token.
3. In Render, go to your service > **Environment** > add
   `COURTLISTENER_API_TOKEN` = your token. Redeploy.

This also unlocks `get_opinion_text` (full opinion text requires auth on
CourtListener's side regardless of rate limit).

## 3. Push to GitHub

```bash
git remote add origin https://github.com/<your-username>/legal-research-agent.git
git push -u origin main
```

(Nothing sensitive is in this repo — the token lives only in Render's
environment variables, never in git, per `.gitignore`.)

## 4. Give students the connector URL

In Claude.ai: **Settings > Connectors > Add custom connector**, paste your
`/mcp` URL from step 2. Once connected, students can ask things like:

> "Find the case where the Supreme Court established the Miranda warning
> requirement, and give me the citation."

> "What's the legal definition of promissory estoppel?"

## Limitations students should know

- CourtListener is a large, reputable, but not-exhaustive free database —
  it doesn't have everything Westlaw/Lexis has, especially older or
  obscure state cases.
- This is a **research aid, not legal advice** and not a substitute for
  reading the actual opinion — always click through to the source.
- Wex is Cornell's own reference material, written for public education;
  it's a great starting definition, not a substitute for a case-specific
  legal argument.
