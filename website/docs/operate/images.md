---
sidebar_position: 11
---

# Image generation

Create a model with the `image` capability and an `image_price` (cost per image). An OpenAI-compatible image endpoint that returns `b64_json` works. For a dry run without a GPU, the offline demo seeds *Offline demo images*, which returns a synthetic placeholder.

- **Playground:** switch to the **Images** tab, write a prompt, pick a size and a count.
- **API:** `POST /api/images {prompt, model?, n?, size?}`, or the OpenAI-shaped `POST /v1/images/generations`.
- **Workflows:** a `generate_image` step renders its `prompt` template (default `{{input}}`, and earlier step outputs are available) and makes one image.

Sizes are `256x256`, `512x512`, `1024x1024`, `1024x1792` and `1792x1024`, with up to four images per request. The prompt passes the guardrail policy, including the classifier model if one is set, and requests are refused once the day's budget is spent.

Images are stored as artifacts that expire after `NUVORA_ARTIFACT_TTL_DAYS` (default 7, up to 365). `GET /api/artifacts/{id}` serves one to the person who generated it and to administrators only. Every generation is metered and recorded as `image.generated` in the audit chain.
