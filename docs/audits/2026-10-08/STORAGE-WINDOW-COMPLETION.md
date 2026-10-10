# Storage incident: completed finite window, attribution still open

8 October 2026. This supersedes the observer's earlier running checkpoints,
without rewriting their raw reports. No cleanup or new collector was started.

## Completion and coverage

The limited, unprivileged observer completed at09:01:34.471173 UTC. Its last
complete sample was09:01:25.607563 UTC. All241 samples at120-second intervals
were read from the bounded JSONL report. Report2210733B is within16MiB budget.
PID36664 was independently absent when work resumed at18:07 UTC. No autostart
was configured; the interval after09:01 is not covered by this observer.

Source SHA256 d71e5c7a9fa028f91098d47c224ce53ba11723d06f03f0ee1b248dc4ce5c4bc6.
Private report: `.local-pilot/host-storage-limited-20261008T010125Z`.
[Sanitized scalars and report hash](STORAGE-WINDOW-COMPLETION.json).

| Measurement | First | Last | Interpretation |
| --- | ---: | ---: | --- |
| C: free bytes | 53474902016 | 46517481472 | −6957420544B, about6.48GiB |
| Docker VHDX allocated/logical bytes | 234731077632 | 234731077632 | Constant in all241 samples |
| Four named LDPlayer VMDKs | Same allocation | Same allocation | Constant in all241 samples |
| Docker guest used KiB | 186465412 | 189863448 | Guest contents grew inside existing VHD extents |
| WMI pagefile allocated base MiB | 48320 | 48320 | Endpoint unchanged; not a filesystem allocation trace |
| VSS measurement | Unavailable | Unavailable | All241 samples; no zero inferred |

All five watched files had one reported identity and one logical/allocated size
across the window. Therefore growth of those five host files does not explain
the measured C: loss. This does not rule out Docker-related effects elsewhere,
shadow-copy allocation, build/download files, or unrelated writers. VSS was not
measured; the earlier7October VSS attribution cannot be copied onto this window.

Docker df reported images189→198,175.3→178.7GB; volumes7.253→7.304GB;
containers318.1MB and build cache84.42GB unchanged. Reviewed CI archives and
new images were downloaded/installed during this window. Docker categories
share layers and use rounded sizes; summing them is not physical disk accounting.
No image/cache/volume pruning or host VHD compaction occurred here.

Host RAM/commit endpoints and bounds are recorded in the JSON. A change between
two snapshots is not a confirmed memory leak, OOM or a specific process's retained
allocation. Process IO rates include other traffic and are not file growth.

## Current read-only checkpoint and next incident response

At approximately18:19 UTC C: free50005229568B and Docker VHDX logical size
234731077632B were read independently. This later endpoint does not fill the gap
or attribute intervening changes. No universal writer attribution is claimed.

At recurrence, first verify collector process creation identity, last complete
sample age, coverage/deadline and remaining report budget. Correlate file
allocation deltas with bounded elevated NTFS/ETW/VSS evidence if available.
Do not infer current monitoring from a stale running status, launch duplicate
collectors, or substitute bytes-written counters for allocated growth.

[Observer checkpoints](STORAGE-OBSERVER-LIVENESS.md) ·
[Host resource procedures](../../operations/HOST-RESOURCES.md).
Storage incident remains OPEN; development resumes independently.
