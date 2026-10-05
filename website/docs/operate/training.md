---
sidebar_position: 10
---

# Fine-tuning and distillation

Nuvora prepares and governs customization; your own trainer does the GPU work.

## Datasets

`POST /api/datasets {name, content}` stores a JSONL dataset after validating it. Send `dry_run: true` to check it without storing.

| Format | Each line |
|---|---|
| `chat` | `{"messages": [{"role": …, "content": …}, …]}` |
| `completion` | `{"prompt": …, "completion": …}` |
| `prompts` | `{"prompt": …}`, used for distillation |

A dataset needs 10–100,000 records and at most 20 MiB. Every record passes the workspace guardrails, so blocked content never reaches a trainer. Listing datasets never returns their content.

## Recipes

A recipe names a base `model`, a `method` and a `dataset_id`:

| Method | What happens |
|---|---|
| `lora`, `qlora` | The dataset goes to the trainer as is, with `rank` and `epochs` |
| `distillation` | A `teacher_model` answers every prompt first, then the student is trained on those answers |

`POST /api/recipes/{id}/run` starts the job. Without a trainer, `POST /api/recipes/{id}/export` gives you a `TrainingRecipe` to run elsewhere.

## Connect a trainer

```bash
export NUVORA_TRAINER_URL='https://trainer.internal'
export NUVORA_SECRET_TRAINER_TOKEN='…'
# when the trainer doesn't report where the model is served:
export NUVORA_TRAINER_SERVING_URL='https://serving.internal/v1'
export NUVORA_TRAINER_SERVING_KEY_ENV='NUVORA_SECRET_SERVING_KEY'
```

The trainer's host must be on `NUVORA_PROVIDER_HOSTS`. Nuvora calls:

- `POST /v1/training/jobs` with `base_model`, `method`, `hyperparameters`, `dataset` (format, records, digest, content) and `suffix`; it expects an `id` back.
- `GET /v1/training/jobs/{id}` until `status` is `succeeded`, `completed` or `success` (or `failed`, `error`, `cancelled`).

While training, the job waits as `waiting_external`, for up to seven days. When it succeeds, Nuvora registers the result (`result.model` or `fine_tuned_model`) as a new model you can evaluate before anyone uses it.
