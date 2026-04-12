---
name: search-topic-online
description: Research any topic online — searching, browsing URLs, and scraping pages — then synthesise findings
metadata: '{"kore":{"emoji":"🔍","always":true,"requires":{"tools":["web_search","scrape_url", "get_current_time"]}}}'
---

# Web Research Skill

Use this skill for any task that requires accessing information online — whether that means searching for topics, browsing a specific URL, or reading full article content.

## Hard limits

- **Search budget: 5 `web_search` calls for the entire task.** Every call counts — including follow-up searches for context about URLs already found. When the budget is spent, stop and synthesise.
- `scrape_url` is free — use it as many times as needed without restriction.

## Synthesise from what you have

Search snippets are often sufficient — you do not need to scrape or search further to answer. If the snippets contain the answer, synthesise directly. Only spend more calls when a snippet is genuinely too thin to answer the question.

## Workflow

1. **Call `get_current_time`** before any search — use the result to qualify time-sensitive queries with the correct year and date.
2. **Try `scrape_url` first** if the instruction gives a specific URL.
3. **Run targeted `web_search` queries** within your budget — use the current date for freshness, specific terms, and quotes for phrases.
4. **Scrape results** as needed when snippets lack enough detail.
5. **Synthesise** what you found — note gaps, contradictions, and source quality.
6. **Cite sources** — always include URLs in the response.

## Search query tips

- Use the exact date from `get_current_time` in time-sensitive queries — never guess the year.
- Use quotes for exact phrases. Example: `"rate limiting" python asyncio`.
- Separate sub-questions into independent queries rather than one compound search.
