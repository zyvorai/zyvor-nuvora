---
sidebar_position: 3
---

# The console

The console follows the Zyvor Apple UX contract shared with Netra:
- light by default, with dark one click away and remembered on the device
- compact page heroes, so data starts in the first screen
- hairline tables, and blue reserved for intent

## Navigation

| Group | Pages |
|---|---|
| **Overview** | Overview |
| **Workspace** | Playground, Models, Knowledge |
| **Build** | Agents, Connectors & actions, Workflows, Prompts, Model studio |
| **Operate** | Runs, Evaluations, Batch inference |
| **Govern** | Approvals, Guardrails, Usage & cost, Evidence, Access |

Every page has a hash URL (`#playground`), so links and the browser back button work. The workspace chip shows `tenant · role`. A dot appears on **Approvals** when a decision is waiting.

## Roles

| Role | Can |
|---|---|
| `viewer` | Read the workspace |
| `developer` | Build and run models, knowledge, agents, workflows, and prompts |
| `approver` | Decide approvals that someone else proposed; doesn't build |
| `admin` | Everything, including people, connectors, and guardrails |

The roles don't inherit from each other. Keeping builders and approvers as separate people is the point.

The console hides or disables controls by role, but the API is the authority.

![Playground in dark mode](/12-playground-dark.png)
