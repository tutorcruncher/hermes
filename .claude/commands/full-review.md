# Full Review Command

Run a comprehensive review of a Hermes branch using four specialist agents (**architect**,
**code-reviewer**, **security-auditor**, **performance-reviewer**) plus the **Pipedrive impact survey**
(`/pd-impact`, run as a fifth agent) in **parallel** against the branch diff vs `main`, run the repo's
checks yourself while they work (lint, tests, patch coverage, migration
check), then synthesise all findings into one prioritised report and, with your approval, post the
non-security part of it onto the branch's open PR.

Hermes is a FastAPI + SQLModel + Pydantic v2 + PostgreSQL service with no UI: it receives TC2 webhooks
(HMAC-signed), the website call booker's bookings, and Pipedrive webhooks, and syncs to Pipedrive v2 and
Google Calendar. `AGENTS.md` at the repo root is the single source of truth for its conventions; every
reviewer reads it first and every "convention" finding cites it.

## Usage

```
/full-review [PR_NUMBER] [--scope PATH]
```

If no arguments are given, the command reviews the **current branch's** diff against `main`.

## Parameters

- `PR_NUMBER` — review a specific GitHub PR instead of the current branch. The review runs from the
  checkout that holds the PR's branch (see "Resolving the checkout"). Without this, the **current
  checked-out branch** is reviewed.
- `--scope {path}` — limit all five reviewers to a path subtree (e.g. `--scope app/pipedrive/` or
  `--scope app/callbooker/`). Useful for large diffs where you only care about one integration.

This command is **review-only**. It never edits source files — it produces reports and a synthesis for
you to act on, and (Step 5, with approval) publishes the public part of that synthesis onto the branch's
open PR.

## The three Hermes gates (read before anything else)

`tutorcruncher/hermes` is a **public** repository and its PRs are opened by the person running this
command. Three rules follow, and every later step is written around them:

1. **Nothing from the security review ever reaches GitHub.** Not a finding, not a count, not the fact
   that a security review ran, not the fact that something was withheld. Security findings live only in
   `${WT}/.claude/security/` and in the chat summary's local-only section. This holds even when the user
   asks to post "everything", "the full report" or "the security findings too": the answer is that the
   security part stays local and is read in the chat, and the posted review is built as Step 5 says. There
   is no override for this rule. Violating it is never acceptable.
2. **Posting to the PR needs explicit approval.** Show the exact text, ask with `AskUserQuestion`, post
   only on an explicit "Post". The event is always `COMMENT` (GitHub rejects `REQUEST_CHANGES` and
   `APPROVE` on your own PR). Never `APPROVE`.
3. **Stamping the reviewed commit needs no approval.** After the review, whether or not the post was
   approved, stamp the PR with the verdict (Step 6). The stamp carries a verdict, never a reason.

## Resolving the checkout, the tools and the scratchpad

`.claude/` is committed apart from the reports and local state (`.claude/README.md`), so every checkout has
the agents, the commands and the tools. Resolve these once at the start:

```bash
WT=$(git rev-parse --show-toplevel)                       # the checkout under review: reports go here
SCRATCH=<your session scratchpad directory>               # coverage data and other temp files
```

- Tools are always referenced as `$WT/.claude/tools/...`.
- Reports go under `${WT}/.claude/{architect,reviews,security,performance}/`, which are gitignored. Create
  these directories if they do not exist (`mkdir -p`).
- The timestamp `{TS}` is `YYYY-MM-DD-HHmm` (`date +%Y-%m-%d-%H%M`).
- Don't rely on `cd` (the cwd reverts between calls and `cd X && …` trips permission prompts): use
  `git -C "$WT"`, `make -C "$WT"`, `uv run --directory "$WT"`, `uvx --directory "$WT"` and absolute
  paths, exactly as Step 1.5 shows. The Bash tool's cwd is the checkout the session started in, which is
  not always `${WT}`.

### Resolving the checkout for `PR_NUMBER`

`gh pr view <PR> --json headRefName,headRefOid,url`. Review from a checkout of that branch: the current
one if it matches, else the worktree that holds it (`git worktree list`). Never `gh pr checkout` in the
main clone, which usually has work in progress. If no checkout holds the branch, say so and offer
`git worktree add ../hermes-<name> <headRefName>` instead of checking out over someone's work.

## Determining the diff

```bash
# Always compare against main.
git -C "$WT" fetch origin main --quiet

# Current branch (default):
git -C "$WT" diff origin/main...HEAD

# Scoped:
git -C "$WT" diff origin/main...HEAD -- <SCOPE_PATH>
```

Use the merge-base form (`origin/main...HEAD`) so the review covers only what this branch adds, not
unrelated commits already on `main`. Also run `git -C "$WT" status --short`: uncommitted changes are part
of the review, and Step 0 commits them first. If the diff is empty, say so and stop.

## Instructions

When this command is invoked, follow these steps.

### Step 0: Preflight

1. **Commit before launching the reviewers** (ask for the message only if the user has a convention you
   don't know; otherwise commit with a plain message), so the worst case is a clean `git checkout`, and
   diff the tree against HEAD when they return. Never push.
2. Resolve the PR: `PR=${PR_NUMBER:-$(gh pr view --json number --jq .number 2>/dev/null)}`. Record
   `HEAD=$(git -C "$WT" rev-parse HEAD)` and, if there is a PR, its `headRefOid`. If they differ, the
   review still runs locally, but Steps 5 and 6 do not post or stamp (line numbers would not match what
   GitHub shows). Never push to make them match.
3. `mkdir -p "${WT}/.claude/architect" "${WT}/.claude/reviews" "${WT}/.claude/security" "${WT}/.claude/performance" "${WT}/.claude/pd-impact"`.
4. Check whether another process holds the rate-limiting test port:
   `lsof -nP -iTCP:8765 -sTCP:LISTEN`. If it does, note it for Step 1.5 (deselect the class, report it).
   **Never kill that process**: it is another session's test run.

### Step 1: Run ALL FIVE reviews in parallel

**IMPORTANT: ALWAYS run fresh reviews when this command is invoked. Never reuse existing report files
from a previous run.** Each run writes new timestamped files; old files are not read or trusted.

Launch all five agents in a **single message with five parallel `Task` tool calls** (they are fully
independent). Pass each agent the resolved `${WT}`, the diff command, and the `--scope` path if one was
given.

#### 1a. Architect agent (`subagent_type=architect`)

```
Review the branch diff against origin/main for Hermes (FastAPI + SQLModel service syncing TC2,
Pipedrive and the call booker; read AGENTS.md at the repo root first). Scope: {SCOPE or "whole diff"}.
Focus on:
- Data-flow fit: TC2 -> Hermes -> Pipedrive and Callbooker -> Hermes -> Pipedrive propagate fully;
  Pipedrive -> Hermes updates Hermes ONLY and never syncs back to TC2. Anything that closes that loop
  (a Pipedrive webhook that calls TC2, a TC2 webhook that re-triggers itself through Pipedrive) is a
  circular update.
- Module layout per AGENTS.md: views.py (endpoints), process.py (business logic), api.py (external
  client), tasks.py (background sync), models.py (SQLModel in main_app, Pydantic in integrations).
  Logic in the wrong module, or duplicated across app/tc2, app/pipedrive and app/callbooker when it
  belongs in app/common or one process module.
- The field-mapping system: a new Pipedrive custom field is added once to app/pipedrive/field_mappings.py,
  once to the SQLModel in app/main_app/models.py and once to the Pydantic model in
  app/pipedrive/models.py with validation_alias=MAP['field']. No magic field-ID strings anywhere else;
  sync code must pick the field up through the map, not by hand.
- Background tasks: BackgroundTasks receive IDs, never model instances; a task opens its own session via
  get_session(); a task logs and never raises.
- Pipedrive writes: create with POST, update with PATCH and only the changed fields
  (api.get_changed_fields); no PUT, no full-object re-sends.
- Migrations: any change to app/main_app/models.py has a matching Alembic migration under
  migrations/versions/ with a single head; no migration that changes data without a reason stated.
- Settings only through app.core.config.settings; constants as ClassVar on the model; no in-function
  imports; no class Config (model_config = ConfigDict(...)).
- Scope creep: changes the branch's stated purpose does not need.
Cite the AGENTS.md section for every convention finding.
Write your report to ${WT}/.claude/architect/{TS}-pr-review.md
```

#### 1b. Code-reviewer agent (`subagent_type=code-reviewer`)

```
Review the branch diff against origin/main for Hermes (FastAPI + SQLModel + Pydantic v2; read AGENTS.md at
the repo root first). Scope: {SCOPE or "whole diff"}. Focus on:
- Correctness, readability, maintainability; modern type hints (str | None, not Optional[str]) on changed
  signatures; single quotes; f-strings; datetime.now(timezone.utc), never utcnow(); every new model has
  __str__; no comparisons with == True.
- Webhook processing edge cases that do occur: null or missing custom fields, deleted and merged
  Pipedrive entities (404/410, is_not_found), TC2 short payloads and meta_agency null, duplicate
  near-simultaneous events (the Redis cligency lock), a Pipedrive 429/403 rate-limit response.
- Pipedrive sync: PATCH with only the changed fields via api.get_changed_fields; a GET before a PATCH
  only where the diff needs the old data; errors in background tasks are logged, not raised.
- Error handling: HTTP403/HTTP404 from app.common.api.errors in endpoints; don't demand guards for
  impossible states.
- Test coverage & quality (enforced: overall coverage must stay >= 95% and every changed line must be
  covered):
  * Every test starts with an HTTP request (client.post(client.app.url_path_for('route-name'), ...)) or a
    direct background-task call; never calls process/internal functions or instantiates Pydantic models
    directly (model property tests and pure helpers are the only exception).
  * TC2 webhook tests post through tests.helpers.tc2_webhook so the body is HMAC-signed.
  * External APIs are mocked with the @patch decorator (never an inline with patch() block), async
    functions with new_callable=AsyncMock, HTTP responses with tests.helpers.MockResponse /
    create_mock_response / create_error_response / pipedrive_http_error; internal logic is never mocked.
  * Test data via db.create(Model(...)) or the factories' create_with_db; never add/commit/refresh by hand;
    no explicit IDs.
  * Response variables are named r; the whole response structure is asserted (r.json() == {...}), not
    single keys; inline select(...) without an intermediate statement variable; module-level imports only;
    a docstring and no inline comments.
  * Every new branch, including error/except paths, has a test. Name the branch and the missing test.
For each finding give file:line, severity (CRITICAL / HIGH / MEDIUM / LOW / NIT), and a concrete fix.
Write your report to ${WT}/.claude/reviews/{TS}-pr-review.md
```

#### 1c. Security-auditor agent (`subagent_type=security-auditor`)

```
Review the branch diff against origin/main for Hermes (a public-repo FastAPI service that receives
webhooks from TC2 and Pipedrive and bookings from the public website; read AGENTS.md first).
Scope: {SCOPE or "whole diff"}. Your report is LOCAL ONLY and is never posted anywhere; still, put no
customer names, emails, phone numbers or real IDs in it. Focus on:
- Inbound trust boundaries: read the check on each callback (app/tc2/views.py, app/pipedrive/views.py);
  every webhook payload is untrusted input; call-booker endpoints are public. Flag any change that adds or
  widens a dev_mode exception, weakens or skips a check, trusts a webhook-supplied ID or URL without a
  lookup, or adds an endpoint without the right check.
- Bearer-protected endpoints compare get_bearer(authorization) to settings.tc2_api_key (get-companies,
  generate-support-link); support links are signed with sign_args and checked with compare_digest plus an
  expiry. Flag timing-unsafe comparisons, missing expiry checks, or a signed value that can be forged.
- Secrets and PII: keys only from app.core.config.settings; pd_api_key, tc2_api_key, signing_key and the
  Google private key never logged, never in a response, never in a Sentry/Logfire attribute; no customer
  email/phone/name in log lines that did not already carry them; no secret in tests or fixtures.
- Injection and SSRF: user-supplied text (booking form fields, webhook payload strings) written into
  Google Calendar event descriptions, Pipedrive notes/activities, or f-string SQL; outbound requests to a
  URL taken from a payload (e.g. tc2_cligency_url) instead of built from settings.
- IDOR on lookups: endpoints that fetch a Company/Contact/Deal by a caller-supplied ID must not return
  data the caller is not entitled to.
- Dependencies: new or bumped packages pinned and reputable; known CVEs.
- CORS/headers if touched.
For each finding give file:line, severity, exploit scenario, and remediation. Mark false-positive caveats.
Write your report to ${WT}/.claude/security/{TS}-pr-review.md
```

#### 1d. Performance-reviewer agent (`subagent_type=performance-reviewer`)

```
Review the branch diff against origin/main for Hermes (FastAPI + SQLModel service; read AGENTS.md first).
Scope: {SCOPE or "whole diff"}. Hermes is small, but two resources are scarce: the Pipedrive API is
rate-limited (settings.pd_api_max_rate requests per pd_api_rate_period seconds, enforced by the
httpx_limiter transport in app/pipedrive/api.py, with 429 and Cloudflare 403 on overflow), and TC2 sends
webhooks in batches, so one event can arrive many times in a burst. Focus on:
- Pipedrive call count: a GET before every PATCH, a lookup inside a loop over contacts/deals, a re-sync of
  an unchanged object, or a retry that sleeps inside a request handler. Every extra call delays the whole
  queue. Prefer one get_changed_fields diff and one PATCH.
- Blocking in async code: synchronous HTTP, the sync Google client, or time.sleep inside an async handler
  or task; sessions or Redis locks held across an await on an external API (see the scope='function'
  session in app/pipedrive/views.py and the 10s lock lease in app/tc2/views.py).
- SQL: N+1 through lazy relationship loads in a loop (use selectinload); select(...).all() over a whole
  table where a where/limit exists; a new filter/order column without index=True and a migration;
  per-row commits.
- Background tasks that do work the request could skip, or that do the same sync twice for one webhook.
- Python hot loops: work hoistable out of a loop, O(n^2) membership scans over a list.
For each finding give file:line, severity, what happens under a TC2 webhook burst or at the Pipedrive
rate limit, and the concrete fix. Write your report to ${WT}/.claude/performance/{TS}-pr-review.md
```

#### 1e. Pipedrive impact survey (`subagent_type=general-purpose`)

```
Run the Pipedrive impact survey for the Hermes checkout ${WT}. Read ${WT}/.claude/commands/pd-impact.md
and follow its steps exactly: it is read-only (SELECT on the local hermes-prod-backup database, the Logfire
hermes-prod project, the diff and the code; never the Pipedrive or TC2 APIs, never a write, never a test run
in ${WT}). Diff: git -C ${WT} diff origin/main...HEAD. Scope: {SCOPE or "whole diff"}. Judge whether the
branch can create duplicate Pipedrive records, overwrite Pipedrive with stale Hermes data, close or delete
the wrong records, fire Pipedrive automations in bulk, blow the Pipedrive call budget or start a circular
update. Write your report to ${WT}/.claude/pd-impact/{TS}-pr-review.md. In the findings you return, keep the
counts and record ids in the report only: the finding text must make sense without them.
```

**Add this to all five briefs** (the review is posted onto the PR's diff in Step 5, and a finding that
can't be anchored is a finding nobody sees in context):

> Every finding must carry an exact **`path` + `line`**, where `line` is the line number in the file's
> **new version** and is a **changed or added line in this diff** — that is the line the comment will be
> attached to on the PR. Quote the offending line in the finding so the anchor can be verified. Review
> the changed lines; a problem in surrounding code only counts if the diff caused it, and then anchor it
> to the changed line that caused it. Give each finding a one-word category (correctness, performance,
> code-quality, architecture, test-coverage, security). Findings only: no praise, no commentary; "no
> findings" is a valid result.

The four agent definitions carry a "Shared checkout: read-only" section (no edits, checkouts, stashes,
mutation tests or test runs in `${WT}`): you are working in that checkout while they run. In Hermes a
reviewer's pytest run would also fight yours for the rate-limiting test port 8765 and append to the
same coverage data. Don't ask an agent to run tests there; run what a finding needs yourself afterwards.

**All five must run concurrently** — issue them as parallel tool calls in one message, not sequentially.

### Step 1.5: Run the checks yourself while the reviewers work

Run each as its own Bash call. A failing check is a **Blocker**; it enters Step 2 like any reviewer
finding and prevents an `APPROVED` stamp.

1. **Lint**: `make -C "$WT" lint` (ruff check over `app/` and `tests/`). Also run
   `uv run --directory "$WT" ruff format --check app/ tests/`: a formatting diff is a Nit, not a Blocker.
2. **Tests + coverage** (SQLite, no Postgres needed; `COVERAGE_FILE` keeps the data file out of the
   checkout, because `pyproject.toml` sets `--cov-append`):
   ```bash
   COVERAGE_FILE=$SCRATCH/.coverage uv run --directory "$WT" pytest tests/ -q --cov=app --cov-branch \
     --cov-fail-under=95 --cov-report=term --cov-report=xml:$SCRATCH/coverage.xml
   ```
   If Step 0 found port 8765 held by another process, add
   `--deselect tests/pipedrive/test_rate_limiting.py`, say so in the synthesis and the chat summary,
   and treat the rate-limiting tests as not run. Never kill the process that holds the port.
   A failed test or a total below 95% is a Blocker.
3. **Patch coverage** (the number Codecov enforces on the PR):
   ```bash
   uvx --directory "$WT" diff-cover $SCRATCH/coverage.xml --compare-branch=origin/main --fail-under=100
   ```
   **Every uncovered changed line is a High finding anchored to that line** (`path:line`, with the line
   quoted). List them individually; "coverage dropped" is not a finding.
4. **Migration check**, only if the diff touches `app/main_app/models.py`. Alembic is configured by
   `alembic.ini` plus `[tool.alembic]` in `pyproject.toml` (`script_location = migrations`), and
   `migrations/env.py` imports the app settings, so it needs `REDISCLOUD_URL` and a `DATABASE_URL`.
   - The diff must add a file under `migrations/versions/` (`git -C "$WT" diff --name-only
     origin/main...HEAD -- migrations/versions`). None → **Blocker**: "model changed, no migration; run
     `make migrate-create msg=\"...\"` and review the generated file".
   - `uv run --directory "$WT" alembic heads` must print exactly one head. Two → Blocker (the branch's
     migration must `down_revision` from main's current head).
   - If local Postgres is up (`pg_isready`), prove the migration matches the models on a throwaway
     database, then drop it:
     ```bash
     createdb hermes_review_check
     DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hermes_review_check \
       REDISCLOUD_URL=redis://localhost:6379 uv run --directory "$WT" alembic upgrade head
     DATABASE_URL=postgresql://postgres:postgres@localhost:5432/hermes_review_check \
       REDISCLOUD_URL=redis://localhost:6379 uv run --directory "$WT" alembic check
     dropdb hermes_review_check
     ```
     `alembic check` printing anything other than `No new upgrade operations detected.` is a Blocker
     (the migration does not cover the model change). If Postgres is not up, say the autogenerate check
     was skipped.

Record every check's result (command, pass/fail, the decisive output line) for the synthesis.

### Step 2: Collect and synthesise

Once all five agents have finished and the checks are done:

1. Read the **architect, code-reviewer, performance and Pipedrive impact** reports and the check results.
   The Pipedrive impact report holds prod counts, record ids and names: carry its findings into the
   synthesis as code risks in words only, never with its numbers, ids or names (the synthesis feeds the
   posted review). The numbers go in the chat summary (Step 4) and stay in `${WT}/.claude/pd-impact/`.
2. Read the **security-auditor** report separately and keep it separate: its content goes only into
   `${WT}/.claude/security/` files and the chat summary's local-only section (Step 4). It is never an
   input to the posted findings or summary (Step 5).
3. **Isolate security-flavoured findings from the other three reviewers.** Any finding, from any
   reviewer, whose subject is authentication or authorisation, webhook signature or secret handling,
   injection, SSRF, IDOR, PII or secret exposure in logs or responses, dependency CVEs, CORS, or the
   `dev_mode` bypass is a security finding regardless of who raised it. Move each one, verbatim with its
   reviewer and anchor, to `${WT}/.claude/security/{TS}-withheld.md`, and drop it from the material
   Steps 3 and 5 use. When in doubt, withhold: a withheld correctness finding costs a chat line; a posted
   security finding is public.
4. Verify every remaining finding at its `path:line` against the code. Drop anything wrong or not caused
   by the diff; fix drifted line numbers to the changed line in the current diff.
5. Categorise every remaining finding:
   - **Blocker** — a failing check (lint, tests, coverage < 95%, missing or mismatched migration),
     data loss, a sync that writes wrong data to Pipedrive, a circular TC2/Pipedrive update, a
     background task that raises or holds a session/lock across an external call.
   - **Correctness** — logic bugs, unhandled webhook edge cases that do occur, wrong PATCH payloads.
   - **Performance** — extra Pipedrive calls, blocking in async code, N+1 SQL, missing index.
   - **Code quality** — AGENTS.md convention violations (test rules, hardcoded URLs, in-function imports,
     `response =`, mocking internal logic, inline `with patch()`), readability, type hints.
   - **Architecture** — wrong module, duplication, field-mapping bypass, settings access, scope creep.
   - **Test coverage** — uncovered changed lines (each one a High finding anchored to the line), missing
     branch tests, weak asserts.
6. Mark **consensus** items (flagged by ≥2 reviewers): highest confidence.
7. Note any **contradictions** between reviewers and resolve or surface them.

The security report and the withheld file get the same verification pass (step 4) so the chat summary and
the verdict rest on confirmed findings, but that work happens in the security files, not in the synthesis.

### Step 3: Generate the synthesis report

Write `${WT}/.claude/reviews/{TS}-full-review-synthesis.md` containing:

- **Summary** — the diff reviewed (branch or PR #, scope, HEAD sha), per-reviewer finding counts for
  architect, code-reviewer, performance and the Pipedrive impact survey, and the check results (lint, format, tests, overall and
  patch coverage, migration check, whether rate-limiting tests ran).
- **Findings by priority** — Blocker → Correctness → Performance → Code quality → Architecture → Test
  coverage. Each item: `file:line`, severity (Blocker / High / Medium / Nit), one-line description,
  recommended fix, and which reviewer(s) raised it.
- **Consensus items** — issues multiple reviewers independently flagged.
- **Disagreements** — where reviewers conflict, with your adjudication.
- **Recommended actions** — an ordered, actionable checklist (fix Blockers first).
- A final one-line pointer: `Security: local only, see .claude/security/{TS}-pr-review.md and
  {TS}-withheld.md`. No security content in this file: the posted summary is derived from it.

### Step 4: Present results to the user

Return a concise chat summary:

- The verdict (Step 6's value) and what decided it.
- Check results: lint, format, tests (and whether the rate-limiting class ran), overall coverage, patch
  coverage with each uncovered line, migration check.
- Per-reviewer finding counts and where each full report lives.
- The Pipedrive impact survey's findings with their prod counts and the backup's age (chat only, never
  posted).
- **Blocker / High** items that must be addressed before merge, as `file:line` plus one line each; counts
  for Medium and Nit.
- **Consensus** items (multiple reviewers agree) and any reviewer disagreements.
- Path to the synthesis report.
- The URL of the review posted to the PR, or "not posted" with the reason (no PR, user declined, HEAD
  differs from the PR head).
- The stamp result (Step 6).
- Last, a section headed exactly **`## Local only: security (never posted)`** with every finding from
  the security-auditor report and the withheld file, each as `file:line`, severity, one line, fix. If
  there are none, say "none". This section is the only place security findings are reported outside
  `${WT}/.claude/security/`.

Do **not** modify any source files — this command only reports.

### Step 5: Post the public part of the review to the PR (approval required)

Skip this step, and say so in the summary, when there is no open PR, or when local HEAD differs from the
PR's `headRefOid` (report locally; say the PR is behind or ahead; never push to make it match).

#### 5a. Build the findings + summary from the synthesis, security stripped

Both files are built from the Step 3 synthesis only. Never open a `${WT}/.claude/security/` file while
building them.

- **`${WT}/.claude/reviews/pr-${PR}-findings.json`** — a JSON array, one object per distinct finding.
  Written inside the checkout, not `/tmp`: a shared `/tmp` path let another session's review overwrite
  these between the dry run and the post.
  ```json
  [{ "path": "app/pipedrive/tasks.py", "line": 142, "severity": "High",
     "body": "**CLAUDE SAYS:**\n\nThe PATCH sends the whole org payload; diff it with api.get_changed_fields(old, new) first and send only the changed keys." }]
  ```
  - `severity`: Blocker / High / Medium / Nit.
  - `body`: objective — the issue **and** the concrete fix. No praise, no commentary. **Prefix every
    finding body with `**CLAUDE SAYS:**` yourself**: `post_pr_review.py` only prefixes the summary.
  - Dedupe across reviewers; if two flagged the same line, merge them and note "(architect + performance)".
  - **Every finding that is about code gets an inline anchor.** `path`/`line` are the file's
    **new-version** line and must be a changed/added line in the PR diff. If a reviewer's line number has
    drifted, find the line in the current diff and use that. Only a finding genuinely not tied to a line
    (architecture, a missing test file, a cross-cutting gap) omits `path`/`line` and goes in the summary.
  - **Public-repo hygiene**: no customer or agency names, emails, phone numbers, IP addresses, API keys
    or tokens, Pipedrive/TC2 record IDs of real customers, or internal volumes and counts (customers,
    revenue, request rates) in any body. Describe the pattern, not the record.
- **`${WT}/.claude/reviews/pr-${PR}-summary.md`** — the objective synthesis: one-line assessment, the
  verdict, the check results (lint, tests, overall and patch coverage, migration check), consensus items
  (≥2 reviewers), and any cross-cutting notes. The same hygiene rule applies. The poster prepends
  `**CLAUDE SAYS:**` to this one, so don't add it here.
  - The summary **does not mention security at all**: no security section, no counts, no "security
    review ran", no "some findings withheld", no "see local report". Reviewer counts in the summary are
    for architect, code-reviewer and performance only. The verdict is stated as a word
    (`CHANGES_REQUESTED`) with the public reasons only; if the only reason is a withheld finding, state
    the verdict without a reason.

#### 5b. Mandatory security keyword self-check

Before the dry run, grep both files. This is not optional and is repeated after every edit to them:

```bash
grep -n -i -E 'secur|authn|authz|authent|authori|unauth|signature|hmac|secret|token|api[_ -]?key|credential|inject|ssrf|idor|xss|csrf|cve|vulnerab|exploit|pii|cors|dev_mode|bypass|leak|withheld|withhold|redact|password|sanitis|sanitiz|expos' \
  "${WT}/.claude/reviews/pr-${PR}-findings.json" "${WT}/.claude/reviews/pr-${PR}-summary.md"
```

The required result is **no output**. On any hit: if the finding is security-flavoured, move it to
`${WT}/.claude/security/{TS}-withheld.md` and delete it from the file; if the word is incidental in a
non-security finding, reword the finding so the term is gone. Then run the grep again. Do not proceed to
5c while the grep prints anything.

#### 5c. Dry run, then show the user exactly what would be posted

```bash
python3 "$WT/.claude/tools/post_pr_review.py" "$PR" \
  --findings "${WT}/.claude/reviews/pr-${PR}-findings.json" \
  --summary "${WT}/.claude/reviews/pr-${PR}-summary.md" --dry-run
```

Any line printed as `SUMMARY` is a code finding that would lose its anchor: re-anchor it to the changed
line it is about (open the diff, find the line), re-run 5b, and dry-run again. Only findings with no
`path` at all should be left for the summary.

Then present, in the chat, the **full text** of what would be posted: every inline finding as
`path:line` + severity + its complete body, and the complete summary body. Not a paraphrase: the user
approves the exact text. Then ask with `AskUserQuestion`:

- question: "Post this review to PR #<N>?"
- options: **"Post this review to PR #<N>"** / **"Don't post"**

Post only on an explicit "Post". "Don't post", no answer, or any other reply means the review stays
local; say so in the summary and continue to Step 6. If the user asks to add the security findings or
to post "everything", explain that the security part never leaves the machine (gate 1), point them to the
chat section, and ask again whether to post the review as shown.

#### 5d. Post one GitHub review

```bash
python3 "$WT/.claude/tools/post_pr_review.py" "$PR" \
  --findings "${WT}/.claude/reviews/pr-${PR}-findings.json" \
  --summary "${WT}/.claude/reviews/pr-${PR}-summary.md" \
  --event COMMENT
```

The event is always `COMMENT`: Hermes PRs are the user's own, and GitHub rejects `REQUEST_CHANGES` and
`APPROVE` on your own PR (the helper keeps those choices for a PR someone else opened, but this command
never uses `APPROVE`; a bot shouldn't formally approve a PR). The helper inlines every finding whose
`path:line` is a commentable line in the diff, folds the rest into the summary, falls back to a body-only
review if GitHub rejects an inline line, and prints the review URL + counts. Report those counts back to
the user — a code finding that ended up in the summary means the anchor was wrong, not that the diff
couldn't take it. Post exactly the files the user saw; if anything in them changed after the approval,
show the new text and ask again.

### Step 6: Stamp the reviewed commit (no approval needed)

If the branch has an open PR, stamp it now, whether or not Step 5 posted. Do not ask: the stamp is a
verdict marker in the PR description, not a review. Skip it (and say so) only when local HEAD differs
from the PR's `headRefOid`.

```bash
python3 "$WT/.claude/tools/pr_review_stamp.py" \
  stamp "$PR" "$(git -C "$WT" rev-parse HEAD)" --verdict <APPROVED|CHANGES_REQUESTED|BLOCKED>
```

The verdict counts **every** confirmed finding, including the security-auditor's and the withheld ones:

- `BLOCKED` — any Blocker stands (a failing check, or a Blocker-severity finding from any reviewer,
  security included).
- `CHANGES_REQUESTED` — no Blocker, but at least one High stands (an uncovered changed line is High).
- `APPROVED` — nothing above Medium stands.

The stamp never states a reason, and the chat summary gives the public reasons and keeps the security
ones in the local-only section. The stamp upserts a single banner at the top of the PR body and preserves
the rest. Don't stamp `APPROVED` while blocking findings stand — the stamp is the signal that HEAD is
cleared to hand off.

## Report Locations

- Architect report: `${WT}/.claude/architect/{YYYY-MM-DD-HHmm}-pr-review.md`
- Code review report: `${WT}/.claude/reviews/{YYYY-MM-DD-HHmm}-pr-review.md`
- Security report (local only): `${WT}/.claude/security/{YYYY-MM-DD-HHmm}-pr-review.md`
- Withheld security-flavoured findings from other reviewers (local only):
  `${WT}/.claude/security/{YYYY-MM-DD-HHmm}-withheld.md`
- Performance report: `${WT}/.claude/performance/{YYYY-MM-DD-HHmm}-pr-review.md`
- Pipedrive impact report (local only: prod counts and ids): `${WT}/.claude/pd-impact/{YYYY-MM-DD-HHmm}-pr-review.md`
- Synthesis: `${WT}/.claude/reviews/{YYYY-MM-DD-HHmm}-full-review-synthesis.md`
- Posted findings and summary: `${WT}/.claude/reviews/pr-{PR}-findings.json`, `pr-{PR}-summary.md`
- Coverage data: `$SCRATCH/.coverage`, `$SCRATCH/coverage.xml` (never in the checkout)

## Examples

### Review the current branch (default)

```
/full-review
```

Diffs the current branch against `main`, runs all five reviewers in parallel and the checks, synthesises,
presents the report, asks before posting, stamps.

### Review a specific PR

```
/full-review 450
```

Reviews PR #450 from the checkout that holds its branch, diffs against `main`, and runs the full parallel
review.

### Scoped review

```
/full-review --scope app/pipedrive/
```

All five reviewers focus only on the `app/pipedrive/` subtree of the diff.

### Scoped review of a PR

```
/full-review 450 --scope app/callbooker/
```

## Success Criteria

The command is complete when:

- All five reviews (architect, code-reviewer, security-auditor, performance-reviewer, Pipedrive impact
  survey) ran **fresh** and in **parallel**, each writing a timestamped report under
  `${WT}/.claude/{architect,reviews,security,performance,pd-impact}/`.
- Lint, the test suite with coverage, patch coverage via diff-cover and (when models changed) the
  migration check ran, and every failure or uncovered changed line became a finding.
- A synthesis report has been written to `${WT}/.claude/reviews/{TS}-full-review-synthesis.md` with no
  security content in it.
- A prioritised summary has been presented, with Blocker/High and consensus items called out, the
  security findings in the `## Local only: security (never posted)` section only, and no source files
  modified.
- **If the branch has an open PR** at the same HEAD: the public findings and summary passed the keyword
  self-check with no hits, the dry run showed every code finding inline, the user saw the exact text and
  answered the `AskUserQuestion`, and the review was posted with `--event COMMENT` only on an explicit
  "Post" — or the summary states why it was not posted.
- The reviewed HEAD was stamped with the verdict (no approval asked), or the summary states why not (no
  PR, or HEAD differs from the PR head).
- Nothing from `${WT}/.claude/security/` reached GitHub.
