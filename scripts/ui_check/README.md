# UI visual check

Screenshots every LavBench page and interactive scenario on a real stack, for every role,
at desktop (1280 px), tablet (820 px) and phone (390 px) widths, in English and Bulgarian,
in the dark and light themes. Each screenshot also records:

- browser console and page errors;
- horizontal overflow (the page wider than the viewport);
- whether every scripted step worked (a button or row that could not be found is reported).

axe-core accessibility checks run for each scenario on desktop in English, in both themes.

Run it for every pull request that changes the frontend, and review the contact sheets
before asking for review.

## Requirements

- Docker. The capture runs in an image built from `Dockerfile`: the official
  `mcr.microsoft.com/playwright/python:v1.63.0-noble` image (browsers included) plus the
  packages pinned in `requirements.txt`. `run.sh` builds it; later builds come from the cache.
- A Python on the host with `pandas` and `pyarrow` for the seed and state scripts, for example
  `PYTHON="micromamba run -n lavbench_backend python"`.
- A **throwaway** stack with an evaluation worker. `stack.sh` starts one the way the CI
  `docker-build` job does. The check creates challenges, users and submissions, finalises a
  challenge and archives another, so never run it against data you want to keep.

## Running

```bash
scripts/ui_check/stack.sh up            # build and start; HTTPS_PORT=8443 if 443 is taken
PYTHON=python3 make ui-check            # the full check, about 20 minutes
scripts/ui_check/stack.sh down          # remove the stack and its volumes
```

Re-capture a few scenarios after a fix (the stack and `seed.json` from the last full run
must still exist; rebuild changed images first with `stack.sh up`):

```bash
scripts/ui_check/run.sh --only competitor--submission-platform-error,admin--panel-backups
```

Screenshots run in parallel browsers, 6 by default; set `UI_CHECK_WORKERS` to change that
(1 runs them one at a time). Each role logs in once per phase and its windows share the
session. After each step the check waits until the page has had no open request for 400 ms,
plus 400 ms for transitions; event streams are ignored.

Output goes to `ui-check-output/` (git-ignored, override with `UI_CHECK_OUT`):

| Path | Content |
|---|---|
| `index.html` | One section per scenario: step results, console errors, overflow, axe findings and its contact sheet, with links to every full screenshot |
| `sheets/<role>--<scenario>.png` | Contact sheet: a row per viewport, a column per language and theme |
| `shots/<role>--<scenario>--<viewport>-<lang>-<theme>.png` | Full-page screenshots |
| `report.json` | The same results, machine-readable |

## Phases

`run.sh` seeds the stack (`seed.py`), then alternates state changes (`states.py`) and
capture phases (`capture.py`):

| Phase | State before it | Covers |
|---|---|---|
| `main` | seeded | login and its errors, keyboard focus, every competitor page, the cell picker and an oversized notebook, completed, failed and platform-error submissions, leaderboards and their tabs, docs per role, empty states, every admin and jury tab, task create and edit (all form tabs), stage create and edit modals, user edit, bulk reset prompt, manual points modal (on a task tab, where grading happens) |
| `live` | a long-running submission | live log streaming, the admin kill button and its confirmation, the queue with a running item |
| `actions` | (runs once each) | final selection saved, manual points saved, backup created, competitor registered, CSV import, leaderboard updating live over SSE |
| `frozen` | emergency freeze on | frozen challenge, submit blocked |
| `grace` | stage deadline just passed, a submission made in grace | the grace timer and the grace submission in the list |
| `archived` | empty challenge archived (runs while the grace window closes) | login refused for its competitor |
| `after-grace` | grace window over | the grace submission still viewable, submission closed after the deadline, the stage finalize modal (admin and jury) |
| `ended` | the jury's points entered, the stage final with results revealed, the challenge ended | the challenge finalize modal (admin and jury), the ended challenge, stage results revealed to competitors, private stage scores for the jury |
| `final` | challenge finalised, results revealed | final leaderboards (private scores visible to the jury), locked submissions, read-only manual points |

## Reviewing

Open `index.html`. For each scenario check, in this order:

1. **Steps:** "all worked". A failed step means the screenshot does not show the intended state.
2. **Console errors:** none, except the expected `401` responses on the login page (the
   session probe and the failed login) and the `413` of the oversized notebook.
3. **Horizontal overflow:** none.
4. **The contact sheet:** text fits in both languages, both themes are readable, nothing overlaps
   or is cut off, and the state matches the scenario name.
5. **axe:** new violations on elements your change added.

## Adding a scenario

Scenarios live in `capture.py` `scenarios()`, per phase, as
`(role, name, path, steps, options)`:

- `role`: `anonymous`, `competitor` (or `competitor2`, `competitor3`), `empty_competitor`,
  `jury` or `admin`;
- `path`: where the browser starts;
- `options`: `{"variants": ONE}` for steps that change data, so they run once. These run
  one at a time, in the listed order, after the phase's other scenarios.

Steps:

| Step | Does |
|---|---|
| `("button", key)` | Click the first visible button whose text starts with the translation of `key`; opens the phone menu if needed (`button_last` takes the last match) |
| `("button_in", text, key)` | Click the button labelled `key` inside the row that contains `text`, for labels shared by several buttons |
| `("text", text)` / `("text_key", key)` | Click the first element containing the text |
| `("title", key)` | Click the element whose `title` is the translation of `key` |
| `("sub", submission_id)` | Click the submission row with that id |
| `("upload", "notebook" \| "oversized")` / `("upload_css", selector, file)` | Set a file input |
| `("fill_label", key, value)` / `("fill_placeholder", key, value)` | Fill a form field |
| `("select_label", key, option)` | Open the dropdown labelled `key` (a `ui/SelectField` or a native select) and pick the option whose text contains `option` |
| `("form_submit", index)` | Submit the n-th form on the page; reported as failed when a field is left invalid |
| `("press", key, times)` | Press a key, for example `Tab` for focus states |
| `("login_fail",)` / `("login_as", seed_key)` | Use the login form |
| `("api_submit", task_id)` | Submit a correct solution through the API as the scenario's user |
| `("wait", ms)` | Wait a fixed time, for example for a log to stream (other steps wait for the network) |

Labels come from the locale files, so a scenario works in both languages. A new seeded object
goes in `seed.py`; a new state change goes in `states.py` and `run.sh`.
