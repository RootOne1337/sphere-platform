# AUD-120 · Task Engine hid history and invented runtime indicators

**High · operational observability · source 19 September; pilot acceptance 20 September 2026 (Asia/Yekaterinburg).**

## Reproduction and root cause

The pilot contains 190 tasks. `GET /api/v1/tasks?per_page=100` returns total 190
and 100 rows; the deployed web still displays Total Tasks 100 and 100.0% success.
Earlier evidence had the same discrepancy at 174 tasks. The page paginated,
searched, sorted and aggregated only the newest hundred. Older failures or active
work could not appear. This is not a storage loss.

The same page inferred `CRON` from positive priority, despite manual commands
using priority 5. Active Pipeline was constant text without a request; New Workflow
had no action. The “Next 60s” chart projected creation timestamps as future work.
[Original night analysis](NIGHT-RUN-ANALYSIS.md).

## Fix and contract

- `/tasks` accepts bounded `search` (200 characters), allowlisted `sort_by`
  (`created_at`, `script_name`, `status`, `priority`), `sort_dir`, `active_only`
  and opt-in `include_counts`. Existing status/device/script/batch filters remain.
- Search matches task ID, script and device names, case-insensitively. `%` and `_`
  are literal input. Name joins and task predicates are tenant scoped.
- Filters precede aggregation and paging. `status_counts` describes the complete
  filtered history, including when the requested page is empty. Existing clients
  skip the grouped calculation unless they request it. UUID breaks sort ties.
- UI requests pages of 25 from the server; changing filter/search/order resets the
  page. Polling clamps a page that disappeared. Search is debounced by 300 ms.
- Metrics use server totals and explicitly define success as
  `completed / (completed + failed + timeout)`; cancellation and unfinished work
  are excluded. Loading/error states display unavailable values, not zero.
- Active tasks and pipeline previews are independent server queries, limited to
  ten with an explicit shown/total label. Pipeline `active_only` includes queued,
  running, waiting and paused. The current task links to its existing detail page.
- Priority is displayed as priority; unsupported trigger/forecast claims are
  removed. “Новый сценарий” opens the existing `/scripts/builder` editor. This
  does not add an n8n or pipeline designer.

## Affected files and regression evidence

- Backend task router/schema/service and pipeline run router/service.
- Frontend Task Engine page, task and pipeline hooks.
- `tests/production/test_task_history_query.py`: PostgreSQL fixtures with 129 tasks,
  an older failure, older active work, a foreign tenant and literal wildcard decoy;
  all pages, stable ties, counts, search, invalid options and restricted RLS role.
- `frontend/__tests__/tasks/history.test.tsx`: 190 tasks/eighth page, old failure
  search/filter, real active work, editor navigation, loading/error and shrinking
  pages. Hook tests verify HTTP parameters.

Before: 10 PostgreSQL/API failures and 7 UI failures. After: 81 related backend
tests, all 218 frontend tests across 27 suites and TypeScript pass. The first wider
backend retry encountered stopped disposable services (19 setup errors); it is
preserved as an environment failure, not a passing run. After restarting only
those two audit services, all 81 passed. [Machine-readable evidence](evidence/task-history-regression.json).

## Deployment and residual risk

Backend and frontend `03b161e` are deployed only to `sphere-pilot-20260911`.
The previous installation and other containers retained IDs, images, start times,
status and mounts; the OTA catalog and artifact hash also matched. The initial
deployment rolled back because the harness compared unordered Docker mount lists
as ordered lists. Two consecutive read-only inspections reproduced this harness
error; sorting by mount destination retained the guard and the repeat passed.

The installed API returned 190 unique tasks as seven pages of 25 plus 15. All
seven status filters and counts matched those rows; search found the oldest task.
Browser navigation reached page 8, found that same ID, showed the empty failed
filter and opened the existing editor. A five-minute delay-only pipeline appeared
as RUNNING at step `hold`, then disappeared after cancellation. Its definition was
disabled; no recurring or Android action was added. The helper's first disable
request used PUT (405); correcting it to the documented PATCH completed cleanup.
Both existing APK 1.2.7 / 10207 agents returned the expected echo after deployment.

The 190 pilot tasks are all completed: the 100% value is correct for those rows.
Older-failure visibility and non-100% arithmetic are independently covered by the
isolated PostgreSQL/frontend fixtures. This does not turn the failed overnight
harness into a successful run. No uptime claim spans the gap between deployment
and acceptance. [Runtime evidence](evidence/task-history-runtime.json) and
[all successful source workflows](evidence/ci-03b161e-summary.json).

Pagination uses offset and does not freeze history across requests. Concurrent
inserts/deletes can shift pages; aggregate and row queries run under the existing
transaction isolation and can observe adjacent snapshots. These are live views,
not an immutable export. Counts/search cost grows with matching history; fleet-
scale query latency and indexing need measurement before capacity claims.

Polling every 10 s may miss the running state of a 2.6 s task. Open its persisted
result for evidence. Preview panels are explicitly limited; full pipeline
management, durable trigger provenance and large script-selector pagination are
separate work. A 403 pipeline response is shown as unavailable. The original
night remains failed; this fix does not certify a new eight-hour run or VPN.
