# LavBench and nanoColab: integration note

This note covers how LavBench drives nanoColab through nanoColab's own `/v1` API, and what LavBench asks of nanoColab for the April 2027 selection round.

**The contract is nanoColab's OpenAPI file,** generated from code: [`docs/api/nanocolab-v1.openapi.json`](https://github.com/Aleksis99/nano-colab/blob/b13c73cff415d213b681098933d65d9b1fe9759d/docs/api/nanocolab-v1.openapi.json) in the nano-colab repository. LavBench pins commit `b13c73c` (branch `feat/v1-compute-api`) until a tag exists, vendors that file and runs its contract tests against it.

This note only records what the OpenAPI file cannot say: who calls whom, the timing, the package format, the error mapping and the fallback. It replaces the earlier contract ([#175](https://github.com/delyan-boychev/lavbench/pull/175)), whose OIDC provider, service JWTs, stage-spec pull and BagIt mirror are no longer planned.

## Who calls whom

- **One direction.** LavBench calls nanoColab. nanoColab never calls LavBench: LavBench serves no JWKS and verifies no nanoColab tokens.
- **Authentication:** `Authorization: Bearer ncak_<key_id>_<secret>`. LavBench reads the key from a secret file and never logs it. It uses the scopes `events:read`, `events:write`, `workspaces:launch`, `workspaces:export` and `assets:write`.
  - b13c73c allows one key per client and no expiry. So a key rotation is a planned window outside any contest: nanoColab replaces the key and LavBench swaps its key file. Calls in between get 401 and are retried on the next tick.
  - The client's `hub_username_prefix` is `lb-`. b13c73c requires every asset version to start with it, and Hub usernames become `lb-<LavBench user uuid>`.
- **A reconcile loop** is the only writer: a 60-second timer in LavBench, also run on an admin save and on "Sync now". For every exported stage it ensures the stage package, PUTs the full event, creates the workspaces at the window start and caches readiness.
  - Every PUT is the complete desired state, because `EventUpsert` resets omitted fields. A failed call is retried on the next tick.
  - No LavBench GET request writes to nanoColab.
- **Students** reach nanoColab only through three calls LavBench makes for them: launch, file check and export.
- **Readiness** is read once per stage per tick, never for a student request. LavBench uses only `status`, `message` and `capacity`, because b13c73c returns no conditions, and shows a 404 before the first event PUT as "not created yet". Readiness gates nothing: "Open workspace" stays enabled inside the window, and the launch call decides.

## A stage, from draft to archive

1. **Package upload.** An admin marks a stage as exported. LavBench builds the stage package (below), uploads it, and waits until nanoColab reports the asset READY: every event PUT, draft included, needs a READY asset.
2. **Event draft.** LavBench PUTs the event with `published: false`. Admins can still change the stage, and every tick re-PUTs it.
3. **Publish and freeze at T-24 h.** LavBench publishes automatically 24 hours before the start, then the stage is frozen.
   - Publishing is blocked, and the admin alerted, if the asset is not READY, readiness is BLOCKED, or the image's pyarrow is newer than the grader's or missing from the catalog's package list.
   - An audited fix to hidden files, such as the labels, is still allowed in LavBench. Hidden files never reach nanoColab, so the asset does not change.
4. **After publish,** only a later end is sent: an extension, with the admin's reason and the actor. LavBench sends it before the current `ends_at`, because b13c73c refuses one afterwards. Extensions are global; there is no per-student extra time.
   - Before the start an admin can cancel an export, in LavBench only: b13c73c cannot cancel a published event (request 14). Deleting an exported stage is refused.
5. **Window start.** LavBench creates the workspace of every registered, active student who has not finished (`PUT /v1/events/{external_id}/workspaces/{external_user_id}`), in rate-limited batches that spread the writes on the event's seat document. b13c73c refuses creation before the window (request 13). A student who clicks first creates their own.
6. **Launch.** "Open workspace" calls `POST /v1/workspaces/{workspace_id}/launch`. The browser form-POSTs the 60-second, single-use token to the returned `launch_url` (`/hub/launch`) in a new tab.
   - The form must not use `rel="noreferrer"`: the Hub denies a `null` Origin. `LAUNCH_ORIGINS` must be `https://bench.noai-bg.com`.
   - A student who lost the Hub cookie starts again from "Open workspace"; request 8 asks the Hub to send them there instead of showing a 403 page.
   - Each student has one Hub server across all of LavBench's events (`allow_named_servers: false`), and the Hub answers 409 while another workspace runs. So LavBench never lets exported stages overlap, across all challenges, counting grace and the stop and archive time.
7. **Submitting.** The student writes `/workspace/<slug>/submission.parquet` with the starter's `save_submission(df)`.
   - LavBench fetches that file and the task's notebook through the export endpoint, one path per call, up to nanoColab's export cap (20 MiB by default). It re-hashes them, stores its own copy and scores it.
   - The Check step fetches the file too, until a metadata-only mode exists (request 6).
8. **The end.** `ends_at` is the stage end plus LavBench's 180-second grace period. After the stage, exports read the archive (`source: ARCHIVE`), which needs `internal_app` deployed (request 2).
9. **Retention.**
   - LavBench keeps its own copy of the evidence for its configured period.
   - nanoColab keeps workspace archives until the selection is final plus the appeal window. LavBench sends that date as `retention_days`, counted from the end of the event. It can grow but never shrink.
   - The jury reads archives only through LavBench, under aliases.

## The event LavBench sends

`PUT /v1/events/stage-<LavBench stage uuid>` carries:

| Field | Value |
|---|---|
| `name` | a display name for the stage (3-200 chars) |
| `starts_at`, `ends_at` | stage start; stage end + 180 s grace (RFC 3339, UTC) |
| `max_attendance` | registered students + 5% (rounded up, at least +2); it grows with the roster, which after publish needs request 5 |
| `image_id` | the one pinned CPU image for April, from `GET /v1/images` |
| `profile` | the one CPU profile: 2 vCPU, 8 or 12 GiB memory, 10-100 GiB disk, as nanoColab's capacity automation requires |
| `asset_version` | `lb-<first 12 hex of the bundle digest>-v<N>` |
| `export_paths` | per task, relative to `/workspace`: `<slug>/submission.parquet` and the notebook (at most 16 paths, so at most 8 tasks per stage) |
| `retention_days` | days from the end of the event to the archive date above; growing it after publish needs request 5 |
| `published` | `false` until T-24 h, then `true` on every PUT |
| `actor`, `extension_reason` | the LavBench user id (no `@`); the admin's typed reason (at least 8 chars) |

## The stage package

- **Contents.** One ZIP per stage version, built from the published task versions using public files only:
  - per task: `<slug>/README.md`, `<slug>/sample_submission.parquet`, `<slug>/data/**`, `<slug>/models/**`, and any `<slug>/LICENSE*`, `<slug>/NOTICE*` and `<slug>/sources.txt`;
  - `starter/<slug>/baseline.ipynb`, when the task has one (it is optional in file mode);
  - `manifest-sha256.txt`.

  Labels, solutions, evaluators and file-mode baseline submissions never leave LavBench, and no public file may share a sha256 with one of them.
- **Format.** `ZIP_STORED`, entries sorted, fixed 1980 timestamps, mode 0644. No ZIP64, at most 2 GiB and at most 2,000 entries, directories included; LavBench refuses a larger stage instead of sending it. Every path passes nanoColab's `asset_zip.safe_path` rules, and notebooks are nbformat 4 within 16 MiB.
- **Identity.**
  - `manifest-sha256.txt` has one `<sha256>  <path>` line per other file, sorted by the NFC UTF-8 bytes of the path. The bundle digest is the sha256 of that file.
  - The ZIP's own hash is transport only.
  - nanoColab binds a version name to one ZIP hash, so any change to the builder bumps `-v<N>`.
- **Upload,** as a background job in LavBench:
  1. Skip if `GET /v1/assets/<version>` is already READY.
  2. `POST /v1/assets/<version>/uploads` with `size_bytes` and `sha256`.
  3. PUT the ZIP to `upload.url` with `upload.headers` unchanged: a GCS resumable session in 8 MiB chunks with CRC32C, or an S3 presigned URL (its headers carry `x-amz-checksum-sha256` and `If-None-Match: *`). LavBench tells them apart by the URL host.
  4. `POST /v1/assets/<version>/complete`, then poll every tick until READY or FAILED.
- **In the workspace.** LavBench asks for `<slug>/` mounted read-only at `/competition/<slug>/`, with only the starter notebook seeded into `/workspace/<slug>/` (request 7). At b13c73c the whole package is copied into every home disk, so the baseline is at `/workspace/starter/<slug>/baseline.ipynb`, and LavBench's notebook export path follows it until request 7 lands.

## How nanoColab responses map to LavBench

| nanoColab | LavBench code | What the person sees |
|---|---|---|
| no `NANOCOLAB_API_URL` configured | `ERR_NANOCOLAB_DISABLED` | workspace features hidden |
| timeout, connection error, other 5xx | `ERR_NANOCOLAB_UNAVAILABLE` | nanoColab is unavailable, try again shortly |
| 503 with Retry-After on launch or workspace PUT | `ERR_WORKSPACE_PREPARING` | "Preparing, retry in N s" |
| 409 outside the event window | `ERR_WORKSPACE_NOT_OPEN` | the stage is not open |
| 409 with Retry-After on export (server not running) | `ERR_WORKSPACE_STOPPED` | "Start your workspace", then try again |
| export file `status: MISSING` | `ERR_WORKSPACE_FILE_MISSING` | no `submission.parquet` saved yet |
| export file `status: TOO_LARGE` | `ERR_WORKSPACE_FILE_TOO_LARGE` | the limit |
| size, mtime or hash differ before and after the read (once request 6 lands) | `ERR_WORKSPACE_FILE_CHANGED` | the file changed while it was read |
| readiness BLOCKED at publish | `ERR_NANOCOLAB_CAPACITY_BLOCKED` | admins: the BLOCKED reason |
| asset FAILED | `ERR_NANOCOLAB_ASSET_FAILED` (a task problem) | admins: nanoColab's message |
| other 4xx (validation, frozen field) | `ERR_NANOCOLAB_REJECTED` | admins: nanoColab's message; students: a generic error |

nanoColab's errors come in three shapes: `detail` as a string, a dict with `message` and `fields`, or a list on 422. LavBench's client reads all three and honours `Retry-After` on 409 and 503; `/v1` has no 429.

LavBench enforces nanoColab's limits before calling, so these never reach nanoColab: more than 8 tasks in an exported stage (`ERR_STAGE_TOO_MANY_TASKS`), a package over 2 GiB (`ERR_STAGE_PACKAGE_TOO_LARGE`), an image whose pyarrow is newer than the grader's or unlisted (`ERR_GRADER_PYARROW_TOO_OLD`), and an extension after `ends_at` (`ERR_EXTENSION_TOO_LATE`).

## If nanoColab fails on the day

The fallback does not depend on nanoColab:
- students submit by uploading `submission.parquet` in LavBench;
- they download the stage data as a ZIP from LavBench;
- admins extend the stage by the length of the outage, before `ends_at`.

No legacy nanoColab accounts are kept on standby.

## Requests to nanoColab

"For April" means the round on the production cluster needs it. "Optional" means LavBench already works around it. None blocks LavBench's development: LavBench builds against the pinned OpenAPI file and a fake, and its local end-to-end run uses b13c73c as it is.

| # | Request | For April | At b13c73c |
|---|---|---|---|
| 1 | **Auto-start `/v1` events.** Startup selection skips events without `competition_assignments` (`startup_policy.py:44-45`, counted in `event_startup_routes.py:100-104`); `/v1` events use `event_seats` | needed | not done |
| 2 | **Production wiring:** `NANOCOLAB_API_CLIENTS`, the image catalog, the export service token, `LAUNCH_ORIGINS` = `https://bench.noai-bg.com`, and `internal_app` deployed (without it there is no data volume and no archive, so every after-stage export gets 409) | needed | not done (`deploy/local/api.sh:93` only) |
| 3 | **Sync API:** `GET /v1/events`; generation, observedGeneration and conditions in the event response; ETag; `asset_version`, `profile` and `retention_days` echoed back | optional | not done |
| 4 | **Readiness semantics:** READY means asset staged + startup run finished + placeholders ready, not only `/hub/health` | needed | partly (placeholders not checked) |
| 5 | **Lifecycle:** `retention_days` and `max_attendance` may grow after publish; `POST /v1/workspaces/{id}/stop` (archive, never delete) | needed | not done |
| 6 | **Export:** one raw streamed file per request from `/files/`, with size, mtime and hash before and after, no base64; a metadata-only mode for the Check step; narrow the export role (`tokens` limited to students; test dropping `access:servers`) | optional (LavBench adapts: base64, one path per call) | partly (a 60 s per-user export token, `hub_export.py:39-46`) |
| 7 | **Data:** seed only `starter/<slug>/*.ipynb` into `/workspace/<slug>/` (no copy-all `preserve`); mount `<slug>/` read-only at `/competition/<slug>/` with a file-browser symlink; verify files against `manifest-sha256.txt` | needed | partly (read-only `/competition`, ROX, uploads lifecycle rule) |
| 8 | **Launch:** GET `/hub/launch` and the Hub login URL redirect to LavBench's "Open workspace"; raise the spawn limit; placeholder pods and an image puller that work with nanoColab's own controller (the z2jh settings do not apply); Hub cookie lifetime about the event length | needed | not done |
| 9 | **Auth:** two active `ncak_` keys per client, each with an expiry (overlap rotation) | optional (planned rotation windows) | not done |
| 10 | **Image:** one pinned CPU image for April with its package list (including pyarrow) in `GET /v1/images`; pandas and pyarrow at or below the grader's | needed | partly (catalog API only) |
| 11 | **Network:** cluster-only DNS for student pods (no recursion; `hub_connect_url` at the Hub's internal address); `HF_HUB_OFFLINE=1`; no AI extensions in images | needed | partly (`PIP_NO_INDEX=1`, egress limited) |
| 12 | **Contract:** Schemathesis in nanoColab CI; `/v1` additive-only; tag the commit LavBench pins | needed | partly (generated OpenAPI with a drift test) |
| 13 | **Window-free workspace creation:** allow `PUT /v1/events/{id}/workspaces/{user}` after publish, before the window, so workspaces exist before the start (today `require_window`, `v1_firestore.py:355-365`) | needed (a calm start) | new |
| 14 | **Cancel event:** an endpoint to cancel an unstarted published event | optional | new |
| 15 | **Image pull access:** Artifact Registry read access for the LavBench workers, which run the grader on the pinned digest | needed | new |
| 16 | **Large stage data:** ZIP64 and a configurable cap up to 8 GiB (S3 multipart or GCS resumable above 5 GB) | optional (only if a task needs over 2 GiB) | new |

## Venues (for the organisers)

- **Machines:** venue machines run Windows or macOS, with Safe Exam Browser and the venue's `.seb` config.
- **Network:** the firewall allows only `bench.noai-bg.com` and `lab.noai-bg.com`.
- **Leaving early:** a student clicks "Finish round" before leaving, which ends their round in LavBench: launch, check, submit and the data download are refused from then on. The supervisor checks the banner, then unlocks Safe Exam Browser's quit.
- **Running workspaces:** the workspace of a finished or deactivated student keeps running. Once request 5 lands, LavBench stops it after "Finish round", and admins can stop any workspace (archive, never delete).
