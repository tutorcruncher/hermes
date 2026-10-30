# Pipedrive Impact Survey

Check whether a Hermes branch will send stale, wrong or duplicate data to Pipedrive once it meets real
production data. Much of the sync code exists to stop Hermes' stale copies from reaching Pipedrive. This
command finds every Pipedrive write the
branch adds or changes, measures how many real records each one would touch using the local prod backup,
and reports what the sales team would see.

## Usage

```
/pd-impact [PR_NUMBER]
```

No argument: the current branch's diff against `main`. `PR_NUMBER`: the checkout that holds that PR's
branch, resolved as `/full-review` does.

This command is **read-only**. It never edits source, never writes to the database, and never calls the
Pipedrive or TC2 APIs. It only reads the diff, the code, the local backup and Logfire.

## Data sources

- **Prod backup:** the local Postgres database `hermes-prod-backup`. Query it only with
  `psql hermes-prod-backup -X -P pager=off`, and only with `SELECT`. Before anything else, record how old it
  is (`SELECT max(created) FROM company;`). If the database is missing, say so, skip the counts and still
  do the code part.
- **Logfire:** project `hermes-prod`, through the Logfire MCP `query_run` tool (14-day window at most).
  Use it for how often each sync trigger fires (TC2 callbacks, call booker bookings, Pipedrive webhooks)
  and for real examples of a code path running.
- **Field types:** `$MAIN/PROD_CUSTOM_FIELDS.json` (org fields) when present, to know whether Pipedrive
  accepts any string in a field.

## Privacy gate (Hermes is a public repo)

The report is **local only**: `${WT}/.claude/pd-impact/{TS}-pr-review.md`. Counts, record ids, company or
person names, emails and internal volumes never go to GitHub. When `/full-review` posts a finding that came
from this survey, it posts the code risk in words only ("a call booker booking for a company with no TC2
client overwrites the deal's tc2_status with the model default"), with no numbers or names.

## Steps

### Step 1: Resolve the checkout and the diff

```bash
WT=$(git rev-parse --show-toplevel)
MAIN=$(git worktree list | head -1 | awk '{print $1}')
git -C "$WT" fetch origin main --quiet
git -C "$WT" diff origin/main...HEAD
```

`mkdir -p "${WT}/.claude/pd-impact"`. Timestamp `{TS}` is `date +%Y-%m-%d-%H%M`. If the diff touches no
code that can reach Pipedrive (`app/pipedrive/`, `app/tc2/`, `app/callbooker/`, `app/main_app/common.py`,
`patch.py`, field mappings, models), write a one-line report saying so and stop.

### Step 2: List every Pipedrive write the diff adds or changes

Read the changed files in full, not only the hunks. For each change, write down:

- **What is written:** which Pipedrive object (org, person, deal, activity), which fields, create / PATCH /
  delete, and where the value comes from (the Hermes deal row, the company row, the webhook payload).
- **Which records are selected:** the exact `select()` that decides which rows get synced. A widened
  filter (a new status, a dropped `pd_deal_id IS NOT NULL`, a dropped `is_deleted` check) is the most
  common way stale rows reach Pipedrive.
- **What triggers it:** follow the callers up to an entry point. Today they are the TC2 callback
  (`app/tc2/views.py`, the company's TC2 fields are fresh at that moment), the call booker
  (`app/callbooker/views.py`, the company can be stale or never have had TC2 data), the Pipedrive webhook
  (`app/pipedrive/views.py`) and `patch.py` commands. Re-check with `grep` rather than trusting this list.
- **Which guard it passes or skips.** Read the current code for each of these and say whether the diff
  keeps it:
  - Paying companies get a partial sync only: no deal creation, only open deals with a `pd_deal_id`, only
    `SYNCABLE_DEAL_FIELDS`.
  - The full deal sync skips an update when Pipedrive's deal is not open but Hermes thinks it is.
  - Pipeline and stage are never sent on update (#399), only on create.
  - Deal creation is behind `settings.sync_create_deals`.
  - `person_id` is not sent when Hermes does not know the person.
  - Only changed fields are PATCHed (`api.get_changed_fields`).
  - TC2-authoritative fields are never read back from Pipedrive (`OrganisationProcessor.custom_field_names`),
    and values Pipedrive joined while merging records are ignored.
  - Merged orgs link to the company that has a TC2 client (`_listed_id`).
  - Deleted companies are not synced, deleted deals and narc companies are not updated from Pipedrive.
  - A Pipedrive 404 marks the Hermes row deleted and never recreates it, except for a call booker booking.
  - Deals that never reached Pipedrive are marked deleted when a company is brought back
    (`_delete_unsynced_deals`).
  - Per-company sync lock.

### Step 3: Measure each write against the backup

For each write from Step 2, write a `SELECT` that counts the rows it would touch on its next trigger, and
how many of those would actually change in Pipedrive. Always split the counts by:

- company with a TC2 client (`tc2_cligency_id IS NOT NULL`) or Pipedrive-only (no TC2 client: its TC2
  fields hold model defaults such as `tc2_status = 'pending_email_conf'`, not real data);
- paying (`paid_invoice_count > 0`) or not;
- deal status (`open`, `won`, `lost`, `deleted`) and pipeline.

Starting queries (adapt them to the write being checked):

```sql
-- Rows whose value would change: Hermes' source value vs the value Pipedrive has now (the deal row mirrors
-- Pipedrive through the deal webhook, so it is the best local stand-in for Pipedrive's value)
SELECT CASE WHEN c.tc2_cligency_id IS NULL THEN 'no TC2 client' ELSE 'TC2' END kind,
       CASE WHEN coalesce(c.paid_invoice_count, 0) > 0 THEN 'paying' ELSE 'non-paying' END pay,
       count(*) total, count(*) FILTER (WHERE d.<field> IS DISTINCT FROM c.<field>) would_change
FROM deal d JOIN company c ON c.id = d.company_id
WHERE d.status = 'open' AND d.pd_deal_id IS NOT NULL AND NOT c.is_deleted AND NOT c.narc
GROUP BY 1, 2;

-- Model defaults and junk in the source column
SELECT <field>, count(*) FROM company WHERE tc2_cligency_id IS NULL AND pd_org_id IS NOT NULL
  AND NOT is_deleted GROUP BY 1 ORDER BY 2 DESC;
SELECT count(*) FROM company WHERE <field> LIKE '%,%';   -- values Pipedrive joined while merging

-- Duplicate risk
SELECT count(*) FROM (SELECT pd_deal_id FROM deal WHERE pd_deal_id IS NOT NULL GROUP BY 1 HAVING count(*) > 1) x;
SELECT count(*) FROM (SELECT pd_org_id FROM company WHERE pd_org_id IS NOT NULL GROUP BY 1 HAVING count(*) > 1) x;
SELECT count(*) FROM deal WHERE status = 'open' AND pd_deal_id IS NULL;   -- would be created on a full sync
SELECT count(*) FROM company a JOIN company b ON lower(a.name) = lower(b.name) AND a.id < b.id
  WHERE NOT a.is_deleted AND NOT b.is_deleted;

-- Hermes' status may be stale against Pipedrive: a company with both a won and an open deal
SELECT count(DISTINCT company_id) FROM deal o WHERE o.status = 'open' AND o.pd_deal_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM deal w WHERE w.company_id = o.company_id AND w.status = 'won');
```

Use Logfire to turn counts into a rate: how often each trigger fires per day, and whether Hermes has been
receiving the updates the change depends on (a field that TC2 never sends stays stale however often the
sync runs).

### Step 4: Judge each risk

Go through these, and add any other way the change can upset the sales team:

1. **Duplicate resources.** Can the change create an org, person or deal that already exists in Pipedrive
   (a widened create path, a lost `pd_*_id`, a deleted row brought back)?
2. **Stale data overwriting Pipedrive.** Is the value sent fresh at the moment of sending? A value from a
   Pipedrive-only company, a model default, a field TC2 stopped sending, or a joined merge value is stale.
   Would it overwrite something sales set by hand?
3. **Wrong closing or deletion.** Can the change mark a deal lost, won, or deleted in Pipedrive when
   Pipedrive's own state is different (Hermes says open, Pipedrive says won)? Can a 404 now mark rows
   deleted that should not be?
4. **Pipedrive automations.** A field change can fire an automation in Pipedrive (for example a
   `tc2_status` change moving a deal to another stage). Count the transitions the change will cause.
5. **Volume.** How many PATCHes or creates land on the first sync after deploy, and on each later one?
   Pipedrive's rate limit is shared with every other sync.
6. **Circular updates.** Can the write come back through the Pipedrive webhook and trigger another write?

Severity: **Blocker** when the change will write wrong or stale data to Pipedrive records that exist
today, or create duplicates. **High** when it can, but only on a rare trigger. **Medium** for a visible
side effect that is arguably correct (an automation firing). **Nit** otherwise.

### Step 5: Write the report

`${WT}/.claude/pd-impact/{TS}-pr-review.md`:

- Backup age and the diff reviewed (branch, HEAD sha).
- Each finding: severity, `path:line` (a changed line in the diff), what goes wrong in Pipedrive, the
  query and its counts, the trigger and its rate, and a suggested fix.
- "No risk found" for each of the six risks that does not apply, with the reason in one line.
- The queries you ran, so the numbers can be re-checked.

Then reply in the chat with the findings, most severe first, each as `path:line` plus one line.
