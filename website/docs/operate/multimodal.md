---
sidebar_position: 9
---

# Images, audio and extraction

## Vision in chat

Mark a model as `vision` and the playground lets you attach images. Over the API, a message's `content` can be a list of parts:

```json
{"role": "user", "content": [
  {"type": "text", "text": "What does this invoice total?"},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]}
```

Up to four PNG, JPEG or WebP images per request, each as a data URL. Text parts still pass the guardrails. OpenAI-compatible, Ollama and AWS providers are supported.

## OCR and transcription

When you upload to a knowledge base:

| Upload | How the text is extracted |
|---|---|
| Image | The knowledge base's `ocr_model` (a vision model), or local Tesseract with the `ocr` extra |
| Scanned PDF | Falls back to OCR when the PDF has no text layer |
| Audio | The knowledge base's `transcription_model`, an OpenAI-compatible model with the `transcription` capability |

Each document records which `extraction` method produced its text. The container image includes Tesseract; elsewhere, install `zyvor-nuvora[ocr]` and the `tesseract` binary.

## Extraction blueprints

`POST /api/extract` turns a document, text or an image into typed fields:

```json
{
  "document_id": "…",
  "fields": {
    "invoice_number": {"type": "string"},
    "total": {"type": "number", "description": "Grand total including tax"},
    "due_date": {"type": "date"}
  },
  "min_confidence": 0.8,
  "review": true
}
```

Field types are `string`, `number`, `integer`, `boolean` and `date`. The job returns each value with a confidence and lists the fields below `min_confidence` (default 0.7). With `"review": true`, such a result waits in an `extraction_review` approval, where a different person sees every value and the low-confidence ones, then approves or rejects the result. Small models sometimes return bare values without a confidence; Nuvora keeps those values at confidence 0, so they always count as low confidence. **Runs** shows the extracted fields as a table.
