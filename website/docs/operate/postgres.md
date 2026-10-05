---
sidebar_position: 2
---

# PostgreSQL and replicas

SQLite stays the default: no extra service, one file, one process. Set `NUVORA_DATABASE_URL` to run on PostgreSQL 13 or later and scale to several replicas. This needs the `postgres` extra (`psycopg`), which the container image includes.

```bash
export NUVORA_DATABASE_URL='postgresql://nuvora:…@db.internal:5432/nuvora?sslmode=require'
python3 -m nuvora.server --host 0.0.0.0 --tls-cert … --tls-key …
```

## What changes with PostgreSQL

- **Schema:** created on first start and tracked in `schema_version`. Replicas that start together migrate one at a time under an advisory lock. A database newer than the running code is refused.
- **Jobs:** each job is claimed with `SELECT … FOR UPDATE SKIP LOCKED`, so exactly one replica runs it. Workers heartbeat every 10 seconds. A job left `running` by a replica that hasn't been seen for 45 seconds becomes `interrupted` for review. It is never replayed automatically.
- **Audit chain:** appends take a per-tenant transaction-scoped advisory lock, so concurrent replicas can't fork the hash chain.
- **Login throttling:** failed attempts live in the database, so the limit of 10 per 5 minutes holds across replicas.
- **Still per process:** the in-flight concurrency limit (four calls per user) and the daily token budget reservation for calls in progress. The budget check itself reads the shared usage ledger.

## Helm

```bash
kubectl create secret generic nuvora-db --from-literal=url='postgresql://nuvora:…@db:5432/nuvora?sslmode=require'
helm upgrade --install nuvora deploy/helm \
  --set database.urlSecret=nuvora-db --set replicas=3
```

With `database.urlSecret` set, the chart:
- drops the PVC
- switches to a `RollingUpdate` (`maxUnavailable: 0`)
- injects `NUVORA_DATABASE_URL`

Rendering refuses `replicas > 1` without PostgreSQL. It also refuses SSO with several replicas unless `oidc.clientSecret` is set, because every replica must verify the same login-state signature.

## Move from SQLite

Stop Nuvora, create an empty database, then:

```bash
pip install 'zyvor-nuvora[postgres]'
NUVORA_DATABASE_URL=postgresql://… python3 scripts/migrate-sqlite-to-postgres.py /data/nuvora.db
```

The copy:
- runs in one transaction
- keeps audit sequence numbers, and continues the sequence after them
- verifies every tenant's audit chain before it commits
- refuses a target that already holds Nuvora data

Use `--dry-run` to count rows first.

## Backups

Use your PostgreSQL tooling (`pg_dump`, WAL archiving or managed snapshots). The database holds documents, prompts, job evidence, password hashes and token digests: encrypt it at rest and in transit (`sslmode=require` or stronger).
