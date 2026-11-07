# Joint image bundle adjustment with a weak velocity-change prior

Offline diagnostic, not a route candidate for publication. A single deterministic selected dataset from the 166-camera converged targeted model uses 2000 real 3D points, with temporal stratification over eight bins. Each original (image ID, point ID) observation is assigned to heldout when BLAKE2b-64 modulo 5 is zero. Only points with at least three training observations and at least one held-out observation were retained: 13,493 training and 4,132 held-out 2D observations. The resulting held-out fraction is 23.44%, not exactly 20%, because point eligibility conditions on having held-out observations. The baseline model had already used all of these observations, so its apparent held-out score is an in-sample reference; w=0, fit on the same split as the other runs, is the relevant comparator. No independent recording or ground-truth poses are available.

All 166 camera centers and 2000 landmark positions were optimized jointly against actual training 2D feature coordinates. Camera rotations and intrinsics remain fixed to the baseline, an important limitation. C0 is fixed; the distance from C0 to the frame nearest 12 s (11.903 s, 4.9633 model units) is fixed exactly while that anchor's direction stays free. The prior residual is `weight * (v[i]-v[i-1]) / baseline_median_camera_rate`, with `v=(C[i+1]-C[i])/dt[i]` and baseline median rate 1.0641 model units/s. No forward-direction assumption, straight-line constraint or HUD measurement entered the objective. SciPy sparse LSMR uses soft_l1 and a 2-pixel scale over image residuals and prior residual components; weights were fixed at 0, .5 and 2 before the final run. This is a proposed regularizer, not a validated vehicle dynamics model.

| Variant | Termination | Train 2D median / p95 px | Heldout 2D median / p95 px | Heldout behind camera |
|---|---|---:|---:|---:|
| Baseline before split-fit, in-sample reference | n/a | .893 / 3.760 | .891 / 3.789 | 0 |
| w=0 split-fit control | ftol, 229 evals | .985 / 3.376 | 1.57866 / 5.15924 | 0 |
| w=.5 | ftol, 383 evals | .984 / 3.379 | 1.57936 / 5.17266 | 0 |
| w=2 | evaluation limit, 500 evals; **not converged** | .990 / 3.389 | 1.58240 / 5.18071 | 0 |

Relative to the same-split w=0 control, w=.5 increases held-out median by .00070 px and p95 by .01342 px; w=2 increases them by .00373 and .02147 px. These changes are very small and no uncertainty or independent generalization estimate was computed. Under the requested rule to reject a prior variant if heldout pixel fit worsens, neither weighted candidate is accepted. `ftol` is a numerical termination condition, not a guarantee of global optimum; w=2 did not reach it. Baseline versus split-fit is not an unbiased comparison because baseline used the subsequently held-out observations.

| Variant | Common-163 motion flags: reversal / speed outlier | Full-166 motion flags | Full-166 max step (model units) | HUD heldout scale-fit median absolute log / >4x |
|---|---:|---:|---:|---:|
| Original in-sample baseline | 25 / 2 | 25 / 2 | 4.290 | .603 / 5 of 60 |
| w=0 | 24 / 2 | 24 / 2 | 3.141 | .649 / 5 of 60 |
| w=.5 | 24 / 2 | 24 / 2 | 2.551 | .639 / 4 of 60 |
| w=2 | 21 / 0 | 21 / 0 | 1.559 | .665 / 3 of 60 |

Motion flags are heuristic and not actual turn counts; all three gauge-fixed models share the same anchor distance, but model units remain nonmetric. The w=2 geometry looks smoother under these heuristics while its heldout image fit worsens relative to w=0 and its optimization has not converged. HUD is evaluated after fitting on the same recording; median scale is fitted only to the first 65 eligible original edges and checked on the remaining 60 of the same 125 edges. The heldout label applies only to that scalar fit. HUD speed and camera/body coupling are unverified. There is no basis to prefer or publish a weighted geometry on this evidence.

`data.npz` is the fixed split and original track data, `prepare.json` the selection and gauge; `w0`, `w05`, `w2` contain per-case reports and diagnostics; comparison.json includes same-view motion, HUD and normalized velocity changes. Geometry outputs deliberately contain only the 2000-point subset and are marked `diagnostic_partial_point_subset=true`, execution/navigation false. They are not full-scene exports or primary replacements.

Earlier trial directories used equal 8 and then equal 100 function-evaluation ceilings for all three weights; neither introduced extra weights. The limit was raised equally to 500 because the 100-evaluation fits did not converge, not to tune against heldout results. All three stages here have the same 500 maximum and completed within 60 s per case. Wall time for final run 63.03 s; including the two preliminary runs about 89.22 s, under the 180 s experiment budget. The 4.5 GiB host RAM/commit guard was not triggered; minimum sampled RAM 9.74 GiB, commit headroom 18.87 GiB during final run. CPU-only; SciPy/BLAS/OpenCV bounded to at most two computational threads. Model binaries, source geometry, report and HUD input hashes matched before/after each run. No source, primary geometry, production, browser, device, autoplay or UI was changed.

## Visual review on common axes

`review-comparison.png` shows the original 166 baseline centers and the three fitted center sets in the same original camera-0 X/Z axes and identical plot bounds and scale. The first center stays fixed and the distance to the same 11.903 s anchor remains 4.9633 model units in every panel. The figure connects estimated camera centers; it does not show actual road geometry, between-frame truth or an autonomously drivable route. Green/red markers indicate first/last source frames. The baseline used all observations before the split, so the lower baseline error is not an independent held-out result.

| Variant | Heldout mean / p95 px | Max camera step vs w=0 | p95 normalized velocity change vs w=0 |
|---|---:|---:|---:|
| w=0 | 2.10034 / 5.15924 | reference | reference |
| w=.5 | 2.10381 / 5.17266 | −18.77% | −4.28% |
| w=2 | 2.11363 / 5.18071 | −50.36% | −9.77% |

The biggest changes are in intervals 27.236–27.468 s (step 3.141→2.551→1.559 model units) and 27.468–27.668 s (2.178→1.684→.813), for w0→w.5→w2. These percentages and lower max step only describe this model's smoothness; they are not accuracy improvement. w2 remains nonconverged. Differences in heldout image errors relative to w0 are tiny and no statistical significance was established; the prior changes the visual trajectory without establishing that any variant is correct. The image and all numerical details including source hashes are in `review-comparison.png` and `review-comparison.json`; this review did not rerun the fit.
