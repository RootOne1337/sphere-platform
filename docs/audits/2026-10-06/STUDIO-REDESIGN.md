# Script Studio: usability correction and live workbench

Date: 2026-10-06 (Asia/Yekaterinburg). Baseline UI: 952b5e2f;
API: c2b91e32. User evidence: annotated `/scripts` at 724×884 and
`/scripts/builder` with collapsed navigation. This document records a new
correction; it does not alter the earlier immutable Stage A receipts.

## Proven defects

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

Status: implementation in progress. No new live result is asserted yet.

## Source review: catalog payload retention remains open (P1)

Reviewed on 2026-10-06. This is a code-derived finding, not a measured live
response, browser heap profile or diagnosis of the earlier PC/Docker storage
growth. The UI-only delivery does **not** close this P1.

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
