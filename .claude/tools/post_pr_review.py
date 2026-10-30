#!/usr/bin/env python3
"""Post review findings to a GitHub PR as a single **Review** (summary + inline comments).

`/full-review` (`.claude/commands/full-review.md`) produces findings (path/line/severity/body) + a synthesis
summary; this posts them as one GH review. GitHub rejects the whole review (422) if any inline comment is on a
line that isn't in the diff, so we only inline findings whose line is commentable (a `+`/context line on the
RIGHT side of the diff) and fold the rest into the summary. If the inline POST still fails, we fall back to a
body-only review so the review always lands.

  post_pr_review.py <PR> --findings findings.json --summary summary.md [--event COMMENT|REQUEST_CHANGES|APPROVE]
  post_pr_review.py <PR> --findings findings.json --summary summary.md --dry-run   # classify only, post nothing

findings.json: [{ "path": "...", "line": 123, "severity": "Blocker", "body": "..." }, ...]
Per the repo convention every Claude-authored GitHub comment leads with a bold CLAUDE SAYS line.

The default event is COMMENT: Hermes PRs are opened by the person running the review, and GitHub refuses
REQUEST_CHANGES and APPROVE on your own PR. The other events stay available for a PR someone else opened.

This repo is public, so the command that drives this script never passes it any security finding; this script
posts exactly what it is given and does no filtering of its own.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = 'tutorcruncher/hermes'
CLAUDE_SAYS = '**CLAUDE SAYS:**'
HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')


def gh(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(['gh', *args], capture_output=True, text=True, input=stdin, check=False)


def commentable_lines(pr: str) -> set[tuple[str, int]]:
    """(path, new-file-line) pairs that GitHub will accept an inline comment on (RIGHT side)."""
    diff = gh(['pr', 'diff', str(pr), '--repo', REPO]).stdout
    lines, path, new_no = set(), None, 0
    for raw in diff.splitlines():
        if raw.startswith('+++ b/'):
            path = raw[6:]
        elif m := HUNK.match(raw):
            new_no = int(m.group(1))
        elif path and raw.startswith('+') and not raw.startswith('+++') or path and raw.startswith(' '):
            lines.add((path, new_no))
            new_no += 1
        # a '-' (deletion) line consumes no new-file line number
    return lines


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('pr')
    p.add_argument('--findings', required=True)
    p.add_argument('--summary', required=True)
    p.add_argument(
        '--event',
        default='COMMENT',
        choices=['COMMENT', 'REQUEST_CHANGES', 'APPROVE'],
        help='COMMENT (default) is the only event GitHub accepts on your own PR.',
    )
    p.add_argument(
        '--dry-run',
        action='store_true',
        help='Print which findings would land inline and which would fall into the summary, then exit '
        'without posting. Use it to re-anchor findings onto changed lines before posting for real.',
    )
    args = p.parse_args()

    head = gh(
        ['pr', 'view', str(args.pr), '--repo', REPO, '--json', 'headRefOid', '--jq', '.headRefOid']
    ).stdout.strip()
    findings = json.loads(Path(args.findings).read_text())
    summary = Path(args.summary).read_text().strip()
    ok = commentable_lines(args.pr)

    inline, body_only = [], []
    for f in findings:
        path, line = f.get('path'), f.get('line')
        if path and isinstance(line, int) and (path, line) in ok:
            inline.append(
                {
                    'path': path,
                    'line': line,
                    'side': 'RIGHT',
                    'body': f'**[{f.get("severity", "Note")}]** {f["body"]}',
                }
            )
        else:
            loc = f'`{path}:{line}`' if path else ''
            body_only.append(f'- **[{f.get("severity", "Note")}]** {loc} — {f["body"]}')

    if args.dry_run:
        for c in inline:
            print(f'inline   {c["path"]}:{c["line"]}')
        for f in findings:
            if f.get('path') and (f.get('path'), f.get('line')) not in ok:
                print(f'SUMMARY  {f.get("path")}:{f.get("line")} — not a commentable line in the diff; re-anchor it')
            elif not f.get('path'):
                print(f'summary  (no path) {f["body"].splitlines()[-1][:60]}')
        print(f'dry run: {len(inline)} inline, {len(body_only)} in summary. Nothing posted.')
        return

    body = f'{CLAUDE_SAYS}\n\n{summary}'
    if body_only:
        body += '\n\n### Findings not on changed lines\n' + '\n'.join(body_only)

    def post(comments: list) -> subprocess.CompletedProcess:
        payload = {'commit_id': head, 'event': args.event, 'body': body}
        if comments:
            payload['comments'] = comments
        return gh(
            ['api', f'repos/{REPO}/pulls/{args.pr}/reviews', '--method', 'POST', '--input', '-'],
            stdin=json.dumps(payload),
        )

    r = post(inline)
    if r.returncode != 0 and inline:
        # An inline comment was rejected — fold everything into the body and post a body-only review.
        extra = '\n'.join(f'- {c["body"]} (`{c["path"]}:{c["line"]}`)' for c in inline)
        body += '\n\n### Inline findings (could not attach to the diff)\n' + extra
        r = post([])
    if r.returncode != 0:
        print(f'post_pr_review: FAILED to post review:\n{r.stderr}', file=sys.stderr)
        sys.exit(1)

    url = json.loads(r.stdout).get('html_url', '') if r.stdout.strip().startswith('{') else ''
    print(f'posted {args.event} review to PR #{args.pr}: {len(inline)} inline, {len(body_only)} in summary. {url}')


if __name__ == '__main__':
    main()
