---
name: memory-management
description: When and how to store, update, and retrieve memories across conversations
metadata: '{"kore":{"emoji":"🧠","always":true,"requires":{"tools":[]}}}'
---

# Memory Management Skill

This skill is always active. Follow these rules in every conversation.

## When to store memories

Store a memory (via `memory_store`) when you learn:
- A user preference or constraint that will affect future responses
- A fact about an ongoing project, deadline, or goal
- A correction to something previously stored
- The outcome of an important decision

Do **not** store ephemeral task details (current step, draft text) or information easily re-derived from the conversation.

## When to search memories

Before answering questions about the user's context, projects, or preferences, call `memory_search` to retrieve relevant prior knowledge. Always search when:
- The user references "last time", "as we discussed", or "remember when"
- The question is about an ongoing project or recurring task
- You need to personalise a response

## Updating core memory

Use `core_memory_update` to update always-in-context structured facts (user profile, active projects, rules). Prefer updating existing paths over creating new top-level keys. The core memory has a 4,000 token cap — be concise.

## Memory hygiene

- When a stored fact is superseded, note the correction explicitly rather than silently overwriting.
- Do not store the same fact twice — search before storing.
