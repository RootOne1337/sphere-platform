# zaezd888: HUD contamination and bounded reconstruction recovery

The original reconstruction of `zaezd888` is invalid. Its 83 registered cameras
and 1.047 px mean reprojection error concealed a collapse of 1,355/1,586 points
onto camera centres. Rejecting that map was correct; the extraction, matching
and recovery workflow needed repairs. The original H.264 and its manifest have
not been rewritten.

## Source and evidence

Job: `c667f86cc9de4a378fb12e5269981a6e`. Capture: `a4574c036f4149b898b12e263ef98205`.

- 1920 × 1080; 901 real recorded frames; 35.493 seconds.
- Measured media cadence: 25.357 FPS, **not confirmed 30 or 60 FPS**.
- H.264 size: 40,825,272 bytes, approximately 9.20 Mbit/s over the recorded span.
- Median / p95 / maximum timestamp spacing: 34 / 52 / 100 ms.
- Manifest SHA-256: `67e22e330837646e4f0d3b0ab95895371f79136c54bd8c1b0014478aa8c3d417`.
- H.264 SHA-256: `0feaeae732c30d2f25ff1359f276f78f53ed029538243ac1b42ae1537192df1e`.

Local experiment evidence lives in `.local-pilot/zaezd888-diagnosis-20261031/`.
The date in that directory refers to the original recording; the follow-up audit
and delivery are dated 2026-11-01. No device input was sent during these trials.

## Verified defects

1. The generic walking mask missed the left edge of the brake, other vehicle
   controls and the raised left mirror. The original graph contained **357 of
   628 pairs classified WATERMARK**, no CALIBRATED pairs, and a median adjacent
   displacement of 0.084 px in the right overlay region. These observations
   describe the graph, not a semantic proof about every stationary feature.
2. OpenCV applies SIFT's strongest-feature limit before masking. Sharp excluded
   screen overlays could spend the detection quota. A real initial frame yielded
   51 unmasked features with a 1,024-detection limit versus 1,957 with an
   8,192-detection budget. The matcher still receives only its bounded final
   feature quota. A synthetic regression reproduces this starvation without
   shipping the user's video in tests.
3. Route-only preparation disabled learned matching and gated its existing
   repairs behind the learned/dense branch. A failed optical-track reconstruction
   had no independent automatic alternative.
4. The largest reconstruction component was chosen before checking degeneracy.
   Repair detection also ignored failed point conditioning when all cameras had
   registered. Camera count and a low image error do not establish correct motion.
5. Route-only CPU preparation used the heavy-render resource threshold even
   though that stage loads no neural model. Free physical RAM and Windows commit
   are different constraints and must both be measured.

## Implemented behavior

- Capture-aware vehicle masks now cover pedals, HUD and the observed mirror/body
  regions. The same exclusions feed optical sampling, KLT, SfM masks and route
  feature export. Walking presets and explicit unmasked capture retain their
  previous policy. A vehicle preset is selected from the **saved profile**, not
  inferred from game content; a mislabeled capture remains a limitation.
- Vehicle sampling uses a shorter maximum time interval, retaining more actual
  source views within the existing 240-view limit. It does not create video
  frames or interpolate poses. An opt-in wider offline KLT pyramid handles larger
  inter-frame motion; live tracking retains its previous default.
- Native verification can filter stationary correspondences, and mapping ignores
  pairs classified as watermarks. Stationary image displacement is not used as a
  universal semantic classification of scenery.
- Learned extraction first budgets 8,192 SIFT detections, then applies the final
  unmasked 1,024/2,048/4,096-feature quota. The existing pinned model/checkpoint
  validation and no-download loading path remain in effect.
- Every model is assessed before ranking. Scene admissibility and complete-route
  admissibility are separate. Complete-route assessment additionally requires
  source endpoints within one second, no camera gap over one second and no
  detected temporal reversal/speed outlier. These are necessary checks, not metric
  ground truth or an obstacle-free-road certificate.
- Route-only failure can trigger **one isolated learned recovery** on the same
  images/index. It has a 420-second total fence, a 180-second native mapping limit,
  two mapping threads, at most four models and a 1,024-feature matcher budget.
  Available acceleration is preferred; CPU remains bounded. Only a complete
  admissible improvement replaces the baseline. An existing intent is not rerun.
- Source RGB hashes are checked before recovery links its workspace. Baseline
  features/models survive. First-pass geometry and quality are saved even if a
  later optional neural load is refused. Cancellation and resource refusals defeat
  adoption, including completion races.
- CPU route preparation has a scoped 6–12 GiB admission budget based on compressed
  source size, a 4 GiB host reserve, 90% Windows commit ceiling **and** absolute
  commit reserve. Dense rendering and optional learned loading retain their
  previous heavy admission. No page-file changes, application termination or
  cache deletion are part of this fix.

## Actual reconstruction trials

| Variant | Result | Interpretation |
|---|---|---|
| Original KLT | 83/83; 1,586 points; 85.44% collapsed | Invalid, despite 1.047 px image error |
| Denser masked KLT, fixed diagnostic focal | Separate 14 / 67 / 71-view components | Useful local segments; no shared whole-route scale |
| Corrected world-feature LightGlue | 92 / 72 principal components; estimated focal ≈604 / 609 px | Better coverage; one common view does not establish a reliable merge |
| GLOMAP, source-estimated fixed focal | 163/163; 5,546 full-model points; 1.032 px; no collapsed points | Full temporal coverage, but 3 reversals and 5 speed outliers remain |
| Per-image focal refinement | 163 views, 12.84% collapsed points | Rejected; more camera parameters worsened conditioning |
| Source-frame-supported LightGlue + GLOMAP | Separate 91 / 71-view components | Fewer temporal defects, but still not a complete accepted route |

The fixed focal values in the experiments are **estimates**, not measured game
camera calibration. GLOMAP is an experiment here; it has not been made an
unconditional production fallback.

The full GLOMAP result is published to the existing web alternative-geometry
selector as `global-163-requires-review`, explicitly **DIAGNOSTIC_ONLY**. Its
browser payload contains 5,544 points after the existing reprojection filter.
The original primary job, its capability and its failed status remain unchanged;
this alternative is not a localization map or a driving authorization.

## Why the remaining jumps were not smoothed away

A CPU PnP audit re-triangulated landmarks from at least two **other** observations,
excluding each query's own observation. At 3.318 seconds, 72/105 retained
correspondences supported a re-estimated pose only 0.405 units from the current
pose. This did **not** remove the approximately eight-unit trajectory jump. The
current graph/scene itself supports the error. This is an internal consistency
check; all other poses still come from the same recording, so it is not an
independent held-out localization result.

A separate CPU minimap-motion experiment decoded all 901 frames in 13.28 seconds.
It accepted 773/900 transitions; **127 gaps break coordinate chains explicitly**.
Between 3.087 and 3.318 seconds the minimap chain has a path length of 8.327 px
and displacement of 8.286 px, with no corresponding teleport or reversal. This
independently contradicts the SfM discontinuity as real vehicle motion. However,
accumulated HUD scale changes and gaps prevent treating it as a continuous or
metric route. `motor_worker/minimap.py` currently extracts a calibrated colored
GPS line; the experimental minimap odometry is not wired into live control.

Consequently this delivery does not claim successful autonomous scooter replay,
metric road geometry or an error-free whole route. No new recording is required
to inspect these artifacts. Remaining work is to obtain independent constraints
for the suspect links/scale, validate on unused frames and only then admit a live
control test. The existing pedestrian controller is not a vehicle autopilot.

## Reproduction and validation

Read-only graph audit:

```powershell
.local-pilot/motor-worker-venv/Scripts/python.exe -m scripts.pilot.audit_route_feature_graph `
  --prepared .local-pilot/reconstruction-jobs/c667f86cc9de4a378fb12e5269981a6e/prepared `
  --output .local-pilot/new-exclusive-feature-audit.json
```

Regression coverage includes masked-feature starvation, original RGB preservation,
stationary native verification, vehicle temporal overlap, full-count collapsed
candidates, partial tails/gaps, route-only recovery wiring, one-shot intents,
cancellation/adoption races, source hashes and scoped resource admission. See the
adjacent delivery JSON for final test counts and source/runtime hashes.

Primary references: [COLMAP matching and reconstruction](https://colmap.github.io/tutorial.html),
[COLMAP model and mapper tradeoffs](https://colmap.github.io/faq.html),
[official LightGlue implementation](https://github.com/cvg/LightGlue).
These references explain the tools; the numerical results above are local evidence.
