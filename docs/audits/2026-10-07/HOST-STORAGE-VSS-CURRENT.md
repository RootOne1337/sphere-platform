# Current storage pressure: measured VSS growth and finite system observation

Recorded: 2026-10-07, UTC; operator timezone UTC+5. Installed UI/API: `a41c4e6`.
Incident remains **OPEN**. This report adds a short attributed episode to the
[completed eight-hour window](HOST-STORAGE-FOLLOWUP.md); it does not attribute
that entire window or all historical disk loss to one process.

[Sanitized counters and receipt hashes](HOST-STORAGE-VSS-CURRENT-EVIDENCE.json) ·
[Docker image/layer inventory](DOCKER-STORAGE-RETENTION.md) ·
[Operator procedure](../../operations/HOST-RESOURCES.md) ·
[Current acceptance state](../../operations/CURRENT-STATE.md).

## What has been proved

Elevated WPR recording actually started at **11:21:41 UTC** and completed at
11:22:28. Four volume/VSS snapshots span 11:21:42–11:22:12, about 30 seconds.
The existing named recorder stopped early at its free-space-drop threshold;
its own named stop returned zero and saved a 28,303,682-byte ETL.

| Counter | First snapshot | Last snapshot | Difference |
| --- | ---: | ---: | ---: |
| Free C: bytes | 25,462,697,984 | 25,226,952,704 | -235,745,280 |
| VSS allocated bytes | 16,802,201,600 | 17,037,082,624 | +234,881,024 |
| VSS used bytes | Measured | Measured | +168,116,224 |
| VSS maximum bytes | 20,461,912,064 | 20,461,912,064 | Unchanged in this episode |

VSS allocation growth accounts for **99.63%** of the measured free-space loss
in this episode. This is volume allocation attribution, not proof of which
application caused each copied block or changed the VSS policy.

The bounded Microsoft TraceEvent 3.2.8 reader retained 9,185 FileWrite events /
48,867,336 logical write bytes and 12,860 DiskWrite events / 136,577,024 bytes.
EventsLost=0. FileWrite and DiskWrite overlap and MUST NOT be added as unique
growth. The retained FileWrite interval is **11:21:52.492–11:22:12.088 UTC**;
the circular recording does not preserve the full earlier observation interval.
The parser excludes saving/rundown events after the last volume snapshot.

Top retained logical writes include NTFS `$Mft` and `$LogFile` under System,
PC Manager analysis database/journal writes and small application state writes.
These observations do not prove that PC Manager changed the quota. Absence of
a large Docker VHD write in this short retained interval does not exonerate
Docker in other windows. Private paths/PIDs and the raw trace stay local.

## The previously approved quota drifted

The [original application receipt](../2026-10-05/VSS-RETENTION-REVIEW.md)
verified an **8 GiB** C:→C: maximum at 2026-10-04 22:58:31 UTC and again at
23:04:43. A native read already observed the higher limit on 6 October.
Today's exact CIM counters confirm **20,461,912,064 bytes**, about 19.06 GiB.
The actor and precise time of that change remain **UNDETERMINED**.

The current Microsoft provider held two newer copies dated 6 October.
A System Restore record names Windows Update. That record and nearby Volsnap
events establish that restore activity occurred; they do not establish who
changed MaxSpace. No persistent audit policy or system restore service setting
was changed to manufacture that attribution.

At **11:25:16 UTC**, the already operator-approved 8 GiB policy was reapplied.
Fresh guards verified C: Healthy/OK, volume/diff-volume identity, provider,
current copy IDs and the inspected maximum. The native resize returned zero;
the exact resulting maximum was verified as **8,589,934,592 bytes**.

| Counter | Before our resize | After our resize |
| --- | ---: | ---: |
| Free C: bytes | 46,663,110,656 | 64,169,930,752 |
| VSS allocated bytes | 17,506,844,672 | 0 |
| VSS used bytes | 16,999,628,800 | 0 |
| Restore copy count | 2 | 0 |

Our measured free-space increase is **17,506,820,096 bytes / 16.304 GiB**.
**Both inspected restore copies were removed by the quota reduction.**
System Restore was not disabled; there was no fallback global snapshot deletion,
Docker restart, rollback of project data or deletion of ordinary user files.

The operator separately confirmed deleting an unrelated file before this
command, causing an approximately 20 GiB free-space jump. That jump is **not
credited to our cleanup**. Future restore points can consume space up to the
quota, so the incident is not accepted as fixed merely because free C: rose.

## Docker cleanup is a separate measurement

Two guarded finite applications removed **39 explicitly owned historical
images**: 34 runtime images and five web-test images. Exact IDs/tags and all
46 running/stopped container epochs were checked before each ordinary image
removal. Both prior UI/API rollback images remain present.

Guest filesystem used bytes fell by **12,766,756,864 / 11.890 GiB** in total.
The main Docker VHDX remained **234,731,077,632 bytes** in host length and
measured allocation. This is reclaimed guest capacity, not 11.890 GiB returned
to C:. Exact-ID cache prune experiments reclaimed **0 B**, not a successful
84 GB cache cleanup. Foreign images, containers and volumes were preserved.
Offline VHD compaction has not been performed.

## What the operator's nine screenshots add

PC Manager reports used C: **928.1 / 952.9 GB**, an increase of **20.3 GB**
against its previous scan. The visible category changes are user files +11.4,
application files +2.5, system files +435.7 MB and Other +6.0 GB. Rounded
category changes are consistent with the rounded overall increase.

The detailed views still show Docker **218.8 GB**, approximately the same as
the screenshots from 4 October. Thus those screenshots do not show a 20.3 GB
increase of the Docker VHD itself. AppData 420.7 GB includes multiple consumers;
Documents 97.1 GB is broader than this checkout. The ChatGPT directory is
22.1 GB, while the separately listed Documents/sphere-platform directory is
1.8 GB and is **not this checkout's path**.

The LDPlayer detail lists `leidian0` **20.4 GB**, `leidian1` **15.1 GB** and
`leidian2` **1.0 GB**. Live metadata confirmed six VMDK files, with matching
logical and allocated byte measurements. The two larger instances' data files
are actively modified. A modified timestamp is not evidence of growth; two
comparable allocation snapshots are required. No emulator disk was deleted,
compacted or modified by this investigation.

Metadata-only checks of other visible consumers found Amuse **41,832,686,269 B**,
with 31,793,445,298 B in diffusion models and 6,125,392,518 B in text encoders.
This is a complete accessible logical inventory, not a measured growth trend.
The `.gemini` scan reached its 200,000-entry bound: visible browser-recording
directories account for 7,936,040,487 B, 7,936,040,487 B and 5,073,910,807 B.
That scan is explicitly partial; hard links were not deduplicated, so it cannot
prove the physical bytes or infer that similarly sized trees are removable copies.
Roaming also reached the entry bound; a large PrismLauncher instances directory
was observed but no complete Roaming total is claimed. The complete `.codex`
logical inventory was 6,787,885,975 B, including sessions 4,872,286,364 B.
File contents, conversations and credentials were not read by these scans.

The visible Other rows account for only part of its 135.7 GB category. The
screenshots do not identify every protected/root allocation or quantify VSS.
They also have no exact scan timestamp: today's later live free-space counter
cannot be compared to their free-space number as if it were the same instant.

## Actual collection now running

The limited observer was stopped only after matching its command line and
creation epoch. Its 18 collected samples are preserved and explicitly marked
`superseded-by-elevated-observer`.

**Elevated host observer:** started **11:27:02 UTC / 16:27 local**, due
**19:27:02 UTC / 00:27 on 8 October local**. Actual administrator=true and
VSS state=measured, not merely an elevation request. The finite 241-sample,
120-second cadence records free space, VSS identity/used/allocated/max,
physical RAM, commit/limit, paged/nonpaged pools, process start epochs/private
bytes/working sets, process IO, pagefile and the Docker VHD. Docker/WSL are
sampled every eight cycles, about 16 minutes, including guest `df`, container
epochs/stats and `/proc/meminfo` to distinguish Linux cache from anonymous RAM.
Reports are capped at 16 MiB, individual samples at 128 KiB.

**Event-triggered supervisor:** actually started elevated at **11:38:18 UTC**,
using the host observer above; it shares that observation deadline. Every
15 seconds it reads only the latest complete bounded sample. It saves kernel
FileIO/DiskIO/process traces after cumulative free-space loss of 128 MiB,
VSS allocation growth of 128 MiB, VSS membership or maximum changes.
It rebases at boot changes and handles user cleanup as a new free-space peak.
Unavailable VSS is unknown, not an empty healthy baseline.

At most four serial captures, each up to ten minutes, with a ten-minute cooldown
after each attempt. Each child uses a fresh named 128 MiB in-memory WPR profile
and stops only its own instance. A pre-existing/unknown recording is not stopped.
An unknown child result stops further captures; the supervisor does not kill
PowerShell during its trace-save/finally block. Metadata is capped at 1 MiB;
after cumulative saved ETLs reach 512 MiB there are no further attempts.
**That post-save accounting threshold is not a hard maximum ETL file size**:
one final save can exceed the threshold. Low-headroom child guards still apply.

These are **post-trigger** traces, with detection latency bounded by the
120-second source cadence plus supervisor polling under normal operation.
They cannot recover a write that finished before recording started. A stale,
future, malformed or oversized source sample stops the supervisor with an
explicit error; it does not report successful coverage. No autostart,
cleanup, VSS-policy enforcement loop or Android commands are configured.

**LDPlayer named-file observer:** six reviewed VMDKs, 97 samples / 300 seconds,
eight hours, 8 MiB total / 1 MiB per snapshot. It reads file metadata/allocation
and free C: only, not emulator contents. Its separate snapshot window is not
yet complete. Raw private folders and launch statuses are listed in the runbook.

## Additional live checks after VSS reached zero

At 11:49 UTC, the first 12 elevated snapshots cover 22 minutes: free C:
64,147,873,792→64,088,104,960 B, net **-59,768,832 B / 57 MiB**. VSS remains
measured at zero with the verified 8 GiB maximum. This smaller residual loss is
not attributed to VSS. Commit fell to 65,172,099,072 B, available physical RAM
rose to 12,750,786,560 B, and WSL working set fell about 4.75 GiB. WSL private
bytes remained approximately 19 GB. That short window is not a heap-leak soak;
large private/reserved memory is not interchangeable with resident RAM.

Three WSL `/proc/meminfo` snapshots at11:27/11:43/11:59UTC reinforce that
boundary: AnonPages2,222,432→2,241,192KiB, Cached5,598,060→5,601,500KiB,
SReclaimable5,409,804→5,409,956KiB, MemAvailable20,804,272→20,790,240KiB.
These are guest Linux counters, not an attribution of all host WSL private
bytes. A19GB host private counter is not proof of19GB leaked anonymous guest RAM.
Docker image/cache counts and reported sizes remained unchanged in those three
snapshots; total volume size rose about3MB in rounded CLI output, not tens of GB.

`git count-objects -v` measured553,599KiB loose objects and24,276KiB packed
objects, with one12,420KiB temporary garbage object. This is roughly0.55GiB
object storage, not the hundreds of GB in Docker. That orphan is reported,
not deleted or treated as the root cause; Git history was not reset/repacked
by this investigation. No Antigravity/Gemini/Amuse process-name matches were
observed in the queried current process inventory; this does not rule out a
differently named helper or historical growth in their storage directories.

A second actual elevated **180-second** kernel recording ran at
11:51:15–11:54:30 UTC, 18 volume snapshots. VSS stayed zero; measured free space
between the first/last snapshots increased **532,480 B**. The final trace save
occurred after the last snapshot and produced 38,039,730 B, which is our
diagnostic storage and must not be mistaken for an unknown application leak.
Retained FileWrite records cover11:51:16–11:54:06; EventsLost=0,
188,034,767 logical bytes /37,445 events, and 113,540,096 DiskWrite bytes.

Observed writes include Windows remote-client automatic ETL, application
state replacement files, PC Manager's analysis DB/journal, Docker VHD and
browser/application caches. Live metadata showed the remote-client ETL at
exactly100MiB, PC Manager DB about2.3MiB and journal0B. Thus hundreds of MB of
logical writes in that window did not become hundreds of MB of retained
files. No process is declared the residual-loss writer from write totals alone.

**Whole-C: NTFS changed-file observer** actually started elevated at
**11:54:52 UTC /16:54 local**, planned241×120s /eight hours. It reads the
existing USN journal from its current cursor, then resolves changed file IDs
and measures current length/storage API counters. No journal is created,
deleted, resized or reset. This covers filenames across C:, including outside
Sphere; raw paths stay private. First sightings are baselines, not the size
of newly allocated data. Same-identity later snapshots provide deltas.

The observer reads at most8MiB of journal data /10s per cycle, resolves at
most256 changed IDs with data-extension priority, caches4096 measurements,
and stores at most256KiB per sample /16MiB total. More changed IDs produce
`partial_budget` with an explicit unresolved count; no complete resolution
claim. A wrapped/replaced journal, unsupported record format or read-backlog
budget produces a stopped-error coverage gap, not healthy zero. Unresolvable,
deleted or atomically replaced files stay unavailable/incomparable. USN has
no writer PID; pair file-growth evidence with the kernel trace for process
attribution. This reader does not recover file sizes from before its start.

The implementation was checked against Microsoft's [journal request layout](https://learn.microsoft.com/windows/win32/api/winioctl/ns-winioctl-read_usn_journal_data_v0),
[record layout](https://learn.microsoft.com/windows/win32/api/winioctl/ns-winioctl-usn_record_v2)
and [file-ID opening API](https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-openfilebyid),
accessed2026-10-07. It does not attempt to rewrite filesystem metadata.

The first follow-up native cycles actually resolved73 and120 changed regular
files. Unresolved/deleted IDs and directories are preserved as unavailable,
not silently counted as measured. The first comparable growth included Docker
Desktop `init.log.0` +745,452B over one two-minute interval. A fresh directory
check then found nine rotated `init.log.N` files around1MiB each; the last64KiB
contained no error/warning matches. That rotation must not be mistaken for
unbounded permanent growth: subsequent identity/total measurements are needed.
It is separate from Docker's container stdout logs and the234GB data VHD.

## Incident acceptance remains open

The first **automatic** trigger was exercised on the running host at
12:17:02 UTC, without a manual WPR start. Its owned child recorded five volume
samples, finished at12:17:59 UTC, stopped its named trace successfully, and
saved25,111,189B ETL. SHA-256:
`96822668278a1ae7f1cba0d0af28f713f679e4a9d34f6db204d7de0aa37b5330`.
The child reported a186,048,512B free-space fall during capture. This proves
automatic capture and owned stop/save, not the identity of the growth writer.
The supervisor remains running with one of four attempts consumed. Saved
traces are part of our diagnostic storage; their bytes must be accounted for.
The eight-hour collectors stop by their recorded deadlines and do not restart
after Windows reboot; preserved reports remain available for later analysis.

1. Exact VSS growth explains the captured short free-space-loss episode.
2. The full historical loss and the process changing the quota remain open.
3. The new RAM/commit/WSL window is running; no completed RAM-leak soak is claimed.
4. Reclaimed guest image capacity has not yet reduced the host Docker VHD.
5. Total uploaded-log quotas, cross-worker coordination and real object expiry
   remain separate future capacity work; current small log/object volumes do
   not prove adequate 500–1000-device retention.

Collector source commits: kernel supervisor **a52defd**, NTFS reader **32c2278**;
the installed product runtime remains **a41c4e6**. Metadata observers are not a
new frontend/API/APK release.

Focused diagnostic suite: **109 passed / 34 subtests**. Ruff and unrestricted
mypy passed for all three diagnostic production modules. The two previously
unannotated locals in `disk_growth.py` now have
explicit list/optional-counter types, and the saved previous free counter uses
the already measured integer rather than an inferred heterogeneous dictionary.
This stage does not claim a full backend or APK test run. Pure tests exercise
cumulative loss, manual cleanup, rearm, duplicate/old samples, reboot boundaries,
VSS unknown vs measured-empty, quota drift, malformed input, concurrent partial
appends, bounded tail reads and unknown-child cancellation boundaries. USN
tests cover real-layout Unicode/variable records, malformed length/alignment,
unsupported versions, same-file growth/shrink, baseline vs creation and
missing allocation vs identity replacement.
