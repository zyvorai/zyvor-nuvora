---
sidebar_position: 5
---

# Guardrails

A guardrail policy is a workspace resource, edited in **Govern → Guardrails** or with `POST /api/policies`. Nuvora checks the input before a model sees it and the output before a person does. Streamed answers are released sentence by sentence after the check, or held until the end when the policy needs the whole answer (a classifier model or a grounding threshold).

## Filters

| Field | What it does |
|---|---|
| `blocked_topics` | Phrases that block a request or answer outright |
| `word_filters` | Up to 200 whole words or phrases, matched case-insensitively |
| `regex_filters` | Up to 20 `{name, pattern, action}` entries. `action` is `block` or `mask` (replaces the match with `[NAME]`). Nested quantifiers are rejected to avoid catastrophic backtracking |
| `detect_injection` | Blocks common instruction-override phrases (on by default) |
| `max_chars` | Size limit for a single text |

## Sensitive information

`pii_entities` maps each entity to `mask` or `block`:

| Entity | Detection |
|---|---|
| `email` | Address pattern |
| `card` | 13–19 digits that pass the Luhn checksum |
| `iban` | Country code and digits that pass the ISO 13616 mod-97 check |
| `ssn` | US social security number format |
| `ipv4` | A valid IPv4 address |
| `phone` | International and national number formats |

Masked values become `[EMAIL]`, `[CARD]`, `[IBAN]` and so on. Without `pii_entities`, the older `redact_pii` switch masks emails and long account numbers.

## Contextual grounding

Set `grounding_threshold` (0–1) and every answer generated from retrieved sources is scored by how much of each sentence's content appears in those sources. Answers under the threshold are blocked, and `/api/answer` returns the score. It's a lexical check that catches answers drifting away from the evidence, not a proof of correctness.

## Classifier model

Point `classifier_model` at a chat model and choose `classifier_categories` from `hate`, `violence`, `sexual`, `self_harm`, `misconduct` and `prompt_attack`. Content flagged at or above `classifier_threshold` (default 0.5) is blocked. If the classifier fails or returns something unreadable, the request is blocked: it fails closed. Classifier calls are metered like any other model call.

## Caching

`cache_ttl` (30–86400 seconds, default 300) controls how long identical requests are answered from cache. Cached answers cost nothing and show up as cache hits in **Usage**.

## Try a policy

```bash
curl -s https://nuvora.example.com/api/guardrails/check \
  -H "Authorization: Bearer $NUVORA_TOKEN" -H 'Content-Type: application/json' \
  -d '{"text": "Card 4111 1111 1111 1111, mail ops@example.com"}'
```

The verdict lists `reasons`, the transformed `text`, `pii_found` and, when you pass `sources`, a `grounding` score. Every policy change is versioned and lands in the audit chain.
