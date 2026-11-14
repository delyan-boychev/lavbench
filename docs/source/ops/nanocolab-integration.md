# LavBench and nanoColab integration contract

This document is the handoff from the LavBench team to the nanoColab team. It specifies every interface between the two systems and every change nanoColab needs, so that the nanoColab work can be planned and built from this document alone.

- **Contract version:** v1. Within v1, changes are additive only: new optional fields, new endpoints. Readers must ignore unknown fields. A breaking change gets a new `/v2` path, served next to v1.
- **Status:** draft for review. LavBench ships the server side in the pull requests named in section 2; the nanoColab side is built by the nanoColab team.
- **Code references:** nanoColab paths are relative to the nanoColab repository at commit `4259262`. LavBench paths are relative to this repository.

## Contents

1. [Scope, priorities and glossary](#1-scope-priorities-and-glossary)
2. [Dependencies](#2-dependencies)
3. [Flows](#3-flows)
4. [Configuration](#4-configuration)
5. [Identity](#5-identity)
6. [Service-to-service tokens](#6-service-to-service-tokens)
7. [Stage spec](#7-stage-spec)
8. [Firestore model](#8-firestore-model)
9. [Stage bag and mirror](#9-stage-bag-and-mirror)
10. [Status and catalog](#10-status-and-catalog)
11. [Workspace file access for LavBench](#11-workspace-file-access-for-lavbench)
12. [Workspace lifecycle](#12-workspace-lifecycle)
13. [Network](#13-network)
14. [Rollback](#14-rollback)
15. [Tests and acceptance](#15-tests-and-acceptance)
16. [Deferred items and open questions](#16-deferred-items-and-open-questions)

## 1. Scope, priorities and glossary

### 1.1 Responsibilities

**LavBench is the single source of truth** for:
- users, roles and the only login, for every role;
- challenges, stages, schedules and time zones;
- rosters;
- tasks, task data, labels and scoring;
- the compute profile of each exported stage, chosen from the nanoColab catalog.

**nanoColab keeps only:**
- infrastructure: the cluster, images and the capacity catalog;
- live workspace runtime state, archives and staging state;
- cached copies of what it pulls from LavBench.

nanoColab stores no student accounts and no passwords. Scoring happens only in LavBench.

### 1.2 Priorities

Everything in the MUST column is needed for the April 2027 selection. LATER items are designed here only so that MUST work does not block them.

| MUST for April | LATER |
|---|---|
| Identity: Hub sign-in through LavBench (section 5) | Per-user revoke (`user_revocations`, section 16) |
| Stage sync (section 7) | The `s2s_jti` replay store on nanoColab (section 6.4) |
| Bag mirror and staging (section 9) | Blocking external DNS for student pods |
| Hub service and scopes for the LavBench file picker (section 11) | Archive access for LavBench over S2S |
| Workspace window, with culling off (section 12) | Structured JSON logs |
| pyarrow pinned in every workspace image (section 12) | ruff and mypy in nanoColab CI, pinned dependencies |
| The rollback flag (section 14) | i18n of Hub error pages |
| Status push and catalog push (section 10) | Deleting the portals and the legacy account code |

Until revoke ships, a student removed from a challenge in LavBench keeps their workspace until the stage ends, but can no longer submit.

### 1.3 Glossary

| Term | Meaning |
|---|---|
| Challenge | A LavBench competition, with a roster of competitors and one or more stages |
| Stage | A time window of a challenge with its own tasks. **One exported LavBench stage is one nanoColab competition.** The nanoColab competition id equals the LavBench stage id. |
| Kind | `test` (a warm-up stage, `Stage.is_test`) or `official`. nanoColab runs both as `OFFICIAL` internally; the kind only drives labels and display. |
| Exported stage | A stage the LavBench admin has marked for nanoColab. Only exported stages appear in the stage spec. |
| Task slug | The stable key of a task inside a challenge, `[a-z0-9]+(-[a-z0-9]+)*`, at most 48 characters. `starter` is reserved. |
| Bag | The read-only data of one stage, as a BagIt bag (RFC 8493), served by LavBench and mirrored by nanoColab |
| Digest | `sha256:<64 lowercase hex>`, as in the OCI image spec |
| Generation / observedGeneration | The Kubernetes spec/status pattern: LavBench increments `generation` whenever a stage item changes; nanoColab reports the generation it last applied |
| Workspace export | A nanoColab archive of a student's `/workspace` after a stage. Not to be confused with an "archived challenge" in LavBench, which is a hidden challenge. |
| Hub username | `lb-<LavBench user UUID>`, lowercase. Real names and LavBench usernames never reach the Hub. |

## 2. Dependencies

There are no dates in this document; the timeline is agreed between the teams separately. The order of work is:

| LavBench delivers (pull request) | What it unblocks in nanoColab | How nanoColab checks it |
|---|---|---|
| This document (`docs/nanocolab-contracts`) | Planning; the authenticator subclass; the sync client against fixtures | Review |
| `feat/identity-oidc`: OIDC provider, S2S verifier, stage export fields, `GET /api/nanocolab/v1/stages` with `bundle: null` | Hub sign-in (section 5); sync client (section 7) | A test student signs in to a staging Hub; the sync client applies a test stage |
| `feat/nanocolab-sync`: bag and bundle routes, the status and catalog receivers, the profile image rule | Mirror and staging (section 9); status and catalog push (section 10) | A test stage is mirrored, staged and started; LavBench shows the nanoColab row |
| `feat/workspace-picker`: the LavBench side of the file picker | Hub service and scopes (section 11) | A student submits `submission.parquet` from the workspace through LavBench |

Two full rehearsals through a practice stage follow, before the code freeze and before the selection.

## 3. Flows

### 3.1 Student sign-in and spawn

1. The student signs in to LavBench (username and password) and opens a task.
2. The student clicks **Open workspace**. It is a plain link to `https://lab.noai-bg.com/hub/oauth_login?next=/hub/spawn`.
3. The Hub (`LavBenchAuthenticator`, section 5.2) redirects the browser to `https://bench.noai-bg.com/api/oidc/authorize` with a `state` value and a PKCE `S256` challenge.
4. LavBench sees the LavBench session cookie. The two hosts are same-site, so the `SameSite=Strict` cookie is sent. If there is no session, LavBench shows its login page and continues afterwards.
5. LavBench checks that the user is a competitor whose challenge has an exported stage that is open now (`start <= now <= end + graceSeconds`). If so it redirects back to `/hub/oauth_callback` with a code; otherwise with `error=access_denied`.
6. The Hub exchanges the code at `/api/oidc/token` and reads the claims from the id_token (section 5.1).
7. The authenticator calls the control API `POST /internal/hub-logins` (section 5.3), which creates the workspace document idempotently and returns the same payload as today's launch-token consume.
8. `check_allowed` runs unchanged on that `auth_state`, the spawner starts the workspace through the controller, and the student lands in JupyterLab.

The student never sees a second login. LavBench is never called by the Hub after sign-in, so running sessions survive a LavBench outage.

### 3.2 Stage sync, mirror and staging

1. Every minute, in the existing dispatcher tick, nanoColab calls `GET /api/nanocolab/v1/stages` with `If-None-Match` (section 7). On `304` nothing happens.
2. On `200`, each item is validated and applied to its competition document. Items that fail validation or the freeze rules are rejected and the last-known-good copy is kept (section 7.6).
3. When an item carries a bundle digest that is not yet mirrored, the mirror job copies the bag into the assets bucket and verifies it (section 9.3).
4. Before the stage starts, event startup stages the mirrored bag onto a read-only disk and starts the competition as today, with the image from the stage profile (section 9.4).

### 3.3 Workspace pick and submit (LavBench side, for context)

1. The student opens the LavBench submit panel and chooses **From workspace**.
2. LavBench checks the Hub server status once, lists `.parquet` and `.ipynb` files through the Hub proxy with a read-only service token, and shows them (section 11).
3. On submit, LavBench streams the chosen files through the Hub proxy, checks size, mtime and hash before and after the copy, stores its own copy and scores it.

LavBench never starts or stops a server and never polls the Hub.

### 3.4 Status and catalog push

Every minute, in the same dispatcher tick, nanoColab sends `PUT /api/nanocolab/v1/status` and `PUT /api/nanocolab/v1/catalog` (section 10). LavBench shows the nanoColab row in its admin panel and marks it "unknown" when the last report is older than 3 minutes.

## 4. Configuration

All URLs and identifiers are configurable on both sides. The defaults below are the intended production values.

### 4.1 nanoColab settings

| Setting | Default | Used by |
|---|---|---|
| `NANOCOLAB_IDENTITY_MODE` | `lavbench` (`legacy` keeps today's flow, section 14) | Cluster bootstrap, Hub config, sync |
| `LAVBENCH_URL` | `https://bench.noai-bg.com` | Everything below |
| `LAVBENCH_OIDC_ISSUER` | `${LAVBENCH_URL}/api/oidc` | Hub authenticator |
| `LAVBENCH_OIDC_CLIENT_ID` | `nanocolab-hub` | Hub authenticator |
| `LAVBENCH_OIDC_CLIENT_SECRET` | secret (Secret Manager) | Hub authenticator |
| `LAVBENCH_SYNC_BASE_URL` | `${LAVBENCH_URL}/api/nanocolab/v1` | Sync, mirror, status and catalog push |
| `NANOCOLAB_S2S_PRIVATE_KEY` | secret (Secret Manager), Ed25519 PEM | Signing S2S tokens (section 6) |
| `NANOCOLAB_S2S_KEY_ID` | RFC 7638 thumbprint of the public key | `kid` header |
| `LAVBENCH_HUB_SERVICE_TOKEN` | secret (Secret Manager) | `hub.services.lavbench.apiToken` (section 11) |

### 4.2 LavBench settings that must match

| LavBench setting | Value agreed with nanoColab |
|---|---|
| `OIDC_CLIENTS_JSON` | `[{"client_id": "nanocolab-hub", "client_secret_hash": "<hash of LAVBENCH_OIDC_CLIENT_SECRET>", "redirect_uris": ["https://lab.noai-bg.com/hub/oauth_callback"]}]`. Redirect URIs are matched exactly. |
| `NANOCOLAB_JWKS_URL` | The public URL of nanoColab's JWKS (section 6.3) |
| `NANOCOLAB_S2S_ISSUER` | `nanocolab` |
| `LAVBENCH_S2S_AUDIENCE` | `lavbench-api` |
| `JUPYTERHUB_URL` | `https://lab.noai-bg.com` |
| `JUPYTERHUB_API_TOKEN` | The same value as `LAVBENCH_HUB_SERVICE_TOKEN` |
| `JUPYTERHUB_USER_PREFIX` | `lb-` |
| `NANOCOLAB_EXPORT_LEAD_HOURS` | `24`. The freeze window before a stage starts (section 7.5). |
| `DEADLINE_GRACE_PERIOD_SECONDS` | `180`. Sent as `window.graceSeconds`. |

### 4.3 Infrastructure (Terraform)

- **Secret Manager:** the OIDC client secret, the nanoColab S2S private key and the Hub service token. All three must survive a cluster rebuild, so they are read at bootstrap rather than generated (`scripts/cluster-bootstrap.sh` regenerates keys today, lines 145-147).
- **Cloud Scheduler:** the dispatcher tick every minute. Today it runs every 5 minutes (`infra/terraform/environments/staging/automation/main.tf:179`).
- **Node pool:** at most 100 nodes per competition, because a read-only pd-ssd can be attached to at most about 100 nodes (section 9.4). Use larger nodes rather than more nodes.
- **Artifact Registry:** grant the LavBench worker service account read access to the CPU image repository. LavBench grades notebook-mode tasks in the same image the students use.
- **Firestore TTL policy:** only needed LATER, for `s2s_jti` (section 6.4).

## 5. Identity

### 5.1 The LavBench OIDC provider

LavBench runs a minimal OpenID Connect provider (Authlib) with exactly one client, the Hub.

| Item | Value |
|---|---|
| Issuer | `https://bench.noai-bg.com/api/oidc` |
| Discovery | `https://bench.noai-bg.com/api/oidc/.well-known/openid-configuration` |
| Authorization endpoint | `/api/oidc/authorize` |
| Token endpoint | `/api/oidc/token` |
| JWKS | `/api/oidc/jwks` (RS256 key, with `alg` and `use: "sig"`) |
| UserInfo | none. The Hub reads the id_token (`userdata_from_id_token`). |
| Flow | Authorization code with PKCE. `code_challenge_method=S256` is required. |
| Client authentication | `client_secret_basic` and `client_secret_post` |
| Scopes | `openid` |
| id_token signing | RS256, lifetime 5 minutes |
| `prompt` | `none` (returns `login_required` without a session) and `login` |
| Not supported | Refresh tokens, consent screen, dynamic registration, `max_age`/`auth_time`. `display`, `ui_locales` and `acr_values` are accepted and ignored. |
| Token response | `access_token` (opaque, not usable for anything), `token_type`, `expires_in`, `id_token` |
| Errors | RFC 6749: the authorization endpoint redirects with `error=access_denied`, `login_required` or `invalid_request`; the token endpoint returns `{"error": "invalid_grant", "error_description": "..."}` |

**id_token claims:**

| Claim | Example | Meaning |
|---|---|---|
| `iss` | `https://bench.noai-bg.com/api/oidc` | Issuer |
| `aud` | `nanocolab-hub` | Client id |
| `sub` | `0193a5f2-6c1e-7d4a-9b2f-3e8d1c0a4b5f` | LavBench user UUID, stable for life |
| `preferred_username` | `lb-0193a5f2-6c1e-7d4a-9b2f-3e8d1c0a4b5f` | The Hub username |
| `challenge_id` | UUID | The student's challenge |
| `stage_id` | UUID | The open exported stage. Exported stages of one challenge never overlap, so there is at most one. Equals the nanoColab competition id. |
| `locale` | `bg` or `en` | The student's LavBench UI language (OIDC Core 5.1) |
| `iat`, `exp` | Unix seconds | Issued at, expiry |
| `nonce` | as sent | Only when the request carries one |

`amr` is not sent: only competitors can sign in to the Hub, and LavBench enforces MFA for admin and jury inside LavBench.

### 5.2 Hub authenticator

The z2jh 4.4.0 hub image (`quay.io/jupyterhub/k8s-hub:4.4.0`) ships JupyterHub 5.5.0 and oauthenticator 17.4.0 (`images/hub/requirements.txt` at tag 4.4.0). Use `GenericOAuthenticator`: in 17.4.0 it does not read Discovery, so the endpoint URLs are set explicitly. `userdata_from_id_token` exists since 16.3.0, and `enable_pkce` since 17.1.0 with default `True`.

Replace `NanoColabLaunchTokenAuthenticator` (`jupyter/hub/nanocolab_authenticator.py:55-111`) with a subclass that keeps today's `check_allowed` and managed-server routes. The sketch below shows the intended shape; verify the method signatures against oauthenticator 17.4.0.

```python
"""JupyterHub authenticator that signs students in through LavBench (OIDC)."""

import httpx
from oauthenticator.generic import GenericOAuthenticator
from traitlets import Unicode

from nanocolab_server_handler import ManagedServerAPIHandler


class LavBenchAuthenticator(GenericOAuthenticator):
    control_api_url = Unicode(config=True)
    service_token = Unicode(config=True)

    async def authenticate(self, handler, data=None):
        user = await super().authenticate(handler, data)
        if not user:
            return None
        claims = user["auth_state"][self.user_auth_state_key]  # The id_token claims
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{self.control_api_url.rstrip('/')}/internal/hub-logins",
                headers={"Authorization": f"Bearer {self.service_token}"},
                json={
                    "sub": claims["sub"],
                    "challenge_id": claims["challenge_id"],
                    "stage_id": claims["stage_id"],
                },
            )
        if response.status_code != 200:
            return None
        payload = response.json()
        if payload["jupyterhub_username"] != user["name"]:
            return None
        user["auth_state"].update(
            workspace_id=payload["workspace_id"],
            competition_id=payload["competition_id"],
            workspace_kind=payload["workspace_kind"],
            workspace=payload["workspace"],
        )
        return user

    async def check_allowed(self, username, auth_model):
        # Port of NanoColabLaunchTokenAuthenticator.check_allowed, unchanged
        ...

    async def refresh_user(self, user, handler=None, **kwargs):
        # Never call LavBench after sign-in: sessions must survive a LavBench outage
        return True

    def get_handlers(self, app):
        return super().get_handlers(app) + [
            (r"/api/users/([^/]+)/server", ManagedServerAPIHandler),
            (r"/api/users/([^/]+)/servers/([^/]*)", ManagedServerAPIHandler),
        ]
```

Hub configuration (`jupyter/hub/values.yaml`, `extraConfig.10-nanocolab`), when `NANOCOLAB_IDENTITY_MODE=lavbench`:

```python
issuer = os.environ["LAVBENCH_OIDC_ISSUER"].rstrip("/")
c.JupyterHub.authenticator_class = LavBenchAuthenticator
c.LavBenchAuthenticator.client_id = os.environ["LAVBENCH_OIDC_CLIENT_ID"]
c.LavBenchAuthenticator.client_secret = os.environ["LAVBENCH_OIDC_CLIENT_SECRET"]
c.LavBenchAuthenticator.oauth_callback_url = "https://lab.noai-bg.com/hub/oauth_callback"
c.LavBenchAuthenticator.authorize_url = f"{issuer}/authorize"
c.LavBenchAuthenticator.token_url = f"{issuer}/token"
c.LavBenchAuthenticator.scope = ["openid"]
c.LavBenchAuthenticator.userdata_from_id_token = True
c.LavBenchAuthenticator.username_claim = "preferred_username"
c.LavBenchAuthenticator.enable_pkce = True
c.LavBenchAuthenticator.auto_login = True
c.LavBenchAuthenticator.control_api_url = os.environ["CONTROL_API_URL"]
c.LavBenchAuthenticator.service_token = os.environ["CONTROL_API_SERVICE_TOKEN"]
c.Authenticator.enable_auth_state = True  # Already set in values.yaml; requires JUPYTERHUB_CRYPT_KEY
```

Notes:
- `allow_all` stays `False`. Access is decided by `check_allowed` on the `auth_state` from section 5.3.
- In oauthenticator 17.4.0, `userdata_from_id_token` decodes the id_token without verifying its signature. OIDC Core 3.1.3.7 allows this because the token comes straight from the token endpoint over TLS. Verifying against `/api/oidc/jwks` (oauthenticator 17.5 `OIDCOAuthenticator`) is a LATER improvement.
- JupyterHub lowercases usernames; `lb-<uuid>` is already lowercase.

### 5.3 `POST /internal/hub-logins` (control API)

Replaces `/internal/launch-tokens/consume` (`services/api/nanocolab_api/firestore_app.py:1083-1180`) in LavBench mode.

- **Auth:** the existing Hub-to-control-API bearer (`hub-control-api/service-token`).
- **Request:** `{"sub": "<uuid>", "challenge_id": "<uuid>", "stage_id": "<uuid>"}`.
- **Checks:**
  - the competition `stage_id` exists with `source = "lavbench"` and is not deleted;
  - its `lavbench.challengeId` equals `challenge_id`;
  - now is inside the workspace window `[window.start, window.end + window.graceSeconds]`.

  Otherwise it returns `403` (or `409` outside the window) and the Hub denies the sign-in.
- **Workspace document:** created idempotently with a deterministic id, UUIDv5 over `"<stage_id>/<sub>"` with a fixed namespace, using Firestore `create()` and treating "already exists" as success. Fields: `student_id = sub`, `competition_id = stage_id`, `kind = "OFFICIAL"` for both stage kinds, state `REQUESTED`.
- **Skipped checks:** the `students` collection, `require_unexpired_account` and the retirement check. LavBench already authorised the user.
- **Response:** the existing consume payload, built by the same code (`firestore_app.py:1147-1175`):

```json
{
  "jupyterhub_username": "lb-0193a5f2-6c1e-7d4a-9b2f-3e8d1c0a4b5f",
  "workspace_id": "<uuidv5>",
  "competition_id": "<stage_id>",
  "workspace_kind": "OFFICIAL",
  "workspace": {
    "workspace_id": "<uuidv5>",
    "student_id": "0193a5f2-6c1e-7d4a-9b2f-3e8d1c0a4b5f",
    "competition_id": "<stage_id>",
    "kind": "OFFICIAL",
    "image": "<profile.image>",
    "cpu_cores": 2,
    "memory_gib": 12,
    "disk_gib": 50,
    "dataset_pvc": "dataset-<competition key>",
    "synthetic_config_map": null,
    "test_window_id": null,
    "workspace_pvc": "workspace-<workspace_id[:53]>",
    "gpu_type": null
  }
}
```

### 5.4 What goes away

- **Immediately:** `app/chatgpt-auth.ts`. It is unused and trusts `oai-authenticated-user-*` headers.
- **In LavBench mode, and deleted after rehearsal 2 passes:**
  - the launch-token mint and consume code, `/hub/launch` and `NanoColabLaunchHandler`;
  - `/student-sessions`, `competition_accounts.py`, `/admin/students*` and `/admin/competitions/with-accounts`;
  - the `students`, `student_sessions`, `login_rate_limits` and `launch_tokens` collections;
  - the student portal and ControlRoom;
  - the Google OIDC admin login. The production config validator that requires it (`services/api/nanocolab_api/config.py:51-59`), `PORTAL_ORIGIN`, `--portal-origin` (`services/event-startup/worker.py:265`) and the portal link in `jupyter/hub/templates/home.html` go with it.
- If a break-glass view for infrastructure operators is kept, a token without a roles claim must mean "deny", not super-admin (`services/api/nanocolab_api/auth.py:79`).

## 6. Service-to-service tokens

In April, only nanoColab calls LavBench. LavBench does not call nanoColab's control API, so nanoColab does not need to verify LavBench tokens yet.

### 6.1 Profile

Every call from nanoColab to `/api/nanocolab/v1/*` carries `Authorization: Bearer <JWT>`:
- JWT (RFC 7519) with explicit typing (RFC 8725 section 3.11), signed with Ed25519.
- Header: `{"alg": "EdDSA", "typ": "nanocolab-s2s+jwt", "kid": "<RFC 7638 thumbprint>"}`. PyJWT 2.x names the algorithm `EdDSA`.
- Claims:

| Claim | Value |
|---|---|
| `iss` | `nanocolab` |
| `sub` | `nanocolab` |
| `aud` | `lavbench-api` |
| `iat` | Now, Unix seconds |
| `exp` | At most `iat + 300` |
| `jti` | A new UUIDv4 |

```python
import time
import uuid

import jwt  # PyJWT


def lavbench_token(private_key_pem: bytes, kid: str) -> str:
    now = int(time.time())
    claims = {
        "iss": "nanocolab", "sub": "nanocolab", "aud": "lavbench-api",
        "iat": now, "exp": now + 300, "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        claims, private_key_pem, algorithm="EdDSA",
        headers={"typ": "nanocolab-s2s+jwt", "kid": kid},
    )
```

Also send a W3C `traceparent` header on every call. LavBench logs its trace id.

### 6.2 Verification by LavBench

LavBench accepts only `alg = EdDSA` and the exact `typ`, `iss` and `aud`; it requires `exp`, `iat` and `jti`, rejects lifetimes over 300 seconds and allows 30 seconds of clock skew. A token on `GET` may be reused until it expires. On `PUT` and `POST`, every `jti` must be new (LavBench stores it in Redis until `exp`). Failures return `401 {"error": "...", "code": "ERR_S2S_TOKEN_INVALID"}`.

### 6.3 nanoColab JWKS

nanoColab publishes its public keys as a JWK Set (RFC 7517) at a public URL, for example `GET <control API>/.well-known/jwks.json`, and LavBench is configured with that URL (`NANOCOLAB_JWKS_URL`):

```json
{"keys": [{"kty": "OKP", "crv": "Ed25519", "x": "<base64url public key>",
           "kid": "<RFC 7638 thumbprint>", "alg": "EdDSA", "use": "sig"}]}
```

LavBench caches the set and refetches it when it sees an unknown `kid`. To rotate, publish the new key at least a day before signing with it, and keep the old key published until its last token has expired.

### 6.4 LATER: LavBench to nanoColab

When revoke and archive access ship, LavBench will sign calls to nanoColab with the mirror profile (`typ = lavbench-s2s+jwt`, `iss = lavbench`, `aud = nanocolab-api`, plus the RFC 8693 `act` claim for the acting user), published at `https://bench.noai-bg.com/api/oidc/jwks`. nanoColab will then store `jti` values in Firestore `s2s_jti/{jti}` with a TTL policy, on state-changing calls only.

## 7. Stage spec

### 7.1 Endpoint

`GET https://bench.noai-bg.com/api/nanocolab/v1/stages`

- **Auth:** section 6.
- **Response headers:** a strong `ETag` over the body, and `Cache-Control: no-cache`.
- **Conditional requests:** send the last `ETag` in `If-None-Match`; LavBench answers `304 Not Modified` when nothing changed (RFC 9110 sections 8.8.3 and 13.1.2).
- **Errors:** `401 ERR_S2S_TOKEN_INVALID`; `404 ERR_NOT_FOUND` when the integration is not configured on the LavBench side.

### 7.2 Payload

The response lists every stage that has ever been exported and still exists. `deleted: true` marks a stage whose export was switched off. LavBench refuses to delete a stage while it is exported, so normally a stage is unexported (and seen as deleted) first; if an item for a known LavBench competition is ever absent, treat it exactly like `deleted: true`.

Times are RFC 3339 in UTC with a `Z` suffix, to the second. `timeZone` is an IANA name and is for display only.

```json
{
  "apiVersion": "lavbench.nanocolab/v1",
  "items": [
    {
      "stageId": "0193a5f2-7a10-7c3e-8a51-6b2d9e4f1c07",
      "challengeId": "0193a5f2-5f00-7b1d-9e2a-1c3b5d7f9a11",
      "generation": 7,
      "kind": "official",
      "title": "NOAI 2027 Selection / Day 1",
      "window": {
        "start": "2027-04-23T07:00:00Z",
        "end": "2027-04-23T12:00:00Z",
        "graceSeconds": 180,
        "timeZone": "Europe/Sofia"
      },
      "retentionDays": 90,
      "finalizedAt": null,
      "profile": {
        "shapeId": "cpu-2c-12g",
        "cpu": 2,
        "memoryGiB": 12,
        "diskGiB": 50,
        "gpu": null,
        "image": "europe-west4-docker.pkg.dev/nano-colab/nanocolab-staging-environments/colab-compatible-cpu@sha256:cb513357fbf0fafbd2049a0c8c867c6eafc866edb570e3b6557bed3aac4bbeab"
      },
      "participants": {"count": 412},
      "deleted": false,
      "bundle": {
        "digest": "sha256:3f9a0c4e5b6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f",
        "payloadOxum": "8123456789.412"
      }
    }
  ]
}
```

### 7.3 Fields

| Field | Type | Meaning |
|---|---|---|
| `apiVersion` | string | Always `lavbench.nanocolab/v1` in v1 |
| `stageId` | UUID | LavBench stage id; the nanoColab competition id |
| `challengeId` | UUID | LavBench challenge id |
| `generation` | integer, at least 1 | Increases whenever any other field of the item changes; never decreases |
| `kind` | `test` or `official` | Display and labels only |
| `title` | string | Display only; may change at any time |
| `window.start`, `window.end` | RFC 3339 UTC | The stage window. Students are shown `end`. |
| `window.graceSeconds` | integer | Workspaces stay open until `end + graceSeconds`; LavBench accepts submissions until then |
| `window.timeZone` | IANA zone | The challenge time zone, for display |
| `retentionDays` | integer, at least 90 | How long workspace exports are kept after `end` |
| `finalizedAt` | RFC 3339 UTC or null | When the LavBench jury finalised the stage results |
| `profile` | object or null | The compute profile, chosen from the nanoColab catalog (section 10.2). `null` until the admin sets it; a stage without a profile must not start. |
| `profile.shapeId` | string | A catalog shape id |
| `profile.cpu`, `profile.memoryGiB`, `profile.diskGiB` | numbers | The shape values, copied in full so the spec is self-contained |
| `profile.gpu` | null or `{"type": string, "count": integer}` | Always `null` in April (CPU only) |
| `profile.image` | string | An image reference pinned by digest (`...@sha256:<hex>`), from the catalog |
| `participants.count` | integer | Competitors registered in the challenge |
| `deleted` | boolean | `true` when the stage is no longer exported |
| `bundle` | object or null | The stage bag (section 9). `null` until LavBench ships bag generation and the stage has published tasks. |
| `bundle.digest` | `sha256:<hex>` | sha256 of the bag's `manifest-sha256.txt` |
| `bundle.payloadOxum` | string | BagIt `Payload-Oxum`: `<octets>.<file count>` |

### 7.4 JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://bench.noai-bg.com/api/schemas/nanocolab-stages-v1.json",
  "type": "object",
  "required": ["apiVersion", "items"],
  "properties": {
    "apiVersion": {"const": "lavbench.nanocolab/v1"},
    "items": {"type": "array", "items": {"$ref": "#/$defs/stage"}}
  },
  "$defs": {
    "uuid": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},
    "utc": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$"},
    "stage": {
      "type": "object",
      "required": ["stageId", "challengeId", "generation", "kind", "title", "window",
                   "retentionDays", "finalizedAt", "profile", "participants", "deleted", "bundle"],
      "properties": {
        "stageId": {"$ref": "#/$defs/uuid"},
        "challengeId": {"$ref": "#/$defs/uuid"},
        "generation": {"type": "integer", "minimum": 1},
        "kind": {"enum": ["test", "official"]},
        "title": {"type": "string", "minLength": 1},
        "window": {
          "type": "object",
          "required": ["start", "end", "graceSeconds", "timeZone"],
          "properties": {
            "start": {"$ref": "#/$defs/utc"},
            "end": {"$ref": "#/$defs/utc"},
            "graceSeconds": {"type": "integer", "minimum": 0},
            "timeZone": {"type": "string", "minLength": 1}
          }
        },
        "retentionDays": {"type": "integer", "minimum": 90},
        "finalizedAt": {"oneOf": [{"$ref": "#/$defs/utc"}, {"type": "null"}]},
        "profile": {
          "oneOf": [
            {"type": "null"},
            {
              "type": "object",
              "required": ["shapeId", "cpu", "memoryGiB", "diskGiB", "gpu", "image"],
              "properties": {
                "shapeId": {"type": "string", "minLength": 1},
                "cpu": {"type": "number", "exclusiveMinimum": 0},
                "memoryGiB": {"type": "number", "exclusiveMinimum": 0},
                "diskGiB": {"type": "integer", "minimum": 1},
                "gpu": {
                  "oneOf": [
                    {"type": "null"},
                    {"type": "object", "required": ["type", "count"],
                     "properties": {"type": {"type": "string"}, "count": {"type": "integer", "minimum": 1}}}
                  ]
                },
                "image": {"type": "string", "pattern": "@sha256:[0-9a-f]{64}$"}
              }
            }
          ]
        },
        "participants": {
          "type": "object",
          "required": ["count"],
          "properties": {"count": {"type": "integer", "minimum": 0}}
        },
        "deleted": {"type": "boolean"},
        "bundle": {
          "oneOf": [
            {"type": "null"},
            {
              "type": "object",
              "required": ["digest", "payloadOxum"],
              "properties": {
                "digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                "payloadOxum": {"type": "string", "pattern": "^\\d+\\.\\d+$"}
              }
            }
          ]
        }
      }
    }
  }
}
```

Unknown properties are allowed everywhere (additive changes within v1). An unknown `kind` value rejects the item, because a new enum value is a breaking change under the Kubernetes API conventions.

### 7.5 Freeze rules

LavBench enforces these when an admin edits a stage, and nanoColab re-checks them when applying an item. The freeze window is `[window.start - 24 h, window.end + graceSeconds]`, with the lead time configurable on both sides.

Inside the freeze window:
- `window.start`, `profile`, `bundle` and `kind` cannot change;
- `window.end` can only move later, and LavBench refuses an end change when the current end is less than 2 minutes away, so a 1-minute sync always sees it in time;
- a lower `participants.count` is treated as no change (capacity only grows);
- `deleted: true` while the stage is live is ignored and raised to an operator.

Outside the freeze window, every field may change.

### 7.6 Applying items

The sync is level-triggered: each tick compares the full desired state with the competitions it manages and repairs differences. Only competitions with `source = "lavbench"` are touched.

For each item:
1. Validate it against the schema and the catalog (the shape and image must exist).
2. Check the freeze rules against the competition's current state.
3. If both pass, write the item to the competition document and set `observedGeneration = generation`.
4. If not, keep the last-known-good copy, and report an `Accepted=False` condition with the reason (section 10.1). This is the same approach as an Envoy xDS NACK.

On any network or `5xx` error, keep the last-known-good state and try again next tick. Running workspaces never depend on LavBench being reachable.

If an end extension arrives while a competition is live, apply it to the workspace window. If LavBench is unreachable at the end, the cut-off happens at the cached end; that case is documented in the LavBench runbook.

## 8. Firestore model

Changes in LavBench mode:

| Collection or field | Change |
|---|---|
| `competitions/{stageId}` | New fields: `source = "lavbench"`, and `lavbench = {challengeId, generation, observedGeneration, bundleDigest, mirroredDigest, conditions, spec}` where `spec` is the last accepted item. Existing fields are derived from the item: name from `title`; `starts_at`, `planned_ends_at`, `effective_ends_at` from `window`; `retention_days` from `retentionDays`; `cpu_cores`, `memory_gib`, `disk_gib`, `gpu_type`, `environment_digest` from `profile`; `asset_version` from `bundle.digest`; `max_attendance` from `participants.count`. |
| `lavbench_sync/state` | New: `{etag, lastSyncAt, lastError}` |
| `workspaces/{uuidv5}` | Created by `/internal/hub-logins` with `student_id = sub` |
| `students`, `student_sessions`, `login_rate_limits`, `launch_tokens` | Not used in LavBench mode |
| `test_windows` and the synthetic ConfigMap path | Not used: test stages are ordinary competitions run as `OFFICIAL` |
| `competition_assignments` | Not used: capacity comes from `participants.count` |
| `user_revocations/{sub}`, `s2s_jti/{jti}` | LATER |

Nothing exists in production on either side, so there is no legacy data to migrate; rehearsal data is purged before the selection.

## 9. Stage bag and mirror

### 9.1 Bag layout

The bag holds the public data of every published task of the stage, and never any hidden file. Labels, solution notebooks and evaluators stay in LavBench.

```
bagit.txt
bag-info.txt
manifest-sha256.txt
data/<slug>/README.md
data/<slug>/sample_submission.parquet
data/<slug>/LICENSE*, NOTICE*, sources.txt          (when present)
data/<slug>/data/**                                  (task data)
data/<slug>/models/**                                (model files)
data/starter/<slug>/baseline.ipynb                   (the starter notebook)
```

- `bagit.txt` is `BagIt-Version: 1.0` and `Tag-File-Character-Encoding: UTF-8`.
- `bag-info.txt` carries `Payload-Oxum: <octets>.<file count>` and `External-Identifier: lavbench-stage:<stageId>`. It has no date and no generation, so the bag is reproducible.
- `manifest-sha256.txt` has one line `<sha256 hex>  data/<path>` per payload file, sorted by the UTF-8 bytes of the path. Paths containing `%`, CR or LF are percent-encoded (RFC 8493 section 2.1.3).
- There is no tag manifest and no `fetch.txt`. The bag digest is the sha256 of the `manifest-sha256.txt` bytes.
- Each task holds at most 2,000 files and 8 GiB, so a stage bag holds at most 2,000 files per task. Raise the stager's entry limit to match.

### 9.2 Bundle routes

| Route | Content |
|---|---|
| `GET /api/nanocolab/v1/bundles/sha256:<hex>/bagit.txt` | Tag file |
| `GET /api/nanocolab/v1/bundles/sha256:<hex>/bag-info.txt` | Tag file |
| `GET /api/nanocolab/v1/bundles/sha256:<hex>/manifest-sha256.txt` | Tag file |
| `GET /api/nanocolab/v1/bundles/sha256:<hex>/data/<path>` | A payload file. The path is URL-encoded per segment. |

All routes use the S2S token (section 6), support `Range` requests, and return `ETag: "<sha256 hex of the file>"` and `Cache-Control: private, max-age=31536000, immutable` (RFC 8246). An unknown digest returns `404 ERR_NOT_FOUND`.

### 9.3 Mirror

The existing `services/api/nanocolab_api/asset_worker.py` becomes the mirror job. For a digest that is not yet mirrored:

1. Fetch `manifest-sha256.txt` and check that its sha256 equals the digest.
2. Fetch `bagit.txt` and `bag-info.txt`. Check that `Payload-Oxum`'s file count equals the number of manifest lines.
3. For each manifest line, stream `data/<path>`, hash it, compare with the manifest, and write it to `gs://<assets bucket>/lavbench/<hex>/data/<path>` with `if_generation_match=0`. An object that already exists with the right hash is skipped, so the job can resume.
4. Check the total size against `Payload-Oxum`'s octet count.
5. Write the three tag files last, as the seal, and set `BundleMirrored=True`.

Mirroring starts as soon as the digest appears, which is at least the lead time (24 h) before the stage starts. No data is downloaded from LavBench on contest day.

### 9.4 Staging and startup

- **Stager** (`services/asset-stager/stage_assets.py`): reads `manifest-sha256.txt` from the mirrored prefix instead of `manifest.json`, strips the `data/` prefix, and verifies every file as today. It then writes a `manifest.json` in the existing v1 format with `asset_kind: "OFFICIAL_COMPETITION"`, `official_assets_included: true`, `version: "sha256:<hex>"` and `workspace_layout: "starter"`, so the existing checks (`stage_assets.py:21-27`) and the seeder keep working.
- **Seeder** (`services/workspace-controller/nanocolab_workspace/workspace_files.py`): unchanged. With `workspace_layout: "starter"` it copies `/competition/starter/<slug>/baseline.ipynb` to `/workspace/<slug>/baseline.ipynb` once and never overwrites it.
- **Policy** (`services/event-startup/policy.py:14`): the `VERSION` pattern also accepts `^sha256:[0-9a-f]{64}$` for LavBench competitions.
- **Startup** (`services/event-startup/worker.py`): the image comes from `profile.image` (checked against the catalog) instead of the hard-coded `CPU_IMAGE` (lines 19 and 97), the manifest path comes from the mirrored prefix (line 100), and capacity comes from `participants.count` instead of `competition_assignments`.
- **Disk:** one read-only pd-ssd per competition, `dataset-<competition key>`, sized `max(20 GiB, 1.2 x Payload-Oxum octets)`, attached read-only to at most 100 nodes. Hyperdisk ML is not used: the n2 nodes cannot attach it.
- **Result in the workspace:** `/competition/<slug>/data/...`, `/competition/<slug>/models/...`, `/competition/<slug>/README.md` and `/competition/<slug>/sample_submission.parquet`, all read-only, plus `/workspace/<slug>/baseline.ipynb`. LavBench's grader uses the same `/competition/<slug>/` paths, so a baseline runs unchanged in both.

## 10. Status and catalog

Both are pushed by nanoColab in the 1-minute dispatcher tick, with a fresh S2S token (new `jti`) per request. Each `PUT` replaces the previous report. LavBench answers `204`; a body that fails validation returns `422 {"error": "...", "code": "ERR_VALIDATION"}`.

### 10.1 `PUT /api/nanocolab/v1/status`

Built from what Firestore already records: the sync and mirror conditions, the `event_startup` status, and the stored workspace states.

```json
{
  "apiVersion": "nanocolab.lavbench/v1",
  "reportedAt": "2027-04-23T07:05:00Z",
  "platform": {"status": "operational", "message": ""},
  "items": [
    {
      "stageId": "0193a5f2-7a10-7c3e-8a51-6b2d9e4f1c07",
      "observedGeneration": 7,
      "conditions": [
        {"type": "Accepted", "status": "True", "reason": "Applied", "message": "",
         "lastTransitionTime": "2027-04-22T06:10:00Z"},
        {"type": "BundleMirrored", "status": "True", "reason": "Verified", "message": "",
         "lastTransitionTime": "2027-04-22T06:25:00Z"},
        {"type": "VolumeReady", "status": "True", "reason": "Staged", "message": "",
         "lastTransitionTime": "2027-04-23T05:40:00Z"},
        {"type": "StartupReady", "status": "True", "reason": "Ready", "message": "",
         "lastTransitionTime": "2027-04-23T06:55:00Z"}
      ],
      "startup": {"status": "READY", "paused": false},
      "workspaces": {"requested": 398, "stopped": 0, "archived": 0, "purged": 0}
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `platform.status` | One of the Statuspage words: `operational`, `degraded_performance`, `partial_outage`, `major_outage`, `under_maintenance` |
| `conditions[]` | Kubernetes-style conditions. `status` is `"True"`, `"False"` or `"Unknown"`; `reason` is a CamelCase word; `message` is human-readable. Types: `Accepted` (the item passed validation and the freeze rules; `False` with reasons such as `InvalidProfile` or `FreezeViolation`), `BundleMirrored`, `VolumeReady`, `StartupReady`. |
| `startup.status` | The existing event-startup status: `DISPATCHED`, `PREPARING`, `RUNNING`, `READY`, `FAILED` or `BLOCKED` |
| `workspaces` | Counts of the stored workspace states |

LavBench shows "unknown" when `reportedAt` is more than 3 minutes old.

### 10.2 `PUT /api/nanocolab/v1/catalog`

The shapes and images a stage profile may use. LavBench offers only these in its stage form and validates profiles against the latest catalog.

```json
{
  "apiVersion": "nanocolab.lavbench/v1",
  "reportedAt": "2027-04-23T07:05:00Z",
  "shapes": [
    {"id": "cpu-2c-12g", "title": "2 vCPU, 12 GiB", "cpu": 2, "memoryGiB": 12,
     "diskGiB": {"min": 20, "max": 100, "default": 50}, "gpu": null}
  ],
  "images": [
    {"id": "colab-compatible-cpu", "title": "Colab-compatible CPU, Python 3.12",
     "image": "europe-west4-docker.pkg.dev/nano-colab/nanocolab-staging-environments/colab-compatible-cpu@sha256:cb513357fbf0fafbd2049a0c8c867c6eafc866edb570e3b6557bed3aac4bbeab",
     "python": "3.12", "packages": {"pandas": "<version>", "pyarrow": "<version>"}}
  ]
}
```

## 11. Workspace file access for LavBench

LavBench reads a student's files through the Hub proxy with a JupyterHub service token, only when the student clicks in the LavBench picker.

### 11.1 Hub service and roles (z2jh values)

The token is set from Secret Manager at bootstrap, so it survives cluster rebuilds; LavBench stores the same value as `JUPYTERHUB_API_TOKEN`.

```yaml
hub:
  services:
    lavbench:
      apiToken: "<LAVBENCH_HUB_SERVICE_TOKEN>"
  loadRoles:
    lavbench-picker:
      description: Read-only workspace access for the LavBench file picker
      scopes:
        - read:servers
        - access:servers
        - "custom:jupyter_server:read:*"
      services: [lavbench]
    user:
      scopes:
        - self
        - "custom:jupyter_server:execute:*!user"
        - "custom:jupyter_server:read:*!user"
  extraConfig:
    20-lavbench-scopes: |
      c.JupyterHub.custom_scopes = {
          "custom:jupyter_server:read:*": {"description": "read-only access to your server"},
          "custom:jupyter_server:write:*": {
              "description": "access to modify files on your server. Does not include execution.",
              "subscopes": ["custom:jupyter_server:read:*"],
          },
          "custom:jupyter_server:execute:*": {
              "description": "Execute permissions on servers.",
              "subscopes": ["custom:jupyter_server:write:*", "custom:jupyter_server:read:*"],
          },
      }
      c.Spawner.oauth_client_allowed_scopes = [
          "access:servers!server",
          "custom:jupyter_server:read:*!server",
          "custom:jupyter_server:execute:*!server",
      ]
```

This follows the official JupyterHub `examples/read-only`. The `user` role and `oauth_client_allowed_scopes` are what keep students' full access to their own server once the granular authorizer below is active; test that explicitly.

### 11.2 Single-user image

Every workspace image needs:
- `jupyter_server` 2.11 or later (the contents API `hash=1` parameter);
- the granular authorizer from the same example, for example in `/etc/jupyter/jupyter_server_config.py`:

```python
import os

from jupyterhub.singleuser.extension import JupyterHubAuthorizer


class GranularJupyterHubAuthorizer(JupyterHubAuthorizer):
    """Authorizer that looks for permissions in JupyterHub scopes"""

    def is_authorized(self, handler, user, action, resource):
        filters = [
            f"!user={os.environ['JUPYTERHUB_USER']}",
            f"!server={os.environ['JUPYTERHUB_USER']}/{os.environ['JUPYTERHUB_SERVER_NAME']}",
        ]
        required_scopes = set()
        for f in filters:
            required_scopes.update(
                {
                    f"custom:jupyter_server:{action}:{resource}{f}",
                    f"custom:jupyter_server:{action}:*{f}",
                }
            )
        have_scopes = self.hub_auth.check_scopes(required_scopes, user.hub_user)
        return bool(have_scopes)


c.ServerApp.authorizer_class = GranularJupyterHubAuthorizer
```

Without this authorizer, the `access:servers` scope alone gives full access, including running code. The pod must receive `JUPYTERHUB_USER` and `JUPYTERHUB_SERVER_NAME` from the spawner environment.

### 11.3 What LavBench calls

All calls carry `Authorization: token <JUPYTERHUB_API_TOKEN>` and happen only on a student's click:

| Call | Purpose |
|---|---|
| `GET /hub/api/users/lb-<uuid>` | Is the server ready? |
| `GET /user/lb-<uuid>/api/contents/<dir>?content=1` | List a directory (LavBench walks at most 3 levels and 500 entries, keeping `.parquet` and `.ipynb`) |
| `GET /user/lb-<uuid>/api/contents/<path>?content=0&hash=1` | Size, mtime and sha256 before and after the copy |
| `GET /user/lb-<uuid>/files/<path>` | The file bytes, streamed |

LavBench never fetches file bytes through the contents API, never starts or stops a server, and never polls.

## 12. Workspace lifecycle

- **Window:** a workspace can start from `window.start` and runs until `window.end + window.graceSeconds`. Students are shown `window.end`.
- **Culling:** set `cull.enabled: false`. The window is the only workspace lifetime.
- **Kinds:** both kinds run as `OFFICIAL` internally, because `WorkspaceSpec.validate` (`services/workspace-controller/nanocolab_workspace/manifests.py:42-51`) requires a ConfigMap for `TEST` and the lifecycle loop (`services/workspace-controller/nanocolab_workspace/lifecycle.py:38-42`) stops only official disks.
- **Retention:** workspace exports are kept for `retentionDays` (at least 90) after the end. Today's default is 1 day (`services/api/nanocolab_api/schemas.py:54`).
- **Images:** pin pandas and pyarrow in every workspace image. The t4-bert image has no pyarrow today (`environments/t4-bert/requirements.lock`). Students read Parquet data and write `submission.parquet`.
- **Environment:** `HF_HUB_OFFLINE=1`; no `HF_TOKEN`; `HOME=/workspace` already makes the Hugging Face caches writable.
- **April is CPU only.** `profile.gpu` is always `null`.

## 13. Network

- **Students:** browser to `https://lab.noai-bg.com` (Hub, through the Google load balancer) and to `https://bench.noai-bg.com` (LavBench). Both are subdomains of `noai-bg.com`, so they are same-site.
- **nanoColab to LavBench:** HTTPS over the internet from Cloud Run (sync, mirror, status and catalog push) and from the Hub (token exchange). No VPC peering; LavBench runs in a separate GCP project.
- **LavBench to the Hub:** HTTPS through the same public load balancer. The Hub's NetworkPolicy, which only admits Google load balancer ranges (`jupyter/hub/public-service.yaml`), needs no change.
- **Student pods:** egress stays limited to the Hub and DNS. Blocking external DNS is LATER.

## 14. Rollback

- `NANOCOLAB_IDENTITY_MODE=legacy|lavbench` is chosen at cluster bootstrap, because the Hub runs only one authenticator.
- `legacy` keeps today's portal, accounts and launch tokens. `lavbench` uses sections 5-12.
- The sync only touches competitions with `source = "lavbench"`, so both kinds can coexist in Firestore.
- For the legacy path, LavBench offers "Download stage bag as ZIP" (admin only), with the bag payload and the `data/` prefix stripped, ready for the existing portal upload.
- Keep the legacy code until rehearsal 2 passes in `lavbench` mode.

## 15. Tests and acceptance

### 15.1 Fixtures

LavBench adds fixtures next to this document as the server side ships: a sample stage list and its JSON Schema (`feat/identity-oidc`), a test Ed25519 key pair with a sample token and JWKS, and a small sample bag (`feat/nanocolab-sync`).

### 15.2 Manual checks

```bash
LB=https://bench.noai-bg.com
curl -sS "$LB/api/oidc/.well-known/openid-configuration"
curl -sS "$LB/api/oidc/jwks"

TOKEN=$(python3 mint_lavbench_token.py)   # The snippet from section 6.1
curl -sS -D - -H "Authorization: Bearer $TOKEN" "$LB/api/nanocolab/v1/stages"
curl -sS -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" \
     -H 'If-None-Match: "<etag from the previous response>"' "$LB/api/nanocolab/v1/stages"   # 304

TOKEN=$(python3 mint_lavbench_token.py)   # A fresh jti for every PUT
curl -sS -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     --data @status.json "$LB/api/nanocolab/v1/status"                                       # 204
```

### 15.3 Acceptance per MUST item

| Item | Accepted when |
|---|---|
| Identity | A registered competitor clicks "Open workspace" in LavBench and lands in JupyterLab without a second login. A competitor outside the window, a jury member and an admin are denied. Stopping LavBench does not end running Hub sessions. |
| Stage sync | A test stage exported in LavBench appears as a competition within 2 minutes; an end extension is applied; a freeze violation keeps the last-known-good copy and reports `Accepted=False`. |
| Mirror and staging | A stage bag is mirrored and verified, staged read-only at `/competition/<slug>/`, and the baseline is seeded to `/workspace/<slug>/baseline.ipynb`. A tampered file fails verification. |
| Picker scopes | The LavBench token lists and downloads files but cannot run code or write files; students still run notebooks normally. |
| Workspace window | Workspaces stay up until `end + graceSeconds` and are not culled when idle. |
| pyarrow | `pd.read_parquet` and `DataFrame.to_parquet` work in every image. |
| Rollback | A cluster bootstrapped with `legacy` runs today's flow unchanged. |
| Status and catalog | LavBench's nanoColab row turns "unknown" within 3 minutes of stopping the push, and its stage form lists the pushed shapes and images. |

### 15.4 Rehearsal checklist

1. Export a practice stage with one notebook-mode and one file-mode task.
2. Sign in as several test competitors, run the baselines from `/workspace/<slug>/`, and submit from the workspace and by upload.
3. Extend the end during the stage and confirm both systems follow.
4. Stop one LavBench worker, then LavBench itself, during the stage, and confirm running workspaces continue.
5. Confirm the workspace exports exist after the end with the agreed retention.

## 16. Deferred items and open questions

**LATER:**
- **Per-user revoke.** LavBench will call nanoColab when a student is removed; nanoColab records `user_revocations/{sub}`, `archive-context.launch_allowed` returns false for that user, and `end-authorize` treats the workspace as ended, so the existing lifecycle loop stops the pod.
- **Archive access for jury and admin** through LavBench, showing aliases only.
- External DNS blocking for student pods, JSON logs, ruff and mypy in CI, i18n of Hub pages, and deleting the portals.
- Verifying id_token signatures with oauthenticator 17.5 `OIDCOAuthenticator`.

**Open questions (to be answered by testing on staging):**
- The HTTP status the Hub proxy returns when the student's server is not running. LavBench treats any non-success as "workspace not running".
- The jupyter_server version in each workspace image (2.11 or later is needed).
- Whether `/user/<name>/files/<path>` streams large files or buffers them.
