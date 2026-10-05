---
sidebar_position: 6
---

# Routers and caching

## Cascade routers

A router lists 2–5 chat models, cheapest first. Nuvora asks the first model, and moves on to the next when the answer is weak:

- the answer is empty,
- the model says it is unsure or can't answer, or
- a `judge_model` scores the answer below `min_score` (default 0.7).

The last model's answer is always accepted. Answers that call tools are accepted at once, so an agent never repeats a tool call on a stronger model.

```json
{
  "name": "Support cascade",
  "models": ["small-model-id", "large-model-id"],
  "judge_model": "small-model-id",
  "min_score": 0.7
}
```

Use a router anywhere a model is accepted, as `router:<id>`: in the playground, agents, workflows, evaluations and on `/v1/chat/completions`. `/v1/models` lists routers next to models. Every escalated attempt is metered, and the response's `routing` field says which tier answered and after how many escalations. Streaming responses stream from the tier that is finally accepted.

## Prompt caching and cache pricing

- **Response cache:** identical requests within the policy's `cache_ttl` are served from cache at no cost.
- **Provider prompt caching:** when a provider reports cached prompt tokens, Nuvora bills them at the model's `cached_input_price` instead of `input_price`.

**Usage** shows cache hits, cached tokens and the amount saved per day and per model.
