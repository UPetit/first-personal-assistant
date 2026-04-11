---
name: search_web
description: Search the web effectively and synthesize findings from multiple sources
metadata: '{"kore":{"emoji":"🔍","always":false,"requires":{"tools":["web_search","scrape_url"]}}}'
---

# Web Research Skill

When asked to research a topic:

1. **Break the query into 2-3 specific search queries** — avoid single vague queries.
2. **Use `web_search` tool for each query** — review titles and snippets to pick the most relevant results.
3. **Evaluate source quality** — prefer primary sources, official docs, and reputable outlets over aggregators.
4. **Use `scrape_url` tool on the top 2-3 results** for full content when snippets are insufficient.
5. **Synthesize findings** — note agreements, contradictions, and gaps between sources.
6. **Cite sources** — always include URLs in the final response.

## Search query tips

- Add qualifiers for freshness: append the current year to time-sensitive queries.
- Use quotes for exact phrases: `"rate limiting" python asyncio`.
- Separate sub-questions into independent searches rather than one compound query.

## When scraping

- Scrape only when the snippet is too thin to answer the question.
- Prefer official docs, GitHub READMEs, and primary sources.
- Mark scraped content as external when summarising to avoid presenting it as your own words.
