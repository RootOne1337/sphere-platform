# Visual teach-and-repeat: recorded game video to closed-loop movement

Verified on 2026-10-31. This is a source/code review, not a claim that the external systems were run in Black Russia. No external weights were downloaded and no game commands were sent during this investigation.

## Conclusion

The user's requested workflow has a well-established name: **visual teach-and-repeat**. A recorded visual route, local visual localization and a feedback controller are sufficient in principle; a dense Gaussian rendering is not a prerequisite. Our route-map/PnP/optical-flow architecture belongs to this family. Its present shortcomings are delivery jitter, brittle interruption handling, uncalibrated game control dynamics and dependence on a globally reconstructed camera trace. More Gaussian iterations do not address those shortcomings.

The closest new reference for the original overlay idea is **LoTIS**. For a lighter controller, **FFI-VTR** is the most relevant feature-flow reference. Neither is presently a verified drop-in Android-game driver. Preserve the functioning SIFT/PnP/LK baseline and compare alternatives on recorded independent queries before granting them stick authority.

## Checked implementations

| System | What its authors actually provide | Mismatch with our input/runtime | Decision |
|---|---|---|---|
| [LoTIS, RSS 2026](https://github.com/KTH-RPL/lotis) | Cached encoding of an RGB reference sequence; query-image trajectory coordinates, visibility and relative distance. Local video/webcam inference and navigation evaluation are released. | DINOv3 backbone/weights plus LoTIS weights; game-domain and RX 9070 XT speed unmeasured. The released config has a 40-frame sequence limit. | Best candidate for an **offline/shadow image-space guidance comparison**, separate from live control. |
| [FFI-VTR, 2025 paper](https://arxiv.org/abs/2507.12800) / [authors' code](https://github.com/wangjks/FFI-VTR) | A keyframe graph, feature-flow motion indicators and probabilistic local planning without requiring accurate global reconstruction. | Released code is a VINS-Fusion/ROS package; README targets Ubuntu 16.04/18.04 and Kinetic/Melodic, with a platform-specific ONNX Runtime directory. It is not an MP4-to-Android application. | Reuse the **local feature-flow control principle** in an evaluated component; do not install the old robot stack into the current service. |
| [QVPR Teach-Repeat, IROS 2021](https://github.com/QVPR/teach-repeat) | Low-compute normalized image comparison plus a topometric route; an example velocity controller. | It explicitly requires monocular vision **and wheel odometry**, including integrated poses. Its default comparison image is only 115 × 44, but that is not a claim of video-only localization accuracy. | Useful reference for local search, lighting normalization and continuous correction. Our game video has no wheel-odometry channel. |
| [UTIAS VT&R3](https://github.com/utiasASRL/vtr3) | Local submaps and repeat navigation; multi-experience localization to bridge appearance changes. | Supported visual pipeline uses stereo; primary visual support requires NVIDIA/CUDA. The README's CPU-only option excludes Vision. | Strong architectural reference, poor direct match for one monocular game stream on this Windows/AMD host. |
| [ViNT / GNM / NoMaD](https://github.com/robodhruv/visualnav-transformer) | Pretrained image-goal navigation, topomap creation from a recorded demonstration, waypoint prediction and a separate PD controller. | Robot-domain policy and controller; released workstation prerequisites include CUDA. No evidence here for game camera/stick dynamics or AMD latency. | Candidate image-goal policy baseline, not a demonstrated replacement for the current motor/controller. |
| [STRoLL BearNav](https://github.com/gestom/stroll_bearnav) | Efficient visual heading correction during a taught route. | Teaching records velocities and travelled distance; repeating replays those velocities with image corrections. Plain MP4 does not supply that input. | Not the requested video-only, non-macro solution; useful heading-correction reference only. |

Repository revisions and release-file sizes are captured in [research-releases.json](walk-duration/research-releases.json). They are point-in-time checks, not a support or performance guarantee.

## LoTIS: particularly relevant, with important implementation limits

The [paper](https://arxiv.org/abs/2602.18803) separates image-space trajectory guidance from robot-specific action prediction. That fits our earlier proposal: infer the remaining route in a fresh game view, then let a controller follow the local target. It does not establish the true road surface or prove collision clearance in this game.

The [released configuration](https://github.com/KTH-RPL/lotis/blob/c3724e06b5c10897ddbc791ce930b41a90c65379/final_config.yaml) sets `MAX_SEQ_LEN: 40`. The CLI loads at most that many reference frames; preprocessing uniformly subsamples a longer video. Feeding an eight-minute video to the unmodified demo would therefore lose local density. Our adaptation would need ordered overlapping windows, an independent coarse route-position estimate and explicit transition checks. This is an inference from the checked code, not a released long-route integration.

The [setup instructions](https://github.com/KTH-RPL/lotis#setup) require DINOv3 and its weights, with a separate access process described by the authors. The LoTIS checkpoint itself is 118,422,240 bytes in the checked model repository. Neither the benchmark nor GPU compatibility was tested here; no gated weight access or large environment installation was attempted.

An important caveat appears in the **released navigation-evaluation adapter**, not merely in a demo picture. Its [default config](https://github.com/KTH-RPL/lotis/blob/c3724e06b5c10897ddbc791ce930b41a90c65379/nav_eval/configs/lotis_method.yaml) enables `use_geodesic_follower`. The [adapter](https://github.com/KTH-RPL/lotis/blob/c3724e06b5c10897ddbc791ce930b41a90c65379/nav_eval/methods/lotis.py) then uses simulator position, rotation and pathfinding/navmesh to guide its action. A direct image-angle control branch exists when that mode is disabled. We cannot count an evaluation with simulator geometry as a video-only controller for a game whose engine state we cannot access. This observation does **not** establish the configuration of every result in the paper.

## What differs in our current control chain

| Layer | Current implementation | Remaining issue / appropriate comparison |
|---|---|---|
| Route representation | Ordered reconstructed camera centres, reference orientations and selected real 3D landmarks | The camera trace is not a measured character footprint or a certified road corridor. Compare local overlapping submaps and image-space reference windows, rather than requiring globally perfect geometry. |
| Current localization | Descriptor retrieval, exact matching/PnP, map-anchored sparse optical flow between descriptor checks | Retain sequence continuity and competing-place rejection. Compare feature-flow guidance in shadow mode when metric pose fails, without silently promoting an unverified pose. |
| Continuous movement | Camera-relative arc lookahead, bounded stick slew and held native contacts | The maximum stick remains 35%; matching reference-video speed is not established. Camera/stick gain, cross coupling and saturation need measured game response. |
| Freshness | One in-flight JPEG/query; no queue; 250 ms control permit | Measured live JPEG/HTTP/source gaps can invalidate otherwise good geometry. A controller cannot remove those delays by adding map points. |
| Camera | Two-axis continuous drag with native ACK and visual response checks | Reference-view tracking still sometimes enters stationary alignment. Compare predictive target orientation and bounded view selection only after checking convergence/latency. |
| Recovery | Neutral reacquisition using current compatible geometry; bounded time and attempts | Transport loss, weak geometry and true wrong-place evidence must remain distinct. A blind camera search is not a remedy for an encoder stall. |
| Rendering | Separate source comparison, route map and optional Gaussian viewer | Display cadence is not control cadence. More Gaussian training cannot fix native input or delivery deadlines. |

[Nav2's Regulated Pure Pursuit](https://github.com/ros-navigation/navigation2/tree/main/nav2_regulated_pure_pursuit_controller) is a useful control reference: velocity-scaled lookahead, curvature-aware speed and acceleration constraints. Its documented controller speed does not include camera feature extraction or game input. Its collision handling also presupposes a usable costmap. Those prerequisites are not supplied by the current sparse landmark cloud.

[FLAF active view planning](https://arxiv.org/abs/2409.03457) supports selecting camera orientations from likely useful mapped features. For us that suggests a future **small, bounded, stationary** search aimed at expected visible landmarks, with both camera-angle and freshness limits. It does not justify turning blindly while translation is uncertain. No such search was enabled in this delivery.

## Acceptance for an alternative

1. Use a new repeat video or actual archived live query frames, with separate reference construction. A replay of map-building frames is only a regression test.
2. Compare current localization/control, image-space guidance and feature-flow guidance on the **same** queries. Record ordered progress, ambiguous matches, visibility, losses, yaw/pitch error and p50/p95/p99 end-to-end latency. Label model-predicted distance separately from known metric truth.
3. Include lateral offsets, camera pitch/yaw changes, altered lighting, partial occlusion and source delivery pauses. Never fabricate a new physical view by calling a 2D crop a measured displacement in metres.
4. Keep proposals read-only initially. Agreement with PnP is a consistency measurement, not independent ground truth. A learned line alone does not prove a safe obstacle-free route.
5. Before live promotion, verify held stick/camera commands, joint two-axis control, stop/closure acknowledgements, stale-source handling and resume at an independently re-recognized mid-route point.

The immediate v7 delivery fixes concrete time-limit, visibility and display-state defects; it does not claim that these research candidates are installed, that dynamic obstacle avoidance exists, or that a complete repeat has already passed.
