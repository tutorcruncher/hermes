#!/usr/bin/env python3
"""Record / check the last *fully reviewed* commit on a PR, in the PR description.

A PR should be reviewed (via `/full-review`, `.claude/commands/full-review.md`) before it's handed to a human
reviewer — but a trivial follow-up commit (a wording tweak) shouldn't force a full re-review. So `/full-review`
stamps the commit it reviewed into the PR body; `check` (used by `/review-status`) then tells you whether HEAD
is still covered.

  pr_review_stamp.py stamp <pr> <sha> --verdict APPROVED   # upsert the marker (idempotent)
  pr_review_stamp.py check <pr>                            # is HEAD reviewed? exit 0 yes / 1 stale / 2 none

The marker is a single block at the TOP of the PR body, preserving the rest:

  <!-- reviewed-up-to: <full-sha> | verdict: <V> | <date> -->
  > 🔍 Reviewed up to `<short>` — **<V>**, <date> (`/full-review`). Re-run after non-trivial changes.

The stamp carries the verdict only, never a reason: this repo is public and the verdict may rest on findings
that stay local.

Requires `gh` authenticated for tutorcruncher/hermes.
"""

import argparse
import re
import subprocess
import sys
from datetime import date

REPO = 'tutorcruncher/hermes'
VERDICTS = ['APPROVED', 'CHANGES_REQUESTED', 'BLOCKED']
# The comment line + the visible quote line that follows it (+ a trailing blank line).
# NOT re.DOTALL — each part is line-bounded; DOTALL would let `>.*` eat the rest of the body.
MARKER_RE = re.compile(r'<!-- reviewed-up-to:.*?-->\n(?:>.*\n)?\n?')
PARSE_RE = re.compile(r'reviewed-up-to:\s*(\S+)\s*\|\s*verdict:\s*(\S+)')


def gh(args: list[str]) -> str:
    return subprocess.run(['gh', *args], capture_output=True, text=True, check=False).stdout.strip()


def pr_body(pr: str) -> str:
    return gh(['pr', 'view', pr, '--repo', REPO, '--json', 'body', '--jq', '.body']) or ''


def pr_head(pr: str) -> str:
    return gh(['pr', 'view', pr, '--repo', REPO, '--json', 'headRefOid', '--jq', '.headRefOid'])


def stamp(pr: str, sha: str, verdict: str) -> int:
    today = date.today().isoformat()
    block = (
        f'<!-- reviewed-up-to: {sha} | verdict: {verdict} | {today} -->\n'
        f'> 🔍 Reviewed up to `{sha[:9]}` — **{verdict}**, {today} (`/full-review`). '
        f'Re-run after non-trivial changes.\n\n'
    )
    body = MARKER_RE.sub('', pr_body(pr)).lstrip('\n')
    gh(['pr', 'edit', pr, '--repo', REPO, '--body', block + body])
    print(f'stamped PR #{pr}: reviewed-up-to {sha[:9]} ({verdict})')
    return 0


def check(pr: str) -> int:
    body, head = pr_body(pr), pr_head(pr)
    m = PARSE_RE.search(body)
    if not m:
        print(f'PR #{pr}: NO review stamp — run /full-review before assigning it out.')
        return 2
    reviewed, verdict = m.group(1), m.group(2)
    if reviewed == head:
        ok = verdict.upper() == 'APPROVED'
        mark = '✅' if ok else '⚠️'
        print(f'{mark} PR #{pr}: HEAD ({head[:9]}) is fully reviewed — verdict {verdict}.')
        return 0 if ok else 1
    # HEAD moved past the reviewed commit — show what's unreviewed so you can judge triviality.
    print(f'⚠️ PR #{pr}: reviewed up to {reviewed[:9]} ({verdict}) but HEAD is {head[:9]}.')
    log = git_local(['log', '--oneline', f'{reviewed}..{head}'])
    stat = git_local(['diff', '--stat', f'{reviewed}..{head}'])
    if log:
        print('\nUnreviewed commits since the stamp:\n' + log)
        print('\nDiff stat:\n' + stat)
        print('\nIf those are trivial (wording/comments), re-stamp; otherwise re-run /full-review.')
    else:
        print('(could not diff locally — fetch the branch, or re-run /full-review)')
    return 1


def git_local(git_args: list[str]) -> str:
    return subprocess.run(['git', *git_args], capture_output=True, text=True, check=False).stdout.strip()


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('stamp')
    s.add_argument('pr')
    s.add_argument('sha')
    s.add_argument('--verdict', default='APPROVED', choices=VERDICTS)
    c = sub.add_parser('check')
    c.add_argument('pr')
    args = p.parse_args()
    if args.cmd == 'stamp':
        sys.exit(stamp(args.pr, args.sha, args.verdict))
    sys.exit(check(args.pr))


if __name__ == '__main__':
    main()
