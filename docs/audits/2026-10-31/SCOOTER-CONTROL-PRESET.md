# Black Russia scooter control preset

The route-recording page now offers **«Пресет · Black Russia: скутер»** after connecting a fresh stream. Applying it configures local controls only; it sends no Android input and does not start recording or an automatic route.

The user supplied a vehicle HUD screenshot and explicitly requested relative positions rather than fixed pixel coordinates. Pedal centres are stored as percentages:

| Control | X | Y | Keyboard / contact |
|---|---:|---:|---|
| Throttle, bottom-right pedal | 93.1% | 88.7% | W, pointer 0 |
| Brake, pedal to its left | 82.4% | 88.7% | S, pointer 0 |
| Steering joystick | Existing calibrated centre, otherwise 15% / 82% | Existing | A/D, pointer 1 |
| Camera | Existing calibrated origin, otherwise 65% / 50% | Existing | Left mouse drag, pointer 2 |

Throttle/brake and steering remain independent held contacts, allowing W+D or S+A. Opposing pedal keys cancel; opposing steering keys cancel. A floating steering stick first receives DOWN at its centre and then MOVE toward the horizontal target. It is not configured as two arbitrary left/right button taps. Additional action still requires its own explicit zone and shares the camera contact as before.

The preset retains a current valid stick/camera calibration. Percentage centres are converted to the current Android capture dimensions, and the resulting profile persists in the existing account/device/resolution storage. The existing four-button vehicle mode and pedestrian mode remain available. The preset does not convert the supervised pedestrian automatic route follower into a vehicle controller.

For the next scooter demonstration the user can keep HUD visible: the original capture retains speed and minimap pixels. Those are potential additional observations, **not currently implemented automatic speed OCR or minimap navigation**. HUD regions should be excluded from static-world landmark matching when preparing that recording; original pixels should remain intact.

Validation: 25 tests across profile scaling/persistence, independent pedal/steering targets, workbench selection without input and existing contact ownership passed. Scoped lint has zero errors and two pre-existing effect warnings. Production build/type checking and the local image probe/install are recorded in [delivery evidence](scooter-preset-delivery.json). No APK, processor or navigation-map change is required.
