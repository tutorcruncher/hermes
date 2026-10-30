# Hermes review system (`.claude/`)

A port of TutorCruncher2's review, UAT and sync-impact commands, tailored to Hermes (FastAPI + SQLModel,
public repo `tutorcruncher/hermes`, default branch `main`). The review rules come from `AGENTS.md` at the repo
root.

## What is committed

`README.md`, `agents/`, `commands/` and `tools/` are committed, so every checkout and worktree has them.
Everything else under `.claude/` is gitignored: review reports, security reports, Pipedrive impact reports,
UAT runs and local settings. Those must never be committed, because this repo is public.

## What lives here

```
commands/full-review.md    the review command (four reviewers + checks + synthesis + post + stamp)
commands/review-status.md  is this PR's HEAD reviewed and cleared to hand off?
commands/pd-impact.md      how a branch's Pipedrive writes meet production data (read-only, local report)
commands/pr-uat.md         hand-test a PR on a local stack with fake services, and publish the evidence
commands/pr-uat/           the stack, the fake services, the terminal harness, the gate and the upload script
agents/                    architect, code-reviewer, security-auditor, performance-reviewer
tools/post_pr_review.py    posts findings + summary as one GitHub review (inline comments on changed lines)
tools/pr_review_stamp.py   stamps / checks the reviewed commit in the PR description
architect/ reviews/ security/ performance/ pd-impact/ uat/
                           gitignored output; the synthesis and the posted files go under reviews/
```

## Run a review

```
/full-review                       # review the current branch's diff vs main
/full-review 450                   # review PR #450 from the checkout that holds its branch
/full-review --scope app/pipedrive/
/review-status [450]               # has HEAD been reviewed and stamped APPROVED?
```

`/full-review` runs the four reviewers in parallel (each writes a timestamped report), runs the checks
itself (`make lint`, the test suite with coverage, patch coverage with `diff-cover`, an Alembic check
when `app/main_app/models.py` changed), verifies and synthesises the findings, and presents them in the
chat. It never edits source. The tests use SQLite and need port 8765 free for the rate-limiting class;
if another process holds it, that class is deselected and reported, never killed.

## Run a UAT

```
/pr-uat                            # the open PR for this branch
/pr-uat 450 <extra cases>          # that PR, plus any extra cases
/pr-uat <any test described>       # ad hoc: local only, nothing published
```

`/pr-uat` needs local Postgres and Redis. The stack uses its own database and test keys, and fake Pipedrive,
TC2 and Google Calendar services, so nothing real is reachable. Screenshots go to the public `pr-screenshots`
branch, so a run uses synthetic data only.

## The three Hermes gates

1. **Security findings are never posted.** The security-auditor report and any security-flavoured
   finding from the other reviewers stay in `.claude/security/` and are reported in the chat only,
   under `## Local only: security (never posted)`. The posted findings and summary are built without
   them, must not mention security at all, and pass a keyword self-check before the dry run. This holds
   even when asked to post "everything".
2. **Posting needs approval.** After the dry run the command shows the exact text of every inline
   finding and the summary, then asks `AskUserQuestion` ("Post this review to PR #N" / "Don't post").
   It posts only on an explicit "Post", always as a `COMMENT` review (GitHub rejects `REQUEST_CHANGES`
   and `APPROVE` on your own PR). It never `APPROVE`s.
3. **Stamping needs no approval.** When the branch has an open PR at the same HEAD, the reviewed commit
   is stamped with the verdict (`APPROVED` / `CHANGES_REQUESTED` / `BLOCKED`) without asking. The
   verdict counts the security findings; the stamp never states a reason.

## Tools

Both scripts are stdlib-only and need `gh` authenticated for `tutorcruncher/hermes`:

```bash
python3 .claude/tools/post_pr_review.py 450 --findings f.json --summary s.md --dry-run   # classify, post nothing
python3 .claude/tools/post_pr_review.py 450 --findings f.json --summary s.md --event COMMENT
python3 .claude/tools/pr_review_stamp.py check 450            # exit 0 reviewed+APPROVED / 1 stale / 2 no stamp
python3 .claude/tools/pr_review_stamp.py stamp 450 <sha> --verdict CHANGES_REQUESTED
```
