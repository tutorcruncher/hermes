Check whether a Hermes PR's HEAD has been fully reviewed — i.e. whether it's cleared to hand to a human
reviewer / merge. A PR is "reviewed" when `/full-review` has stamped its current HEAD with an `APPROVED`
verdict in the description.

Usage: `/review-status [<PR-number>]` (defaults to the current branch's PR).

Resolve the checkout once: `WT=$(git rev-parse --show-toplevel)`.

## Steps

1. **Resolve the PR**: `gh pr view [<PR>] --json number,headRefOid,url`. If no PR exists for the branch,
   say so and stop.

2. **Run the check** (from the checkout that holds the branch, so the script can diff locally):

   ```bash
   git fetch origin --quiet
   python3 "$WT/.claude/tools/pr_review_stamp.py" check <PR>
   ```

   Exit code: **0** = HEAD is reviewed + `APPROVED` (ready to hand off); **1** = stamp is stale (HEAD
   moved past the reviewed commit, or the last verdict wasn't APPROVED); **2** = no stamp at all.

3. **Interpret and act**:
   - **Exit 0** → report "Fully reviewed up to HEAD — cleared to hand off."
   - **Exit 2 (no stamp)** → "Not reviewed yet. Run `/full-review` before handing this out." Offer to
     run it.
   - **Exit 1 (stale)** → the script prints the unreviewed commits since the stamp + a diff stat. Judge
     the delta:
     - **Trivial** (wording/comments/formatting only, no logic change) → it doesn't need a full
       re-review. Re-stamp HEAD as still-reviewed, carrying the prior verdict (stamping needs no
       approval):
       ```bash
       python3 "$WT/.claude/tools/pr_review_stamp.py" \
         stamp <PR> "$(gh pr view <PR> --json headRefOid --jq .headRefOid)" --verdict APPROVED
       ```
       Say what you judged trivial and that you re-stamped.
     - **Non-trivial** (any logic / query / model / migration / test change) → recommend (and offer to
       run) `/full-review` on the branch, which will re-stamp on completion.
     - **Last verdict not APPROVED** (HEAD matches but verdict was CHANGES_REQUESTED/BLOCKED) → the
       blocking findings still stand; run `/full-review` (or fix them) before handing off. The stamp
       never says why; the reasons are in the last review's chat summary and in
       `<checkout>/.claude/reviews/` (and `.claude/security/`, which is local only and never posted).

4. **Check the migrations still line up with `main`** — even when step 2 passed. A branch that was
   green on its own collides with a migration `main` gained since, and Alembic then has two heads.
   From the PR's checkout:

   ```bash
   git -C <checkout> fetch origin main --quiet
   git -C <checkout> diff --name-only origin/main...HEAD -- migrations/versions
   git -C <checkout> diff --name-only HEAD...origin/main -- migrations/versions
   ```

   Both lists non-empty → both sides added a migration. The branch's migration must `down_revision`
   from `main`'s newest revision; if it doesn't, it is not cleared to hand off: rebase or re-point the
   `down_revision` first, then confirm with `uv run --directory <checkout> alembic heads` after merging
   `main` in (exactly one head).

5. **Report**: the verdict (ready / re-stamped-as-trivial / needs re-review / migration collision), the
   reviewed vs HEAD short SHAs, and a one-line reason. Include the PR link.

## Notes

- This is the low-tech "reviewed before handoff" gate: the stamp lives in the PR description
  (`<!-- reviewed-up-to: … -->` banner), written by `/full-review` Step 6. There's no hard CI gate —
  it's a visible signal a human (or this command) checks before handing the PR off.
- Re-stamping for a trivial delta is a judgement call: when in doubt, re-review. Logic, model,
  migration, Pydantic schema, sync task, or test changes are **never** trivial.
- Don't rely on `cd` (the cwd reverts between calls, and `cd X && …` trips permission prompts): use
  `git -C`, `uv run --directory` and absolute paths.
