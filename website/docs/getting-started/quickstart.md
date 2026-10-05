---
sidebar_position: 1
---

# Quickstart

Nuvora is one Python process that serves both the API and a prebuilt React console. The offline demo needs only Python 3.11 or newer: no GPU, cluster, `pip install`, or hosted model.

```bash
git clone https://github.com/zyvorai/zyvor-nuvora.git
cd zyvor-nuvora
export NUVORA_ADMIN_PASSWORD='choose-your-own-strong-password'
python3 -m nuvora.server --demo
```

Open **http://127.0.0.1:8789** and sign in as `admin` with the password from your environment. The workspace is `default`; to use another one, choose **Change** under the sign-in button.

:::note
- The first start creates the administrator. Changing the variable later doesn't reset the password.
- Locally, the password needs 12–256 characters.
- The k3s deploy script uses the demo password `Admin@321` instead; see [Deploy to k3s](./deploy.md).
:::

![Sign in](/00-login.png)

## What the demo seeds

`--demo` seeds the following once, when no models exist yet:
- a synthetic model, labeled **OFFLINE DEMO** on every answer
- a knowledge base (*Zyvor field guide*)
- an investigator agent
- a *Research → review → answer* workflow with an approval step
- a prompt, an evaluation suite, and an external-training recipe

## Five-minute tour

1. Open **Workspace → Playground**, choose *Zyvor field guide* as grounding, and ask about Keep. The answer comes back with the retrieved passages and their content digests.
2. Open **Build → Agents**, select the investigator, and run it. Follow the run in **Operate → Runs**, where every step is in view.
3. Open **Build → Workflows** and start *Research → review → answer*. It pauses at its approval step.
4. In **Govern → Access**, add a second person with the `approver` role. Sign in as that person and approve the exact action in **Govern → Approvals**.
5. The worker resumes the pinned workflow revision. Open **Govern → Evidence** and verify the chain.

![Overview](/01-overview.png)

## Develop

```bash
make check     # backend tests, console tests, console build
```

The console source lives in `web/`. `make check` rebuilds it into `nuvora/static/`, so the Python-only quickstart keeps working.
