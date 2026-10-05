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
