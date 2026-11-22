# Navigation from the selected measured geometry

## Reported failure

`skuter1` displayed the preferred historical reconstruction (173 cameras,
20,556 native points), while navigation preparation still used the original
primary reconstruction (144 cameras, 9,529 points). That primary job had a
historical resource refusal. The refusal was not a current RAM measurement.
The displayed alternative had no navigation artifact of its own, so showing
its points did not make the transport launchable.

The correction preserves the historical geometry byte for byte. A fixed,
source-bound native bundle connects that alternative to its measured camera
poses, point IDs and image observations. Preparation can export this selected
source without running SfM again or replacing it with another reconstruction.

## Implementation boundaries

- `route_preparation_source.py` verifies the alternative ID, geometry, capture,
  reconstruction index, native binaries and producer evidence. API callers
  supply an ID, never a filesystem path.
- `prepare_route_workspace.py` exports the selected bundle as a separate
  measured Reference-LK family. Legacy sparse maps keep their original family.
- The new runtime uses bounded reference images and real native XY/XYZ
  correspondences. It retains the existing PnP, image support, motion and
  freshness checks; it has no dummy descriptors or unconditional poses.
- The full 20,556-point geometry remains available for review. The runtime
  selects at most 512 measured observations per reference image to bound work;
  its landmark count is therefore not the count of the displayed point cloud.
- A source-bound qualification receipt permits a controlled experimental test,
  not an assertion of autonomous completion or metric accuracy.
- The web prepares the selected source and freezes that choice while the job
  runs. A ready result for another geometry cannot unlock the selected map.

An old parent cancellation marker is preserved. A new explicit alternative
attempt records its identity; a later cancellation still stops that attempt.
Existing recordings, failed attempts, primary models and preferred display
selection are retained.

## Verification record

Private evidence is kept under `.local-pilot/route-reference-lk-qualification-20261103-*`.
Each measurement freezes producer and source hashes, owns its child process,
enforces memory/time limits and sends no Android input. Positive queries are
159 real decoded frames disjoint from the 173 reconstruction references.
The JPEG pass uses actual OpenCV JPEG86 encoding and decoding at 960×540 with
a paced receiver clock. It is a transport surrogate, not a browser-encoder or
Android delivery benchmark.

The first run completed in 87.766 seconds with a peak private allocation of
452,911,104 bytes. RAW queries yielded 128 localized, 15 confirming and 16
unknown states. JPEG yielded 105 localized, 26 confirming and 28 unknown;
processing p95 was 195.254 ms, with seven responses exceeding the 250 ms age
budget and none of those accepted as localized. The longest interval between
localized source samples was 4.109 seconds. These results do not establish
continuous control at road speed.

Independent review caught an invalid negative-test inference: all 89 unrelated
images returned unknown, but 80 had been rejected before matching because their
source sampling gaps exceeded the observation window. That run is preserved
as incomplete negative evidence and cannot authorize the new family. The
corrected check must actually attempt matching for every unrelated image.

Browser verification uses the actual saved 173-camera/20,556-point geometry and
H.264 recording in an isolated fixture. Its preparation API is mocked; it does
not prove an authenticated installed workflow or successful game movement.

## Operational interpretation

The intended user flow is: select the saved recording, retain the preferred
geometry, prepare that geometry, then start a controlled live test from a
recognized location. No new recording is necessary to repair this source-link
failure. Unknown localization remains neutral; geometry or point count alone
does not authorize movement. Actual deployment identities and final preparation
results belong in the delivery evidence, not in historical failed-job records.

## Delivered result

The corrected second run actually attempted Reference-LK independently for all
89 unrelated images: 89 unknown, zero confirming/localized states, zero verified
PnP candidates. RAW remained 128/15/16. Paced JPEG yielded 97 localized,
31 confirming and 31 unknown; p50/p95 were 64.082/267.399 ms. Nine responses
expired and none were accepted as localized. This run overlapped frontend CI;
its contention and failures are retained. Peak private allocation was
542,765,056 bytes. The observed nonlocalized sample run remained 3.692 seconds,
with the next localized query 3.892 seconds after the first lost query.

The reviewed, controlled-test artifact was imported unchanged into new
navigation attempts for both saved jobs:

| Saved job | New navigation attempt | Source |
| --- | --- | --- |
| `6a77040681d142ec97d51831a22785fb` | `024fd153939b071ca65f825b86c16e28` | Historical 173-camera / 20,556-point geometry |
| `f3033bb704d4460fb8ed27a613427cc1` | `cd37b1d2606ff063963bb0454d39abd2` | Exact same verified source binding |

Actual `RouteWorkspaces.status()` returns ready for both. Actual
`start_vehicle()` constructed `ReferenceLKLocalizer` and `VehicleRouteFollower`
with the saved speed reference, then closed them without submitting a frame or
Android input. Both caches were released. This checks the real planner startup
on disk, not authenticated user-browser execution or route completion.

Live starts now carry the expected alternative ID, geometry SHA and runtime
family. The server rejects a changed source before loading/renewing a session;
the active pointer is also fenced throughout the session. Legacy requests stay
compatible. Startup exceptions release the route and tracker caches.

Installed web source: `89b6965721ed14688ac008119bddb805374ac9d5`.
Installed local route API source: `ce9cd58a2f273af8dd309e155df657330852050a`.
The served pages, 31 client assets and recorder/encoder workers were checked;
65 other containers and 843 protected artifacts were preserved. Frontend CI:
239 suites / 3,252 tests passed. Combined backend verification: 187 tests and
91 subtests passed. The browser fixture passed 13 workflow checks; start-source
refusal tests additionally cover observer, walking and vehicle launches.

Evidence and SHA manifest: [selected-geometry-evidence/manifest.json](selected-geometry-evidence/manifest.json).
The user can refresh the web page, select `skuter1`, retain the historical
173-camera geometry and enter the controlled transport test with the existing
15 km/h limit. A new video or SfM run is unnecessary for this repaired map.
Uninterrupted driving at the recorded speed remains unproven. New maps and new
runtime fingerprints require their own qualification; this delivery does not
claim automatic qualification of arbitrary future recordings.

## Primary implementation references

The new family uses the sparse LK mechanism documented by
[OpenCV](https://github.com/opencv/opencv/blob/5.x/doc/tutorials/others/optical_flow.markdown).
Separating a map from lightweight visual tracking is also used in
[RPG SVO Pro](https://github.com/uzh-rpg/rpg_svo_pro_open/blob/master/doc/global_map.md).
SVO itself was not installed or benchmarked here; those references are design
context, not evidence that this game controller is qualified.
