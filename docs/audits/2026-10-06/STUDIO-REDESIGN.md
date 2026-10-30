# Script Studio: usability correction and live workbench

Date: 2026-10-06 (Asia/Yekaterinburg). Baseline UI: 952b5e2f;
API: c2b91e32. User evidence: annotated `/scripts` at 724×884 and
`/scripts/builder` with collapsed navigation. This document records a new
correction; it does not alter the earlier immutable Stage A receipts.

## Proven defects in the initial UI baseline

- Catalog actions are `shrink-0` in the same horizontal row as the title;
  their combined width exceeds the content area at the `sm` breakpoint.
  The title can collapse and actions spill outside the card.
- Start/end circles and small, unlabeled handles obscure the execution model.
  Parameters are a JSON textarea, although common actions have editable fields.
- The ungrouped 32-action palette has no task-oriented discovery.
- Breadth-first positioning does not optimize crossings or branch spacing.
- Device selection, live input capture, selector insertion and task observation
  are absent from Studio. Existing single-device H.264 and hierarchy tools are
  available elsewhere and should be reused, with ownership checks intact.

## Library decision and authorship

Use [React Flow / xyflow](https://reactflow.dev/learn/customization/custom-nodes)
under MIT, retaining its attribution. The existing React/TypeScript graph
contract and free customization API fit this application. This is a choice for
Sphere, not a claim that one editor is universally best. Do not copy paid Pro
templates. Custom Sphere nodes and forms are original implementation.

Use [elkjs / Eclipse Layout Kernel](https://github.com/kieler/elkjs) 0.12.0
under **EPL-2.0**, the offered alternative license. Authors and complete license
remain in the package; see `frontend/node_modules/elkjs/LICENSE.md` in an
installed checkout. [ELK integration](https://reactflow.dev/examples/layout/elkjs-multiple-handles)
is documented by React Flow. Run its local worker with a deadline and terminate
it on completion/unmount; do not download a runtime from a CDN.

[Rete](https://retejs.org/docs/licensing/) is an alternative: the core is MIT,
but some advanced plugins use noncommercial licenses. Replacing the canonical
DAG and editor state with a second framework is not justified for these defects.

## Delivery and verification contract

1. Responsive catalog with visible names, real version/step/date metadata,
   separated actions, density controls and identity-scoped preferences.
2. Rectangular nodes, explicit success/failure/condition outputs, readable
   routes, grouped searchable action library and structured parameter forms.
3. One explicitly selected Android stream in a workbench. Selector insertion
   uses a current, owned hierarchy. Capture records only input actually sent;
   transport submission must not be labeled acknowledged execution.
4. Execution uses a saved version and an explicit single device. Progress and
   logs come from actual task endpoints. Do not animate fictional completion.
5. Preserve source/graph round trips, permissions, cancellation, stale response
   rejection, version conflicts, bounded history/drafts and explicit errors.
6. Check tests/types/build, deploy only the reviewed UI on 3015 and verify
   desktop, tablet and narrow layouts through the native browser. Record image
   revision, actual screenshots, tested behavior and remaining limitations.

Video frames, hierarchy snapshots and task progress currently have independent
clocks. Frame-exact replay requires a new agent/server correlation protocol.
Zero WAN latency and frame-exact verification are not claimed by this UI change.
The original backlog acceptance ledger remains 9 accepted / 41 open until
the corresponding complete criteria have evidence.

## Installed result: 6 October, 07:00 UTC+5

UI **a670a3df3c90ad10658b71ad1b639689d407cf97** is installed on
[3015/scripts](http://127.0.0.1:3015/scripts). Image:
`sha256:e803fc55dc05c1271762d3dca911d1f354e2a42665e8cb0cd917fff20e631c69`.
API remains **c2b91e3202948860e4d99b3f35cbe441d2842538**. This is a frontend
delivery; APK and tunnels were not replaced. The immutable backend tree matches
the deployed API source. A revision-mismatch badge describes different source
revisions, not an observed compatibility failure.

The initial defects above were addressed in separate commits:

- Catalog names and actions use separate, wrapping regions. Real version,
  step, creation/update and hash metadata are available; list/card view, density,
  page size and metadata visibility persist per organization/user in this browser.
- The existing free React Flow canvas has original 256×133 px Sphere nodes,
  action icons, readable summaries and explicit route handles. ELK layout runs
  locally with a ten-second deadline, cancellation and worker termination.
  DOWN and RIGHT layouts change presentation rather than executable routes.
- Common action values, nested maps, checks, retry and timeout have structured
  forms. Complex/unknown action data remains available in JSON. Invalid source
  does not silently fall back to an earlier publishable graph.
- The device laboratory selects one real Android, reuses the single-device
  H.264 stream, records submitted click/swipe/wheel input in memory, inserts a
  fresh owned XPath explicitly and observes a task pinned to the saved version.
  Creation, active execution and uncertain outcomes have distinct input locks.
- Version history, source inspection, launch dialogs and execution details retain
  actual API data, permissions, version preconditions and explicit errors.
  Narrow dialogs wrap titles/actions; final task details use common theme tokens,
  Russian labels and fixed final duration instead of stale active telemetry.

Second review found and corrected three additional concrete defects:

1. Opening the device panel could preserve a previous small viewport and put
   Start behind the toolbar. An accepted panel change now fits once after canvas
   measurement with explicit toolbar clearance. Telemetry does not reset manual
   pan or dragged coordinates. Native final measurement: each of the three
   canary nodes is 256×133 px; document width equals viewport width, 1440 px.
2. Undo/redo could silently discard unapplied node fields. Both controls and the
   handler now wait for applying or explicitly cancelling those fields.
3. Closing the laboratory while POST `/tasks` was pending could discard the
   eventual ID and permit a later launch. The owned close/switch guard now keeps
   that request in its original laboratory until its receipt is reconciled.
   This is not durable exactly-once protection across reloads or other pages.

### Validation and native evidence

Final local frontend run: **1451 passed / 125 suites / 0 failed / 0 pending**, Jest
in-band without cache. TypeScript and the actual immutable Next production image
build passed. Existing unrelated lint warnings in the build are not described
as a clean repository-wide lint result. Source CI is recorded separately from
these local gates and runtime receipts.

Only the review UI container was recreated. **45 neighboring containers** kept
IDs, images, start times, mounts and log rotation; the UI retained read-only
rootfs, dropped capabilities and stable network addresses. Authenticated finite
fleet reads at 02:00:12 and 02:00:20 UTC reported **19 devices, 14 online,
5 offline**, with presence available. These two samples do not establish an
uptime SLA, zero downtime or the target load of 20–30/500/1000 devices.

Two intentional native-browser canaries used one remote **auto-ph-025**, the
same v1 (`0242986d-cabf-4907-9e90-ba4b06eb4a66`) and the same DAG hash:
`96edea950a8a53f48698faf6dad90c3c35e23857d7626c0f54993eb87d81ca8e`.
Both executed **start → sleep 4000 ms → end**, completed with three successful
reports and a 4002 ms sleep report. Receipts retain their original UI revisions
`6a427df` and `4ab8cc1`; final `a670a3d` adds viewport, history/launch guards and
task presentation. No third canary was created for these UI corrections. Reading
the completed task in the final UI confirmed three reports and a fixed four-second
duration. This proves this particular saved version, not all 32 runtime actions.

Native tests also exercised one captured transport gesture, insertion followed
by Undo, a real hierarchy of 49 nodes, a fresh XPath insertion followed by Undo,
lease expiry, catalog preference persistence across F5, both themes, 724/390 px
layouts and narrow version/run dialogs. Capture/insertion edits were not published
or executed. Some screenshots precede the final corrections; the manifest labels
each original source revision instead of attributing every image to the latest UI.

| Native image | What it establishes |
| --- | --- |
| [Original catalog/editor](assets/studio-redesign/before.jpg) | Historical baseline before the correction |
| [Catalog](assets/studio-redesign/catalog-dark-final.jpg) | Separated actions and real version metadata |
| [Narrow version dialog](assets/studio-redesign/version-mobile-final.jpg) | Wrapped dialog title/actions at 390 px |
| [Structured editor](assets/studio-redesign/editor-dark-final.jpg) | Library, route handles and parameters |
| [Live XPath insertion](assets/studio-redesign/xpath-insertion-final.jpg) | Real selector inserted into the graph source |
| [Final device laboratory](assets/studio-redesign/workbench-delivery.jpg) | Readable graph beside one real Android frame |
| [Final task detail](assets/studio-redesign/task-detail-final.jpg) | Rebuilt execution context and final values |
| [Final narrow task detail](assets/studio-redesign/task-detail-mobile.jpg) | 390 px layout without document overflow |

The presence of one screenshot does not prove video cadence or latency. A static
Android frame may legitimately remain unchanged. Frame, tree and task clocks
remain independent; frame-exact replay requires an agent/server trace contract.

Pinned hashes, image/build/install/test receipts and canaries:
[STUDIO-REDESIGN-EVIDENCE.json](STUDIO-REDESIGN-EVIDENCE.json).
Run `python -m scripts.audit.validate_studio_redesign` for artifact integrity only;
it makes no network request and does not repeat Android commands.
The earlier Stage A manifest and validator remain immutable historical evidence.
The operator guide is [SCRIPT-STUDIO.md](../../operations/SCRIPT-STUDIO.md).

### Open acceptance boundaries

The ledger remains **9 accepted / 41 open**; EP-014…020 are not marked accepted
because this UI delivery implements only part of their requirements. Missing
work includes versioned action/capability schemas and preflight, full selector/
text/navigation recording, durable reconciliation/idempotency, sidebar route
blocking, version-conflict diff, agent-correlated trace and frame-exact replay.
Unknown `action` parameters survive unrelated graph edits, but extra top-level
DAG/node properties are not promised to survive graph import/export. Review
the exported JSON when importing an extended format. The metadata-only catalog
P1 below and common resource/release/load gates remain open.

Repository validation also found two corrupt loose Git tree objects (`docs` and
`docs/operations`). Their exact tree bytes were reconstructed from GitHub's
existing tree API, original corrupt files were quarantined locally and canonical
Git SHA-1 was checked before replacing each object. No history rewrite or worktree
reset occurred. Final `git fsck --full --no-dangling` passed. The receipts are
included in the manifest; the cause of object corruption is unknown and is not
presented as the cause of host disk/RAM growth.

## Source review: catalog payload retention remains open (P1)

Reviewed on 2026-10-06. The finding originated in source review; the separate
finite response observation below subsequently confirmed it for the present
small catalog. Neither observation is a browser heap profile or diagnosis of
the earlier PC/Docker storage growth. The UI-only delivery does **not** close P1.

The current catalog GET `/scripts` does not offer an `include_dag` parameter.
Its serializer calls `_to_script_response` for every returned row;
`_to_script_response` calls `_to_version_response` without an override, whose
`include_dag=True` default places the complete current DAG in the response.
See [list and serializer](../../../backend/api/v1/scripts/router.py#L36).
The list permits up to 200 rows per request (default 50). The separate detail
and version-history endpoints have `include_dag` controls; those controls do
not apply to this list route.

The database path is also not metadata-only:
[ScriptService.list_scripts](../../../backend/services/script_service.py#L211)
uses `selectinload(Script.current_version)` without deferring the DAG column.
[ScriptVersion.dag](../../../backend/models/script.py#L25) is a normal JSONB
column. In addition, `_to_version_response` computes `dag_hash` from `v.dag`
even when its own `include_dag=False` is supplied. Merely omitting the response
field would therefore leave DAG loading and hashing work in the current path.

[useScripts](../../../frontend/lib/hooks/useScripts.ts#L46) caches the returned
response under its search/page parameters (`staleTime: 30 seconds`). Opening
the read-only source panel lazily avoids a further detail request while it is
closed; it does not remove current DAG bodies already delivered in the list.
The catalog's truthful step count currently falls back to `current_version.dag`:
see [step-count adapter](../../../frontend/src/features/scripts/scriptPresentation.ts#L3).
The legacy optional `Script.node_count` type is not a field of the current
[ScriptResponse schema](../../../backend/schemas/script.py#L63). Discarding DAGs
in the frontend alone would consequently lose authoritative step metadata.

The new catalog offers pages of 25, 50 or 100 rows. As a **conditional workload
illustration**, if each of 100 serialized DAG bodies were at the Studio source
limit of 512 KiB, their combined body contribution would be 50 MiB before
response metadata and parsed JavaScript object overhead. The
[512 KiB limit](../../../frontend/lib/dag/studio.ts#L4) constrains frontend
source text; it is not an established backend list-payload bound. This arithmetic
is neither an observed transfer size nor an upper bound for all existing/API
scripts. Serialization and transport compression can change actual wire size.
No memory-leak root cause is inferred from it.

Next priority: a separately scoped API change for a genuinely metadata-only,
organization-scoped catalog contract. Return the pinned current-version ID,
version, hash and authoritative node count, with explicit compatibility for
existing consumers. Derive counts/hashes deterministically from that version;
evaluate persisted version metadata or an appropriate deferred-column query
so that metadata reads do not deserialize and rehash every full DAG. Load source
only for explicit inspector, builder or version reads. Treat this as a backend
and frontend contract change, rather than silently changing existing responses.

Acceptance evidence for that stage must cover absent DAG bodies, truthful
version/count/hash metadata, tenant isolation, pagination/search/archive,
legacy compatibility and cancellation/session guards. Measure actual payload
bytes, query work and cache/heap behavior using large 100-row fixtures and a
deployed API before closing P1. The earlier 9 accepted / 41 open ledger is not
advanced by this source review.

### Finite response baseline and next implementation contract

At **02:13:52 UTC**, one authenticated read through UI **a670a3df** and API
**c2b91e32** returned 19 active rows and **19 full current DAGs**: 31,368 decoded
body bytes, 31,368 downloaded body bytes with identity encoding, 106 aggregate
nodes. Re-serializing only the DAG objects contributed 17,715 bytes; this is not
exact per-field wire accounting. The local HTTP round trip was 8.591 ms, including
the UI proxy and response. It is not WAN latency, SQL timing, a load result or
evidence of heap growth. No task or version was written by this read.
[Bounded sample](evidence/studio-redesign/catalog-payload-sample.json).

The [next catalog contract](SCRIPT-CATALOG-METADATA-CONTRACT.md) specifies a
separate compatible endpoint, version-owned persisted hash/count, explicit SQL
projection, resumable backfill, tenant/concurrency/query regressions and measured
rollout/rollback gates. Review found legacy Python/SQL writers that mutate an
existing DAG or bypass the service: these must be migrated or retired before
stored metadata is trusted. JSONB numeric round-trip/hash equivalence is a
separate unmeasured implementation risk requiring a PostgreSQL fixture. The
contract is a plan; the endpoint, columns, migration and backfill are not deployed.

### Completed source CI, separate from deployment acceptance

All four workflows for installed UI source **a670a3df** completed successfully:
[backend](https://github.com/RootOne1337/sphere-platform/actions/runs/37401985029),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/37401985124),
[preview](https://github.com/RootOne1337/sphere-platform/actions/runs/37401985130),
[Android](https://github.com/RootOne1337/sphere-platform/actions/runs/37401985298).
The backend test job reported **2844 passed / 30 skipped / 1 warning**. Android
tested variants and signed smoke APKs with a disposable CI-only key; this does
not publish a production APK or change the installed fleet. The final backend
job completed at **02:14:47 UTC**. Preview's guard passed and its deploy job was
**skipped** because the enable condition was not true; no hosted preview was
deployed by that workflow. Documentation-only commits have their own CI
head and do not replace this source receipt. Workflow success is scoped to those
jobs, not all actions, dependency advisories, fleet SLA or host storage attribution.
[Pinned source CI](evidence/studio-redesign/source-ci.json).
