# skuter2: actual resource refusal, camera motion and mask repair

## Recorded source and initial refusal

The recording is capture `141ad30000b048fca1c4ad992f27a7dd`, job
`b8fba4a19a1a4c2c9aa7448244564584`, manifest SHA-256
`0286968eeee607b6319b51921f5ce46f778a7fcf65940c586b9046ec5ab68360`.
Its completed H.264 contains 1,032 indexed frames at 1920×1080 over 39.916 s.
Measured reception is 25.83 FPS and 8.94 Mbit/s, with a maximum media gap of
91 ms. This does not establish 30/60 FPS or source render quality. No transcoding
or synthetic frames were introduced.

The initial worker stopped at `reconstruct_route.py`'s checkpoint after masks
and frame selection, before importing pycolmap or building native geometry.
The only finding was `volume_health_unavailable`: the last task-owned volume
proof was 34,375 ms old, beyond its 30,000 ms maximum, with a new probe running.
The same snapshot had 14.45 GiB free physical RAM, approximately 44.2 GiB free
disk and 72.3% Windows commit use. This was not a measured RAM shortage.

An optional image-route diagnostic had taken 111.125 s before SfM. The original
monitor scheduled refreshes only when its caller sampled; it could not maintain
the proof across a long interval without such calls. Prepared data contained
209 selected views, including both source endpoints. The message calling this
a "previous" resource failure was also incorrect for the first new attempt.

## Installed fix and tests

Commit `7e5b64d0a35213b5b498395a55ae20cd89d81427` adds a task-owned scheduler
which refreshes volume health independently of caller sampling. At most one
probe is active. The probe timeout remains 10 s and proof lifetime remains
30 s; RAM, commit and disk samples remain fresh. Warning, missing proof,
expired proof, changed volume identity and cancellation still refuse work.
Context exit closes the scheduler and its owned probe.

The real Windows regression deliberately made no `sample()` calls for 36 s.
The following sample was Healthy with proof age 6,734 ms; all owned threads
closed. This reproduces the actual missing-sample boundary, rather than simply
increasing the TTL. Deterministic tests also cover 111 s without samples,
changed identity, failed refreshes, clock regression and exception cleanup.

Root validation passed 133 backend tests. The UI slice passed 96 tests;
canonical frontend CI passed 3,258 tests in 240 suites and TypeScript. The web
was installed from this commit, image
`sha256:be015eb5860999be6ee4fb518259485b959ccdcc5e05d6d70487ce85e8c3a4bb`.
The local API serves
`route_resource_monitor_contract=task_volume30_background_refresh_v2`.
API reload preserved 1,029 protected assets and all 66 containers; web installation
preserved 1,035 protected assets and the other 65 containers. HTTP pages/assets
were verified; authenticated browser interaction and driving were not.

Resource labels now describe the selected attempt without inferring its age or
asserting current RAM pressure from the generic error code. A fresh HTTP refusal
is distinguished from an ambiguous launch result. No quality or input gate was
removed. Video tracks also no longer unconditionally erase the upper 20% when
the selected policy is `none`; the existing game policy already excluded that
area, so this separate fix does not explain skuter2's initial failure.

## Explicit recovery of the same saved recording

After the API reload and fresh resource admission, one reviewed maintenance
intent resumed this exact recording. It preserved `input/**`, `control.json`
and `START`, archived the initial failed prepared directory and metadata under
`recovery-attempts/resource-refresh-v1`, and used the canonical owned worker and
monitor. Completed, source-bound image-review and speed caches were reused.
There was no browser capability extraction, game input or silent source edit.

The saved approved script is `recover-executed-v1.py`, SHA-256
`bbaac7d4029d328bf8221056b9bffc8e8e71a2418d0458f46a4d186e78062adc`,
matching the first preview and root authorization. A later on-disk guard-only
edit occurred after the process had loaded its code; that different file and
its diff are retained separately, not represented as the executed script.

The recovery procedure finished after 428.25 s and kept all source/cache hashes
unchanged. Its worker exited 1 with `camera_quality_gate_failed`, not
`resource_guard`. "Completed" in the maintenance receipt means that the
procedure finished; it does not mean reconstruction succeeded. The retained
primary model registered 124/209 cameras with 9,648 points and covered only
part of the source interval. It was not promoted to ready navigation.

## Stationary camera rotations and incomplete geometry

The first and last seconds contain intentional rotations while HUD speed is
zero. Optical motion is useful for selecting views but does not establish
translation. Such images can be resected against later triangulated landmarks;
they cannot independently provide a depth baseline. Missing poses must not be
filled by copying a center, interpolating positions or treating camera rotation
as driving.

The mapper did try moving-segment initialization pairs, not only the beginning.
For example, pairs around 20.85–21.05 s were attempted before stationary pairs
around 0.87–1.44 s. Some pure-view pairs were homography-only, but a planar
moving scene can also produce that configuration. HUD zero or homography status
alone cannot classify all translation as unobservable.

The remaining failure involves connected coverage and the existing short
endpoint-resection limit (one second/eight views), which is too small to cover
this recording's multi-second stationary surveys. A corrected method needs
measured 2D-to-3D registration for those views after a stable translated model;
lowering the acceptance threshold would not restore the missing geometry.

## Mask and control-mode boundaries

The old known-scooter preset admits only 25.62% of the 960×540 image after the
runtime margin. Actual source inspection confirms that its broad top/side
rectangles hide useful facade details. A tighter HUD candidate admitted 63.49%
with the same margin; that diagnostic candidate alone did not qualify dynamic
mirror or hand exclusion. Existing saved runtime masks remain unchanged.

Commit `1afb5df8` introduces the versioned
`black_russia_scooter_precise_rect_v2` plan for new known-scooter calculations.
It admits **55.962%** after the same runtime margin: fixed HUD controls have a
six-source-pixel margin at 1920×1080; three separate conservative foreground
regions cover expected hands/body. The 63.49% HUD-only candidate above is not
the product preset. Legacy `black_russia_scooter_rect_v1` remains selectable
explicitly and produces its original exclusions. Other control modes retain
their previous policy. Mask plan identity, SHA and producing module are bound
to the reconstruction recipe. Old feature caches are not relabeled v2.

The [actual source comparison](evidence/skuter2-processing-repair/masks.png)
shows frames at 0, 3.020, 20.018 and 39.916 s. It is not an inferred scene or a
generated mockup. Foreground coverage under arbitrary camera rotations remains
unqualified: a fixed preset cannot establish that all mirror/hand positions
are excluded. No additional street geometry is inferred from mask color.

A prepared scooter-recorded map is not permanently tied to a scooter input
controller. Walking checks the current live control profile. To test on foot,
leave the vehicle, select `Стик · ходьба / аналоговое управление`, check stick
and camera calibration, then select the walking test. This changes the current
input profile, not the saved video. It does not bypass map readiness, pose,
source, FOV or input confirmation. The existing offline replay calculates only
walking commands; it is not a vehicle replay implementation.

## Complete video versus recovered-camera interval

Commit `1a243ef3647ac834a70c238f0f1e7341bec8c3ba` adds one shared source-coverage
notice to review and live-route context. For this retained primary result it
reports source **0–39.916 s / 1,032 frames**, separately from measured cameras
**10.187–34.815 s / 124 views**. Prefix, suffix and internal gaps are explicit.
The camera count is not represented as a source-frame count. Alternate geometry
does not inherit an unverified selected-view denominator.

Only groups of neighboring cameras up to one second apart are painted on its
temporal bar. This is neither a per-frame pose interpolation nor an accuracy
score. Video time remains at the user's chosen source frame; it is not
automatically moved to the first registered camera. Standalone 3D and embedded
review use the same presentation without duplicate notices.

The UI slice passed 30 tests in five suites, TypeScript and seven browser checks
at desktop/mobile widths. Browser fixtures exercised the actual React component
and styles with synthetic timestamp metadata matching the observed counts;
they were not live-game or real-video localization acceptance. Canonical CI
and installed-image receipts are recorded separately.

That frontend commit was installed and HTTP-verified as image
`sha256:a6ba072af8dda5d534d58240a5845e8bb77839774fb30723d5acd19fd381eb7e`.
The second canonical frontend run and package completed in 210.172 s and
104.281 s, respectively, without changing resource checks. The canonical UI
run passed 3,264 tests in 241 suites. UI installation
preserved 1,035 protected assets and the other 65 containers. The API was then
reloaded from the same committed tree, including the new versioned mask code;
its receipt confirms unchanged assets, containers and configured watchdogs.
Existing stored route profiles still use their own original mask policy.

## Cached-measurement fusion experiments

The first two private candidates preserve all original job files and use
copies of the original sealed native databases. They combine native q512 SIFT
rows with video tracks; the original float feature cache is unavailable, so
these are not labeled as a rerun of the historical float-feature LightGlue
pipeline. The existing matches are reused without rerunning a neural matcher.
Both candidates use the legacy masks that produced those measurements.

Measured fusion contains 209 views, 364,122 native rows, 1,517 image pairs and
789,392 matches. These are measurement counts, not recovered 3D landmarks or
successful pose counts. Native verification completed. A strict intrinsic
initializer rejected the partial original model as a calibration prior; no
focal value was copied from that rejected prior.

Candidate v1 stopped at a 45-second calibration deadline. Candidate v2 allowed
120 seconds and completed that stage in **114.188 s**. Most of the time was
spent re-estimating relative poses for 1,105 pairs. This was active numerical
work, not an established deadlock. Global mapping then connected all 209 views
and created 23,367 tracks, but stopped at its **150-second** deadline during
bundle adjustment, before a model was serialized. Neither intermediate count
constitutes an accepted full reconstruction. Both failures are time budgets,
not observed memory shortages; owned process CPU/IO and resource samples are
retained.

The closed v2 database differs from the recorded post-calibration SHA even
with an empty WAL. It is therefore not reused as a byte-identical calibrated
checkpoint. A subsequent candidate must regenerate from the original sealed
databases or independently qualify a different checkpoint. No failed candidate
replaces a previous map or supplies input authority.

Candidate v3 regenerated fusion from the original databases and used four
verified native CPU affinities for calibration and global mapping. Calibration
completed in **36.672 s**. Global mapping serialized **209 cameras / 18,333
points / 0–39.916 s**, with mean reprojection error **0.780 px**. Its route
assessment still rejected camera reversals and speed outliers. Fixed-K bundle
adjustment completed in 17.187 s, after which structural checking rejected
`component_merge_nonpositive_depth`. The whole run finished in 237.422 s with
the original source and producer files unchanged. This is a useful complete
candidate for diagnosing tracks; it is not a corrected route or ready map.
The low reprojection error does not override the depth or motion failures.

A read-only audit of all native observations then found one track whose nine
observations became negative-depth after BA, around 4.257–6.690 s, with very
large residuals. Removing that track alone would not repair the candidate:
the final ten camera records (38.216–39.916 s) have zero remaining observations,
and some starting views have only 2–14 supported points. Thus 209 registered
camera records do not establish 209 measured, supported poses. The retained
primary map is not replaced by this candidate.

The [diagnostic comparison](evidence/skuter2-processing-repair/global-candidate.png)
uses real native camera centers and four unchanged source frames. One positive
Sim3 alignment on the 124 common cameras puts both models in comparable axes;
there is no reflection, route smoothing or forced loop closure. Weak/empty
camera records are marked explicitly. This failed candidate remains separate
from the web's selected route.

The production branch selection also differs from the strong historical
skuter1 calculation. Route-only starts with video tracks; fused recovery is
conditional on a failed baseline and an environment opt-in, and its normal
call does not explicitly request the LightGlue backend. A later standalone
LightGlue fallback builds a separate incremental model rather than the joint
video/SIFT global graph. Therefore the quality of the manual historical
candidate cannot be described as already reproduced automatically for every
new recording. A versioned automatic candidate requires its own source-bound
measurements, resource bounds, whole-model audit and regression evidence before
it can replace this branch.

## Fresh precise-mask observations

A separate owned stage regenerated measurements with precise-v2 masks from all
1,032 source frames and the same 209 selected original 1920×1080 PNGs. The old
mask, images and databases remain unchanged. This completed in **242.797 s**:
278,106 VIDEO observations (previous legacy cache: 184,868), 209 actual floating
RootSIFT caches, 1,058 LightGlue training pairs and 32 heldout loop pairs. Its
fused database contains 1,609 pairs and 1,026,427 correspondences. These counts
describe new image measurements; they are not 3D landmarks or accurate poses.

Temporal matching used the real floating descriptors; appearance-loop inputs
retained their explicitly named q512-decoded representation. Both matching
paths used CUDA, with the historical CPU-loop change recorded in the matcher
receipt. Native descriptor rows were checked against quantization of the
persisted float payload, and native keypoint rows matched float-cache geometry
exactly. The namespace refers to the real retained float cache.

At least **11.111 GiB** of physical RAM remained available in sampled checks;
the largest sampled tensor allocator reserve was **318,767,104 bytes**. This
does not measure all GPU driver/runtime allocations. The worker and children
were reaped, and all original/producers hashes remained unchanged. This stage
does not execute a native mapper or generate poses. Geometry admission is a
separate subsequent measurement, not implied by these larger feature counts.

## Fresh native candidate and rotation check

The subsequent precise-v2 global calculation completed inside its resource and
time bounds, with the original source and producers unchanged. It serialized
209 camera records and 19,325 raw points (18,939 after the 3-view filter), but
only 202 cameras had any supporting observation and only 200 had at least 15.
Seven cameras at 36.733–37.733 s had zero support. A moving interval at
18.534–18.684 s also produced a large discontinuity in this model's own gauge.
Fixed-K BA was therefore not started. This candidate is not published or used
for navigation; the low 0.804 px mean projection error does not repair those
failures. The owned runner closed every child in 248.906 s.

A separate read-only check compared native focal lengths: 614.363 px for the
new global candidate, 607.553 px for MAIN and 604.476 px for the skuter1
reference, all at 1920×1080. Six accepted tail rotation pairs gave 610.155 px
under fixed-center, square-pixel, zero-distortion assumptions. This small
difference does not establish a radically wrong FOV as the cause. The
unconstrained rotating-camera calibration was unsuitable; no numeric K prior
was forced or copied into the models.

The fresh image check also exposed a small uncovered server-logo area in the
bottom-left footer. New captures use precise-v3 to close it: 62.040% raw frame
area and 55.584% after the runtime feature margin remain eligible. Explicit
v1/v2 masks and stored route profiles remain byte-compatible. This changes
feature exclusion for new calculations; it is not a reconstruction acceptance.

The [experiment registry](../../operations/ROUTE-EXPERIMENTS.md) connects all
these attempts to the unchanged skuter1 reference and their dated evidence.

## Remaining acceptance

This repair establishes the cause and correction of the false resource refusal
and delivers accurate diagnostics. A connected, verified full skuter2 model,
fresh-frame localization and successful controlled route completion remain
separate acceptance steps. No statement here grants autonomous driving or
metric road accuracy.

## Primary references checked

[COLMAP's registration guidance](https://colmap.github.io/faq.html#register-localize-new-images-into-an-existing-reconstruction)
separates adding poses to an existing model from continuing mapping with
triangulation. Its [mask guidance](https://colmap.github.io/faq.html#mask-image-regions)
defines masks as feature exclusions, not generated image content.
[HLoc](https://github.com/cvg/Hierarchical-Localization) documents retrieval,
matching and pose-solver diagnostics as separate stages. These references guide
the investigation; they do not validate this game recording. The online COLMAP
documentation identifies itself as 4.3.0.dev0; the executed native runtime here
remains pinned to 4.2.1. No version upgrade or new matcher download was performed.
