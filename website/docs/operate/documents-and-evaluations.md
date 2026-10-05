---
sidebar_position: 4
---

# Documents, retrieval and evaluations

## Upload documents

Drop files on a knowledge base, or call `POST /api/knowledge/{id}/upload {name, content_type, content_base64}`.

| Type | Extraction |
|---|---|
| Text, Markdown, CSV, JSON | Decoded as UTF-8 |
| HTML | Visible text only; `script` and `style` are dropped |
| Word `.docx` | Paragraphs from the document XML (standard library) |
| PDF | Text layer through `pypdf` (the `pdf` extra, bundled in the image); no OCR |

Files can be up to 20 MB each, and extracted text is capped at 500,000 characters. An unknown type returns 415, an oversized file 413, an unreadable file 422, and a missing PDF extra 503.

`GET /api/knowledge/{id}/documents` lists documents with their type, size, chunk count and digest. `DELETE /api/documents/{id}` (developer or admin) removes a document and its chunks. Deleting a knowledge base removes its documents too.

## Retrieval

- **Default:** offline retrieval fuses BM25 with hashed lexical vectors. Tokens are lower-cased, common stopwords dropped, and light suffix stemming applied, so `agents` matches `agent`.
- **Semantic option:** set `embedding_model` to an OpenAI-compatible or Ollama (`/api/embed`) embedding model.
- **Rerank option:** set `rerank_model` to a chat model. Nuvora retrieves the top 20, asks the model to score each passage from 0 to 10, and keeps the best `top_k`. If the model answers badly, the fused order stands.

A recall fixture in `tests/fixtures/retrieval.json` runs in CI and checks that recall@1 stays at or above 0.75 for both BM25 and hybrid retrieval.

## Evaluation cases

Each case can combine three checks. All of a case's checks must pass for the case to pass:

```json
{"input": "How does Keep isolate agents?",
 "contains": ["microVM"], "excludes": ["container escape"],
 "judge": {"criteria": "Explains isolation without inventing features", "min_score": 0.7},
 "grounded": true}
```

- **Assertions:** `contains` and `excludes`, case-insensitive.
- **LLM judge:** `judge_model`, or the model under test, returns `{"score": 0–1, "reason": …}`. Malformed output scores 0 and is flagged as such, rather than passing silently.
- **Grounded:** retrieves from the suite's `knowledge_ids`, answers from that evidence only, then judges whether every claim is supported (minimum 0.7).

Edit cases in the visual **Case editor**, or as JSON. The run inspector shows a per-case table with assertion results, judge score and reason, and groundedness with its passage count. The offline demo model gives a synthetic keyword-overlap score labelled as such. It isn't a model judgment.
