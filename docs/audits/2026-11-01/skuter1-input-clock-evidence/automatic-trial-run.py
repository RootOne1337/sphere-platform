"""One isolated helper trial; no source job publication or feature extraction."""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.resource_guard import windows_memory

ROOT = Path.cwd().resolve()
OUT = ROOT / '.local-pilot/skuter1-automatic-postprocess-20261101-v1'
SOURCE = ROOT / '.local-pilot/reconstruction-jobs/6a77040681d142ec97d51831a22785fb'
JOB, PREPARED = OUT / 'job', OUT / 'job/prepared'
GIB = 2**30
stage = argparse.ArgumentParser()
stage.add_argument('--stage', choices=('merge', 'endpoints'), required=True)
STAGE = stage.parse_args().stage
BEGAN = time.monotonic()
LIMIT = 150 if STAGE == 'merge' else 90
receipt = OUT / (STAGE + '-receipt.json')
if receipt.exists() or (OUT / (STAGE + '-intent.json')).exists():
    raise RuntimeError('exclusive_stage_already_exists')

class Memory(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
        (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
        'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
        'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.restype = ctypes.c_void_p
kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
psapi = ctypes.WinDLL('psapi', use_last_error=True)
psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Memory), ctypes.c_ulong]
psapi.GetProcessMemoryInfo.restype = ctypes.c_int
handle = kernel.GetCurrentProcess()
allowed, system = ctypes.c_size_t(), ctypes.c_size_t()
assert kernel.GetProcessAffinityMask(handle, ctypes.byref(allowed), ctypes.byref(system))
bits = [1 << i for i in range(ctypes.sizeof(allowed) * 8) if allowed.value & (1 << i)][:2]
assert bits and kernel.SetProcessAffinityMask(handle, sum(bits))

samples, violations = [], []
finished = threading.Event()
last_sample = 0.

def snapshot():
    memory = windows_memory()
    process = Memory()
    process.cb = ctypes.sizeof(process)
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(process), process.cb):
        raise RuntimeError('resource_guard_rss_unknown')
    return dict(seconds=time.monotonic() - BEGAN, **memory,
                rss_bytes=process.WorkingSetSize, peak_rss_bytes=process.PeakWorkingSetSize,
                free_disk_bytes=shutil.disk_usage(OUT).free)

def sample(admission=False):
    global last_sample
    current = snapshot()
    reserve = (3 if admission else 2) * GIB
    if (current['availableRamBytes'] < reserve
            or current['commitLimitBytes'] - current['committedBytes'] < reserve
            or current['committedBytes'] / current['commitLimitBytes'] >= .9
            or current['rss_bytes'] > 1.5 * GIB
            or current['free_disk_bytes'] < .5 * GIB):
        raise RuntimeError('resource_guard_postprocess')
    last_sample = time.monotonic()
    samples.append(current)
    with (OUT / (STAGE + '-resources.jsonl')).open('a', encoding='utf8') as stream:
        stream.write(json.dumps(current) + '\n')
    return current

def check():
    if (JOB / 'CANCEL').exists() or (OUT / 'CANCEL').exists():
        raise RuntimeError('cancelled')
    if violations:
        raise RuntimeError(violations[0])
    if time.monotonic() - BEGAN > LIMIT:
        raise RuntimeError('postprocess_stage_timeout')
    if time.monotonic() - last_sample >= .5:
        sample()

def watch():
    while not finished.wait(.5):
        try:
            sample()
            check()
        except Exception as error:
            violations.append(str(error))
            return

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024**2):
            check()
            h.update(block)
    return h.hexdigest()

def protected():
    paths = [p for p in SOURCE.iterdir() if p.is_file()]
    paths += list((SOURCE / 'input').iterdir())
    paths += [SOURCE / 'prepared/database.db', SOURCE / 'prepared/database.db-wal',
              SOURCE / 'prepared/reconstruction-input.json']
    for folder in (SOURCE / 'prepared/models').iterdir():
        paths += list(folder.iterdir())
    paths += [SOURCE / 'prepared' / row['image'] for row in json.loads(
        (SOURCE / 'prepared/reconstruction-input.json').read_bytes())['images']]
    return {path.relative_to(SOURCE).as_posix(): sha(path) for path in paths if path.is_file()}

result = dict(stage=STAGE, execution_qualified=False, navigation_qualified=False,
              source_modified=False, feature_extractions=0, network_downloads=0,
              physical_actions=0, process_pid=os.getpid(), cpu_affinity_mask=sum(bits))
thread = None
try:
    initial = sample(True)
    write_json(OUT / (STAGE + '-intent.json'), dict(stage=STAGE, admission=initial,
        source_job=str(SOURCE), owned_job=str(JOB), cpu_affinity_limit=2,
        admission_reserve_gib=3, runtime_reserve_gib=2, max_own_rss_gib=1.5,
        outer_seconds=LIMIT, source_start=0., source_end=36.903, selected=173,
        physical_actions=0, execution_qualified=False))
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    if STAGE == 'merge':
        assert not JOB.exists()
        before = protected()
        write_json(OUT / 'original-source-hashes.json', before)
        (JOB / 'input').mkdir(parents=True)
        (PREPARED / 'images').mkdir(parents=True)
        assert (SOURCE / 'prepared/database.db-wal').stat().st_size == 0
        for path in (SOURCE / 'input').iterdir():
            assert path.is_file() and not path.is_symlink()
            os.link(path, JOB / 'input' / path.name)
        shutil.copy2(SOURCE / 'prepared/database.db', PREPARED / 'database.db')
        shutil.copy2(SOURCE / 'prepared/reconstruction-input.json', PREPARED / 'reconstruction-input.json')
        for row in json.loads((PREPARED / 'reconstruction-input.json').read_bytes())['images']:
            check()
            os.link(SOURCE / 'prepared' / row['image'], PREPARED / row['image'])
        shutil.copytree(SOURCE / 'prepared/models', PREPARED / 'models')
        result['workspace_inputs'] = dict(source_inputs_hardlinked=True, pngs_hardlinked=173,
            database_copied=True, model_binaries_copied=True, hardlink_targets_never_written=True,
            source_cancel_exists=(SOURCE / 'CANCEL').exists(), isolated_cancel_exists=(JOB / 'CANCEL').exists())
    else:
        before = json.loads((OUT / 'original-source-hashes.json').read_bytes())
        assert protected() == before
        assert (OUT / 'ENDPOINT-READY').is_file()
    import numpy as np
    import pycolmap as p
    from scripts.pilot.reconstruct_route import model_assessment
    from scripts.pilot.route_component_merge import merge_components, structural_audit
    from scripts.pilot.route_geometry_selection import candidate_rank
    assert p.__version__ == '4.2.1' and 'torch' not in sys.modules
    def progress(phase, done, total):
        check()
        print(json.dumps(dict(phase=phase, done=done, total=total, seconds=time.monotonic()-BEGAN)), flush=True)
    if STAGE == 'merge':
        result['helper_sha256'] = sha(ROOT / 'scripts/pilot/route_component_merge.py')
        models = {int(path.name): p.Reconstruction(path) for path in (PREPARED / 'models').iterdir()}
        baselines = []
        for identity, rec in models.items():
            check()
            _, assessment = model_assessment(rec, PREPARED, 173, 0., 36.903, check=check)
            baselines.append((rec, dict(assessment, model=identity)))
        baseline, result['baseline_assessment'] = max(baselines, key=lambda row: candidate_rank(row[1]))
        result['baseline_models'] = [r for _, r in baselines]
        rec, report = merge_components(JOB, PREPARED, models, baseline, 173, 0., 36.903,
                                       check, progress, assessment_check=check)
        write_json(OUT / 'merge-result.json', report)
        result['helper_result'] = report
        (OUT / 'merge-chosen').mkdir()
        rec.write(OUT / 'merge-chosen')
    else:
        helper = ROOT / 'scripts/pilot/route_endpoint_resection.py'
        expected = (OUT / 'ENDPOINT-READY').read_text().strip()
        result['helper_sha256'] = sha(helper)
        assert result['helper_sha256'] == expected, 'endpoint_source_not_ready_revision'
        from scripts.pilot.route_endpoint_resection import repair_endpoints
        baseline = p.Reconstruction(OUT / 'merge-chosen')
        rec, report = repair_endpoints(JOB, PREPARED, baseline, 173, 0., 36.903,
                                        check, progress, assessment_check=check)
        write_json(OUT / 'endpoints-result.json', report)
        result['helper_result'] = report
        assert sha(helper) == expected, 'endpoint_source_changed_during_trial'
        (OUT / 'final-chosen').mkdir()
        rec.write(OUT / 'final-chosen')
    check()
    geometry, assessment = model_assessment(rec, PREPARED, 173, 0., 36.903, check=check)
    result.update(assessment=assessment, structural=structural_audit(rec, check=check),
        registered=rec.num_reg_images(), points=rec.num_points3D(),
        mean_reprojection_px=rec.compute_mean_reprojection_error(),
        torch_imported='torch' in sys.modules)
    write_json(OUT / (STAGE + '-geometry.json'), geometry)
    write_json(OUT / (STAGE + '-assessment.json'), assessment)
    after = protected()
    result.update(source_before=before, source_after=after, source_modified=before != after)
    assert before == after, 'original_source_changed'
    result['status'] = 'completed'
except BaseException as error:
    result.update(status='failed', error_type=type(error).__name__, error=str(error))
    raise
finally:
    finished.set()
    if thread is not None:
        thread.join(2)
    result.update(seconds=time.monotonic() - BEGAN, samples=len(samples),
        peak_own_rss_bytes=max((s['peak_rss_bytes'] for s in samples), default=0),
        min_host_available_bytes=min((s['availableRamBytes'] for s in samples), default=0),
        violations=violations)
    write_json(receipt, result)
    print(json.dumps({k:result.get(k) for k in ('stage','status','registered','points','seconds','error','peak_own_rss_bytes','source_modified')}), flush=True)
