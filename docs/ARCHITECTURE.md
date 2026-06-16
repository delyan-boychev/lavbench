# LavBench Architecture

## System Overview

```
Browser (React) → Nginx (port 80) → Flask API (port 5001)
                                        ├── PostgreSQL (users, challenges, tasks, submissions)
                                        ├── Redis (Celery broker, SSE pub/sub, cache, rate limits)
                                        └── Celery Beat (watchdog, backup scheduler)

Celery Workers (host, not Docker):
  start_worker.sh → Redis broker → Docker Sandbox execution → API callback
```

## Components

| Component | Technology | Role |
|-----------|-----------|------|
| **Frontend** | React 19 + Vite + Tailwind 4 | SPA with SSE live updates, i18n (en/bg) |
| **API Server** | Flask + Gunicorn + gevent | REST endpoints, SSE streaming, JWT auth |
| **Database** | PostgreSQL 15 | Users, challenges, tasks, submissions, audit logs |
| **Cache/Broker** | Redis | Celery message broker, SSE pub/sub, caching, rate limiting, token revocation |
| **Task Queue** | Celery | Async job dispatch (evaluation, backups) |
| **Scheduler** | Celery Beat | Watchdog (stuck submissions), automated backups |
| **Worker** | `start_worker.sh` on host | Docker-in-Docker sandbox execution |

## Authentication Flow

```
1. Browser → POST /api/auth/login (username + SHA256(password))
2. Server → verify credentials → generate JWT with jti → set httpOnly cookie
3. Browser → all subsequent requests auto-attach cookie
4. Server → verify_token() → check revocation (Redis) → DB role lookup → authorize
5. Logout → clear cookie + revoke jti in Redis (TTL = remaining token lifetime)
```

## Submission Pipeline

```
1. User uploads .ipynb → POST /api/challenges/<id>/parse-notebook
2. User selects cells → POST /api/challenges/<id>/submit
3. Server: AST validation → rate limit check → create Submission → dispatch Celery task
4. Worker: pick up task → fetch HF key from server → preload datasets → Docker build
5. Docker sandbox: --network none, CPU/RAM/PIDs limits → execute student code
6. Worker: read eval_results.json → calculate scores → report to server
7. Server: update Submission → invalidate cache → publish SSE → leaderboard update
```

## SSE Streaming

6 endpoints use Server-Sent Events for real-time updates:

| Endpoint | Data | Triggers |
|----------|------|----------|
| `/api/tasks/<id>/leaderboard/live` | Full leaderboard JSON | Submission status change, manual points |
| `/api/tasks/<id>/submissions/live` | Submission list | New submission, status change |
| `/api/submissions/<id>/logs/live` | Execution log lines | New log output from worker |
| `/api/admin/workers/stats/live` | Worker cluster status | Worker connect/disconnect |
| `/api/worker-status/live` | Cluster health (navbar) | Worker status change |
| `/api/admin/backups/live` | Backup file list | Backup completion |

## Backup System

| Type | Frequency | Retention | Location |
|------|-----------|-----------|----------|
| **Auto** | Every 20min (active) / 6h (idle) | Latest 6 | `/backups/auto_*.tar.gz` |
| **Manual** | On demand via UI | Never auto-deleted | `/backups/manual_*.tar.gz` |
| **Competition lifecycle** | On deadline, grace end, finalize | Until challenge deleted | `/backups/challenge_{id}/*.tar.gz` |

Contents: `pg_dump` + `uploads/` directory in `.tar.gz`.

## Security Layers

| Layer | Implementation |
|-------|---------------|
| **Auth** | httpOnly cookie + JWT (24h expiry, jti-based revocation) |
| **AuthZ** | Role-based (admin, jury, competitor), DB-backed role lookup |
| **Rate limiting** | Per-user per-endpoint Lua atomic counters |
| **Token revocation** | jti in Redis blacklist with TTL |
| **PII encryption** | Fernet symmetric (optional ENCRYPTION_KEY for rotation) |
| **Sandbox** | Docker --network none, --cpus 2, --pids-limit 64, RAM limit, tmpfs |
| **IP trust** | ProxyFix middleware (trusts X-Forwarded-For from Nginx only) |
| **HF keys** | Fetched on-demand via authenticated API, never in Redis |
