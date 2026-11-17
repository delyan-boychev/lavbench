# LavBench and nanoColab: integration note

This note covers how LavBench drives nanoColab through nanoColab's own `/v1` API, and what LavBench asks of nanoColab for the April 2027 selection round.

**The contract is nanoColab's OpenAPI file,** generated from code: [`docs/api/nanocolab-v1.openapi.json`](https://github.com/Aleksis99/nano-colab/blob/b13c73cff415d213b681098933d65d9b1fe9759d/docs/api/nanocolab-v1.openapi.json) in the nano-colab repository. LavBench vendors that file at `backend/tests/contracts/nanocolab-v1.openapi.json`, from commit `5cb1e0f` of `fix/lavbench-integration` (b13c73c plus the NC fixes, whose only spec change is the export description), until Ivan tags a commit, and its contract tests check both the client and the test fake against it.

This note only records what the OpenAPI file cannot say: who calls whom, the environment owner, the package, workspaces, submissions, the error mapping, the fallback and the requests. Since its previous version, an event belongs to a stage or to a competition, the package has one folder per task at the workspace root, publishing is manual with an optional automatic switch, and file tasks are submitted straight from the workspace.

## Who calls whom

- **One direction.** LavBench calls nanoColab. nanoColab never calls LavBench, and LavBench verifies no nanoColab tokens.
- **Authentication:** `Authorization: Bearer ncak_<key_id>_<secret>`, read from the secret file named by `NANOCOLAB_API_KEY_FILE` and never logged. The scopes are `events:read`, `events:write`, `workspaces:launch`, `workspaces:export` and `assets:write`.
  - b13c73c allows one key per client and no expiry, so a key rotation is a planned window outside any contest. Calls in between get 401 and are retried on the next run (request 9).
  - The client's `hub_username_prefix` is `lb-`: every asset version starts with it, and Hub usernames are `lb-<LavBench user uuid>`.
- **Transport:** HTTPS only, no redirects, and a timeout on every call (`NANOCOLAB_TIMEOUT_SECONDS`, 10 s; `NANOCOLAB_EXPORT_TIMEOUT_SECONDS`, 30 s for exports). Plain http goes only to a local host in development (`NANOCOLAB_ALLOW_INSECURE_HTTP`). With `NANOCOLAB_API_URL` unset, the integration is off.
- **Writers.** The sync loop and the admin's Publish and Extend buttons write to nanoColab, one at a time per environment under one lock. The loop runs every 60 s (`NANOCOLAB_SYNC_INTERVAL_SECONDS`) and on every admin save: for every enabled environment it ensures the package, PUTs the full event, publishes when the automatic switch says so, and reads readiness, and a failed call is retried on the next run. Publish and Extend PUT the event at once, so the admin sees nanoColab's answer.
- **GETs never write.** No LavBench GET request makes a writing call to nanoColab.
- **Students** reach nanoColab only through calls LavBench makes for them: workspace creation, launch and export.
- **Readiness** is read once per environment per run, never for a student request. LavBench uses `status`, `message` and `capacity`, and shows a 404 before the first event PUT as "not created yet". Admins see "Ready", "Preparing for N min" or "Problem: <nanoColab's message>". Until nanoColab reports a failed preparation (request 19), the age of "Preparing" is the only signal, and LavBench alerts the admins after 10 minutes (`NANOCOLAB_PREPARING_ALERT_MINUTES`). A cached readiness older than 180 s (`NANOCOLAB_STATUS_STALE_SECONDS`) shows as "Unknown".

## Environments and events

- **The environment owner** is the stage, or the competition when it has no stages. There is one event per owner, with the external id `stage-<uuid>` or `challenge-<uuid>` (LavBench's id of that stage or competition).
- **Every PUT carries the full desired state,** because `EventUpsert` resets omitted fields:

| Field | Value |
|---|---|
| `name` | the stage or competition name (3-200 chars) |
| `starts_at`, `ends_at` | the owner's start; the owner's end + 180 s grace (`DEADLINE_GRACE_PERIOD_SECONDS`), RFC 3339 in UTC |
| `max_attendance` | automatic: registered students + 5% (`NANOCOLAB_ATTENDANCE_HEADROOM_PERCENT`, rounded up), at least +2. It grows with the roster, which after publish needs request 5 |
| `image_id` | chosen from `GET /v1/images`; for April, the one pinned CPU image (request 10) |
| `profile` | CPU, 2 vCPU, 8 GiB memory, 10 GiB disk by default (nanoColab's capacity automation accepts 2 vCPU, 8 or 12 GiB, 10-100 GiB) |
| `asset_version` | `lb-<first 12 hex of the content digest>-v<N>` (see the package) |
| `export_paths` | per task, relative to `/workspace`: `<folder>/submission.parquet` and `<folder>/solution.ipynb` for a file task, `<folder>/solution.ipynb` for a notebook task. nanoColab allows 16 per event, and LavBench refuses more (`ERR_ENVIRONMENT_TOO_MANY_TASKS`, 409, with the `limit`) |
| `retention_days` | days from the event end to the archive date (1-365): the end plus 30 days unless the admin picks a date, and an extension moves a picked date along with the end. The date may move later, never earlier; growing it after publish needs request 5 |
| `published` | LavBench's state: `false` until publish, then `true` on every PUT |
| `actor`, `extension_reason` | the LavBench user id (no `@`); on an extension, the admin's typed reason (at least 8 chars) |

- **Draft.** Every event PUT, draft included, needs a READY asset, so LavBench uploads the package first and PUTs `published: false` until publish.
- **Publish** is the admin's "Publish to nanoColab" button, with a confirmation. An optional switch, "Publish automatically 24 h before the start" (`NANOCOLAB_AUTO_PUBLISH_LEAD_HOURS`), lets the sync loop publish at that time if the package is READY, and alert the admins otherwise.
- **After publish,** only a later end is sent: an extension with the admin's reason, sent before the current `ends_at`, because b13c73c refuses one afterwards. Extensions are global; there is no per-student extra time.
  - LavBench locks the other event fields, the public files and the folder names.
  - Hidden files such as the labels may still be fixed in LavBench, with a reason and audited. They never reach nanoColab, so the asset does not change.

## The package

One deterministic ZIP per environment version, built in LavBench from the tasks' public files:

```text
<folder>/                one per task, named from the task title
    <public files>
    solution.ipynb       the file-mode starter, if any, or the notebook-mode baseline
models/<org>/<name>/     from the tasks' Hugging Face ZIPs
datasets/<org>/<name>/
```

- **Folder names** are generated from the task title: transliterated from Bulgarian to Latin, lower-case, special symbols removed (only `a-z`, `0-9` and `-` kept), spaces and runs of separators turned into one `-`, at most 40 characters. They follow the title until publish, unless an admin set the folder name by hand, are unique within the environment, never `models` or `datasets`, and frozen after publish: a later title edit does not rename the folder. A generated name already used in the stage gets a number (`-2`, `-3`, ..., the name trimmed to stay within 40 characters); a hand-set name that is taken is refused (`ERR_TASK_FOLDER_TAKEN`).
- **Hugging Face folders** are the plain folders that `hf download --local-dir` writes. A folder used by two tasks goes in once if it is identical; if it differs, LavBench refuses to publish.
- **Hidden files never go in:** labels and baseline submissions stay in LavBench, and so do evaluators.
- **Format:** `ZIP_STORED`, entries sorted, fixed 1980 timestamps, mode 0644. At most 2 GiB (`NANOCOLAB_PACKAGE_MAX_BYTES`) and 2,000 entries, directories included, with no ZIP64. LavBench refuses a larger environment instead of sending it.
- **Paths:** LavBench checks both the public file names and the Hugging Face folders against nanoColab's `asset_zip.safe_path` rules when they are uploaded to LavBench, so nanoColab never rejects a package for its paths.
- **Version:** `lb-<first 12 hex of the content digest>-v<N>`. The digest is the sha256 of the sorted `<sha256>  <path>` lines of the package's files; the ZIP's own hash is transport only. nanoColab binds a version name to one ZIP hash, so any change to LavBench's builder bumps `-v<N>`.
- **Upload,** as a background job, so the admin's save returns at once and shows progress: skip if `GET /v1/assets/<version>` is already READY; otherwise `POST /v1/assets/<version>/uploads` with `size_bytes` and `sha256`, PUT the ZIP to `upload.url` with `upload.headers` unchanged, `POST /v1/assets/<version>/complete`, and poll on every run until READY or FAILED (nanoColab's message goes to the admins).
- **In the workspace,** nanoColab copies the package into the workspace root, as b13c73c already does, without overwriting the student's files on a restart (`cp -Rn`). Each task's folder, `models/` and `datasets/` therefore land at the JupyterLab root, which is the layout LavBench wants: the old request 7 is done as is.

## Workspaces

- **Created on the first click.** A student's first "Open workspace" creates the workspace (`PUT /v1/events/{external_id}/workspaces/{external_user_id}`); later clicks reuse it. LavBench creates none in advance, and b13c73c refuses creation before the window anyway (request 13).
- **Launch.** "Open workspace" calls `POST /v1/workspaces/{workspace_id}/launch`. The browser form-POSTs the 60-second, single-use token to the returned `launch_url` (`/hub/launch`) in a new tab.
  - The form must not use `rel="noreferrer"`: the Hub denies a `null` Origin. `LAUNCH_ORIGINS` must be `https://bench.noai-bg.com` (request 2).
  - JupyterLab opens on the root folder until the launch accepts a start path (request 22), then on `<folder>/solution.ipynb`. The Hub's own progress page shows the first start.
  - A student who closed the tab or lost the Hub cookie starts again from "Open workspace", which took about 1 s in the run. Direct visits to the Hub should send them back to LavBench (request 21).
- **One Hub server per student.** Each student has one Hub server across all of LavBench's events (`allow_named_servers: false`), and the Hub answers 409 while another workspace runs. So LavBench refuses environment windows, from the start to the end plus grace, that overlap for the same student across all competitions.
- **After the round,** nanoColab stops and archives the workspaces at `ends_at`. Stopping one earlier, for example after a student's "Finish round", needs request 5.

## Submissions from the workspace

| Task mode | What LavBench exports, and when | Then |
|---|---|---|
| File submission | `<folder>/submission.parquet` and `<folder>/solution.ipynb`, both required, when the student clicks Submit | LavBench checks the Parquet and scores it on its own CPU evaluation workers; no student code runs |
| Notebook evaluation | `<folder>/solution.ipynb`, when the student clicks "Load from workspace" | the student picks cells in LavBench, which runs them in its own sandbox and scores the output; uploading a notebook still works |

- **Export:** `POST /v1/workspaces/{workspace_id}/export`, one path per call, base64 in JSON as b13c73c returns it, at most 20 MiB per file (`NANOCOLAB_EXPORT_MAX_BYTES`, nanoColab's default cap). LavBench re-hashes each file against nanoColab's sha256 and scores its own stored copy.
- **The right workspace.** The file must come from the requested workspace, which b13c73c does not check (request 17). LavBench's overlap rule avoids the case, but the export must check it too.
- **After the round,** reads come from the archive (`source: ARCHIVE`), which needs `internal_app` deployed (request 2). LavBench keeps its own copy of every submitted file, and the jury reads only those, under aliases, never the archives. nanoColab keeps the archives until the admin's date.

## How nanoColab responses map to LavBench

| nanoColab | LavBench code | What the person sees |
|---|---|---|
| no `NANOCOLAB_API_URL` configured | `ERR_NANOCOLAB_DISABLED` (404) | workspace features hidden |
| timeout, connection error, other 5xx | `ERR_NANOCOLAB_UNAVAILABLE` (503) | nanoColab is unavailable, try again shortly |
| 409 outside the event window, on workspace PUT or launch | `ERR_ENVIRONMENT_NOT_OPEN` (409) | the environment is not open |
| 503 with `Retry-After` on workspace PUT or launch | `ERR_ENVIRONMENT_PREPARING` (503) | "Preparing", retry in N s |
| export 409 with `Retry-After`: server stopped, or archive not ready | `ERR_WORKSPACE_EXPORT_UNAVAILABLE` (409 or 503) | open the workspace, or try again shortly |
| export 410: archive purged | `ERR_WORKSPACE_ARCHIVE_PURGED` (410) | the file is no longer available |
| export file `status: MISSING` | `ERR_WORKSPACE_FILE_MISSING`, or `ERR_WORKSPACE_NOTEBOOK_MISSING` for `solution.ipynb` (404) | the missing file and its folder |
| export file `status: TOO_LARGE` | `ERR_WORKSPACE_FILE_TOO_LARGE` (413) | the limit |
| exported bytes do not match nanoColab's sha256 | `ERR_WORKSPACE_EXPORT_INTEGRITY` (502) | a generic error; try again |
| asset FAILED | `ERR_ENVIRONMENT_PACKAGE_FAILED` | admins: nanoColab's message |
| other 4xx on an admin sync (validation, frozen field, capacity) | `ERR_ENVIRONMENT_SYNC_FAILED` (502) | admins: nanoColab's message |
| other 4xx on a student launch or export | `ERR_NANOCOLAB_UNAVAILABLE` (503) | a generic message; the detail is logged |
| readiness BLOCKED, or a failed preparation (request 19) | none; shown as the status | admins: "Problem: <nanoColab's message>"; the jury sees the state and code without the message |

nanoColab's errors come in three shapes: `detail` as a string, a dict with `message` and `fields`, or a list on 422. LavBench's client reads all three in one place and honours `Retry-After` on 409 and 503; `/v1` has no 429.

LavBench enforces nanoColab's limits before calling, so these never reach nanoColab: more than 16 export paths in an environment (`ERR_ENVIRONMENT_TOO_MANY_TASKS`, 409, with the `limit`), an empty package (`ERR_ENVIRONMENT_PACKAGE_EMPTY`), a package over 2 GiB or 2,000 entries (`ERR_ENVIRONMENT_PACKAGE_TOO_LARGE`, whose `limit` names the one exceeded), a public file name that breaks nanoColab's path rules (`ERR_INVALID_FILENAME`), a Hugging Face folder that differs between two tasks (`ERR_HF_FOLDER_CONFLICT`), an image missing from `GET /v1/images` (`ERR_INVALID_WORKSPACE_IMAGE`), overlapping windows (`ERR_ENVIRONMENT_OVERLAP`), a change after publish other than a later end (`ERR_ENVIRONMENT_LOCKED`), and an extension after `ends_at` (`ERR_EXTENSION_TOO_LATE`).

## If nanoColab fails on the day

The fallback does not depend on nanoColab:
- Admins extend the environment by the length of the outage, before `ends_at`.
- For a file task, an admin can turn on the emergency upload switch. It is off by default, needs a reason and is audited. Students then upload `submission.parquet` and `solution.ipynb` in LavBench, with the same checks and the same 20 MiB cap.
- Notebook tasks keep LavBench's notebook upload, and the public files stay downloadable from LavBench.

No nanoColab accounts are kept on standby.

## Requests to nanoColab

"For April" says whether the round on the production cluster needs it: "optional" means LavBench works around it, and "later" means after April. "Owner: us" means a PR from LavBench's side to Ivan's `feat/v1-compute-api`; "nanoColab" means the nanoColab team. None blocks LavBench's development: LavBench builds against the pinned OpenAPI file and a fake.

Rows 17-24 are new: they come from the end-to-end run of 2026-11-15, which ran Ivan's LavBench branch against b13c73c on a local stack. The first "us" PR (the local stack on Linux, export from the right workspace, pyarrow in the local image and the Hub texts) is being prepared now.

| # | Request | For April | Owner | At b13c73c |
|---|---|---|---|---|
| 1 | **Auto-start `/v1` events.** Startup selection skips events without `competition_assignments` (`startup_policy.py:44-45`); `/v1` events use `event_seats` | needed | nanoColab | not done |
| 2 | **Production wiring:** `NANOCOLAB_API_CLIENTS`, the image catalog, the export token, `LAUNCH_ORIGINS` = `https://bench.noai-bg.com`, and `internal_app` deployed (without it there is no data volume and no archive) | needed | nanoColab | not done |
| 3 | **Sync API:** `GET /v1/events`; generation and conditions; `asset_version`, `profile` and `retention_days` echoed back; machine-readable error codes (409 reasons differ only by text) | optional | nanoColab | not done |
| 4 | **Readiness:** READY means the asset staged, the startup run finished and the placeholders ready | needed | nanoColab | partly |
| 5 | **Lifecycle:** `retention_days` and `max_attendance` may grow after publish (attendance follows the roster); `POST /v1/workspaces/{id}/stop` (archive, never delete) | needed | nanoColab | not done |
| 6 | **Export:** one raw streamed file per request, plus a metadata-only mode, so the task card can show the file's size and save time before Submit; narrow the export role (`tokens` limited to students; test dropping `access:servers`) | optional | nanoColab | partly |
| 7 | **Data layout:** copying the package into the workspace root is what LavBench wants, and `cp -Rn` (`manifests.py:103`) already keeps the student's files on a restart | done as is | none | done |
| 8 | **Launch:** a higher spawn limit, placeholder pods and an image puller that work with nanoColab's controller, and a Hub cookie lifetime of about the event length (direct visits moved to 21) | needed | nanoColab | not done |
| 9 | **Auth:** two overlapping `ncak_` keys per client, each with an expiry | optional | nanoColab | not done |
| 10 | **Image:** one pinned CPU image for April, with its package list (including pyarrow) in `GET /v1/images` | needed | nanoColab (production); us (local) | partly |
| 11 | **Network:** cluster-only DNS for student pods; `HF_HUB_OFFLINE=1`; no AI extensions in images | needed | nanoColab | partly |
| 12 | **Contract:** Schemathesis in nanoColab CI; `/v1` additive-only; a tag for the commit LavBench pins | needed | nanoColab | partly |
| 13 | **Window-free workspace creation:** allow the workspace PUT after publish, before the window (`require_window`, `v1_firestore.py:355-365`); LavBench creates workspaces on the first click | optional | nanoColab | not done |
| 14 | **Cancel** an unstarted published event | optional | nanoColab | not done |
| 15 | **Image pull access** for LavBench's workers, only if its grader ever uses nanoColab's workspace image (today it uses LavBench's own task images) | optional | nanoColab | not done |
| 16 | **Large packages:** ZIP64 and up to 8 GiB per asset | optional | nanoColab | not done |
| 17 | **Export only from the requested workspace:** `live_files` (`v1_firestore.py:512-517`) reads the student's running Hub server whatever its event, so in the run a Submit for one stage returned another stage's file; answer 409 when the server is not the workspace's | needed | us | broken |
| 18 | **Workspace image:** pyarrow (LavBench takes Parquet only), scikit-learn and scipy aligned (the run printed a red `OptimizeWarning`), and the JupyterLab news prompt off | needed | us (local); nanoColab (production) | missing |
| 19 | **Readiness reports a failed preparation** (FAILED with a message), and event and workspace states move (LIVE, RUNNING, STOPPED, ENDED); the run saw SCHEDULED and REQUESTED throughout | needed | nanoColab | missing |
| 20 | **Local stack works on Linux:** pods reach the API without `host.docker.internal` (`deploy/local/up.sh`, `api.sh`), and the preparer retries a failed seed job (`deploy/local/preparer.py:142`) | needed for dev and CI | us | broken |
| 21 | **Hub for LavBench students:** a direct visit and GET `/hub/launch` redirect to LavBench; no login form; no Token page (`/hub/token`); the student's alias as the display name; messages that point to LavBench | needed | us (texts); nanoColab (redirect, config) | missing |
| 22 | **Start path on launch:** the launch accepts the path to open, the task's `<folder>/solution.ipynb` | optional | nanoColab | not done |
| 23 | **Shared Hugging Face folders:** one read-only copy on `/competition`, with links in the workspace root; the archive and the export skip the links | later | nanoColab | not done |
| 24 | **JupyterLab language:** a Bulgarian language pack, if one exists (unverified), chosen per event or from the LavBench language | later | nanoColab | not done |

## Venues (for the organisers)

- **Machines and network:** Windows or macOS with Safe Exam Browser and the venue's `.seb` config; the firewall allows only `bench.noai-bg.com` and `lab.noai-bg.com`.
- **Leaving early:** the student clicks "Finish round", which refuses launch and submit from then on; the supervisor checks the banner, then unlocks Safe Exam Browser's quit. The workspace keeps running until `ends_at`, or until LavBench stops it once request 5 lands (archive, never delete).
