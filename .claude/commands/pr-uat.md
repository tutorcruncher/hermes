Test a Hermes PR, or any test the user describes, by hand on a real local stack (web server, Postgres, Redis, fake Pipedrive, TC2 and Google Calendar, test keys, nothing real reachable). Derive cases from the diff, take any extra cases the user gives, drive each one as the real caller would, check Postgres, the web log and what the fake services received, and capture terminal screenshots. With a PR, publish the evidence into the PR description. With no PR, stay local.

Ported from TutorCruncher2's `/pr-uat`. Hermes has no UI, so cases run through HTTP requests and the evidence is terminal screenshots.

## Usage

```
/pr-uat                        the open PR for this branch
/pr-uat <PR#> [extra cases]    that PR, plus any extra cases
/pr-uat <any test described>   ad hoc: just these cases, local only, nothing published
```

`<PR#>` that is not this branch's PR means running from the checkout that holds that branch. The stack always runs the checkout you are in. With no PR and no cases, ask what to test.

## Hard rules

- **Any case the user gives is run.** Add it to the checklist as written, whichever area of Hermes it touches and whether or not the diff touches it. Never drop, merge or reinterpret it. If it cannot run, mark it NOT RUN with the reason. Existing test coverage is never a reason to skip a case: the tests mock Pipedrive and run on SQLite, and this does not.
- **Synthetic data only.** This repository and its `pr-screenshots` branch are public, and every uploaded image is public. Use placeholders (`uat@example.org`, `UAT Agency`, made-up names and numbers). Never copy a value from Logfire, Sentry, the prod backup or any real system into a case. Read every screenshot for real data before it is uploaded.
- **A security-related PR is never published.** If the PR changes authentication, a signature or secret check, or fixes a weakness, run it as a local run: stop after the gate, upload nothing, add nothing to the PR. Give the result in the chat only.
- **Only `stack.sh`'s stack.** It uses test keys and fake services, and refuses a remote database or Redis. Never point a case at real Pipedrive, TC2, Google or production, and never edit `.env` for a run.
- **Nothing is fixed mid-run.** Log a bug with its repro and severity, then carry on.
- **Report failures as failures.** Publish them with their evidence and never soften them.

## 1. Plan

Set `RUN_DIR=<checkout>/.claude/uat/<PR#>-<yyyy-mm-dd>` (`adhoc-<slug>-<yyyy-mm-dd>` with no PR), always absolute, and create `$RUN_DIR/screenshots/`. It is gitignored.

With a PR, read `git diff origin/main...HEAD` and the PR body, then derive cases: success, errors, bad credentials, settings on and off, a service failing, edge cases. Add the user's cases. With no PR, the user's cases are the plan, plus any check needed to prove each one.

Write `$RUN_DIR/checklist.md` before testing, with cases on exactly this shape (`gate.sh` parses it):

```
- [ ] 1.1 Booking creates the deal -> p1-01-01-book.png, p1-01-02-pipedrive.png
- [x] 1.1 Booking creates the deal -> p1-01-01-book.png, p1-01-02-pipedrive.png | PASS: one deal, open
- [x] 1.2 Bad signature is refused -> p1-02-01-call.png | FAIL: returned 200, expected 403. Severity: high
- [n] 1.3 Case that cannot run -> NOT RUN: reason
```

Every surface a case names gets its own image: "in Hermes and in Pipedrive" is two. Write what you expect to see in each store before acting, and compare against that afterwards. Log anything you change outside the API under `## Mutations` so it can be undone.

Send the user progress at the end of each phase.

## 2. Start the stack

```bash
<checkout>/.claude/commands/pr-uat/stack.sh start <checkout> --fresh
```

It prints the URL and an `env.sh` for journeys to `source`, and starts everything on this checkout's code. It builds its own database `hermes_uat_<n>` with `alembic upgrade head`, so a branch's migration runs, and seeds one admin, three pipelines, one stage and the `Config` row. Use `--fresh` for the first start of a run. Leave it off when restarting mid-run, to keep the data.

- A setting a case needs goes on the environment of `start`, e.g. `SYNC_CREATE_DEALS=false stack.sh start <checkout>`. Re-run `start` to change one, and after any code change: the server does not reload.
- Service keys, service URLs and telemetry settings cannot be overridden.
- `stack.sh status <checkout>` shows what is running and the log paths.
- A migration or a `patch.py` case: build the old state by hand, log it under `## Mutations`, and run the command against the stack's database by sourcing `env.sh` first.

## 3. Run each case

For each case, in order:

1. **Act as the caller.** Call the endpoint TC2, Pipedrive or the website would call. A direct SQL insert proves nothing about an endpoint.
2. **Check every store the case names**, before and after. Background tasks run after the response, so wait for the web log line (`$STACK_DIR/web.log`) before reading the result.
3. **Capture every surface**, then read each image. A traceback, an unexpected 500 or wrong data in the shot is a finding, even if it is not what the case was about and even if it was already there.
4. **Update the checklist.**

### What to drive

`env.sh` gives you these helpers. Each prints the HTTP status after the body.

| To test | Do this |
|---------|---------|
| A TC2 webhook | `tc2_hook '<json>'` signs the body as Chronos does. See `sample_tc_client_data` in `tests/tc2/test_tc2_integration.py` for the payload, and set `sales_person.id` to `1` |
| A Pipedrive webhook | `pd_hook '<json>'` sends the Basic auth. See `tests/pipedrive/test_views.py` for payloads. Take `hermes_id` and `pd_*_id` values from the rows and from `calls` |
| The website | `public <METHOD> <path>`. `POST /callbooker/sales/book/` with an `admin_id` of `1`, a future `meeting_dt` inside `10:00` to `17:30` London time, and a `price_plan` of `payg`, `startup` or `enterprise` |
| TC2-facing endpoints | `api <METHOD> <path>` sends the bearer key |
| A wrong or missing credential | Plain `curl`, with a wrong key or none |
| What Pipedrive, TC2 or Google received | `calls` for everything, `calls deals` for one path fragment. It reads `$STACK_DIR/service-requests.jsonl` |
| Pipedrive holding an object | Pipedrive keeps what Hermes created, so a later GET or PATCH sees it. Anything else is a 404, which is how a deleted object looks |
| TC2 returning a client | Write `$STACK_DIR/tc2-clients/<id>.json`. No file means a 404 |
| A busy calendar | Write `[{"start": "...", "end": "..."}]` to `$STACK_DIR/google-busy.json` |
| A service failing | `fail_next <status> <path fragment> [count]`, e.g. `fail_next 429 persons` or `fail_next 500 deals 2` |
| Anything else | Find the route in `app/`, call it the way its real caller does, and read the stores it writes |

Postgres tables: `admin`, `company`, `contact`, `deal`, `meeting`, `pipeline`, `stage`, `config`.

### Capturing evidence

Screenshots show only real commands and their real output. All narration lives in the checklist and the PR description.

```bash
<checkout>/.claude/commands/pr-uat/setup-terminal.sh     # once, prints the harness URL
<checkout>/.claude/commands/pr-uat/write-case.sh <checkout> '<title>' <<'JOURNEY'
source /tmp/uat-stack-.../env.sh
body='{"admin_id":1,"name":"uat tester","email":"uat@example.org","country":"GB","company_name":"UAT Agency","estimated_income":"1000","currency":"GBP","meeting_dt":"2030-07-03T10:00:00Z","price_plan":"payg"}'
run "public POST /callbooker/sales/book/ -d '$body'"
sleep 2
run "psql \"\$DATABASE_URL\" -x -c 'select id, status, pd_deal_id from deal order by id desc limit 1'"
run "calls deals"
JOURNEY
```

`run` prints a command before running it. Use the real path from `stack.sh`'s output in place of `/tmp/uat-stack-...`.

Then, with whichever browser MCP the session has:

1. Navigate to the harness URL. Each navigation runs the case again in a fresh terminal, so a booking case books again.
2. Wait on elapsed time, because a canvas terminal cannot be read by a text wait.
3. Take the screenshot in a **later message**, to `$RUN_DIR/screenshots/<planned name>` by absolute path. Calls in one message run together and would capture a blank terminal.
4. Crop it: `uv run --with pillow python <checkout>/.claude/commands/pr-uat/crop-terminal.py <image>`.
5. Read the image and confirm the output is complete.

The terminal is 40 rows. For more, `TSH_ROWS=<n> setup-terminal.sh`, write the case again, and take a full-page shot. Do not `2>/dev/null` a command in a journey, because its output vanishes; use `2>&1 | grep -v claude-code-hint`. Avoid commands that print home-directory paths.

With no browser MCP, save each journey's output to `$RUN_DIR/screenshots/<case>.txt`, tell the user there are no screenshots, and do not publish.

## 4. Gate

```bash
<checkout>/.claude/commands/pr-uat/gate.sh "$RUN_DIR"
```

It must pass before anything is published. Report its counts. If it fails, capture what is missing and run it again.

## 5. Publish (PR runs only)

An ad hoc run or a security-related PR stops here: give the user the verdict and `$RUN_DIR`, then go to step 6.

Upload with the script, which uses the REST API only. Never improvise with git objects: an empty SHA in a push can delete the branch.

```bash
<checkout>/.claude/commands/pr-uat/upload-screenshots.sh tutorcruncher/hermes pr-screenshots \
  uat-<PR#>-<yyyy-mm-dd> "$RUN_DIR/screenshots"
```

Then fetch the current PR body, append a `---` and the section below, and patch it with `gh api -X PATCH repos/tutorcruncher/hermes/pulls/<n> --input payload.json` (build it with `jq -Rs '{body: .}'`). Never touch other sections. If you patch again, rebuild from the original body so the section is not doubled.

```markdown
### Manual Testing

- [x] **Phase 1: <group name>**
  <details><summary>Test cases</summary>

  - [x] 1.1 <short plain description>. <What the screenshots prove>
    <details><summary>Screenshots</summary>

    <img width="820" src="https://github.com/tutorcruncher/hermes/raw/pr-screenshots/<dir>/<image>">
    </details>

  </details>
```

Show failed cases as `- [ ]` with **FAIL** and NOT RUN cases with their reason. Use short, plain wording, and no customer data or internal volumes. Re-fetch the body and confirm the section appears once and every uploaded filename is in it.

## 6. Clean up

Undo everything under `## Mutations`, remove any temporary prints from the code, and run `stack.sh stop <checkout>`. Leave `$RUN_DIR` in place. Finish with the verdict, the gate's counts and every failure.
