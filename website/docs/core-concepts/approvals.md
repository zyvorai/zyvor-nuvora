---
sidebar_position: 2
---

# Agents, workflows and approvals

![Agents propose, people decide](/readme-approvals.jpg)

## Agents

An agent runs a bounded model-and-tool loop, capped at 20 steps, over a closed registry of typed tools.
- There's no shell and no unrestricted HTTP tool.
- Read tools run directly.
- Memory writes and external actions are staged for approval.

## Workflows

A workflow is a validated DAG of steps: `retrieve`, `generate`, `template`, `condition`, `extract`, `action`, `approval`, and `handoff`.
- A `handoff` sends a proposal to Zyntra and waits as `waiting_external` until Zyntra's approvers decide. See [integrations](../operate/integrations.md).
- Each completed step writes a durable checkpoint.
- A run is pinned to the workflow revision it started with.

## Connectors & actions

An administrator registers typed enterprise APIs.
- `GET` calls run as reads. Don't register a `GET` endpoint that changes state.
- `POST` calls are always staged as an exact-action approval.
- Model providers and actions share the same host allow-list and credential-reference rules.

## Approvals

When a step needs a human, Nuvora records:
- the exact action and its arguments
- a sha256 fingerprint of the action
- the proposer and an expiry

Only a **different** authenticated person with the `approver` or `admin` role can decide. The console disables self-approval, and the API refuses it with `403 A different person must approve`.

The decision checks the fingerprint and the job checkpoint atomically. The worker then resumes the job on its pinned revision. Automatic `POST` retries are intentionally absent.

![Approvals](/07-approvals.png)
