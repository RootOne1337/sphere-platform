"""Bound marked one-off Android intermediate outputs; preserve APKs and reports.

Only a fixed Gradle init recipe naming its own gradle-output directory proves
ownership. Terminal logs are mandatory. This never touches source, shared SDKs,
model weights, databases, recordings, backups or Docker.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
from datetime import datetime,timezone
from pathlib import Path

from scripts.pilot.atomic_json import write_json

ROOT=Path(__file__).resolve().parents[2]
RECIPE=re.compile(r'allprojects \{ p -> p\.layout\.buildDirectory\.set\(new File\("([^"\r\n]+)", p\.name\)\) \}\s*\Z')
GENERATED={'intermediates','tmp','generated','kotlin','kspCaches','ksp','hilt','classes'}


def inventory(root: Path, *, keep=5):
    if type(keep) is not int or not 3<=keep<=10:raise ValueError('artifact_retention_keep')
    base=root/'.local-pilot/artifact-builds'
    if not base.is_dir() or any(p.is_symlink() or os.name=='nt' and p.is_junction() for p in (base,*base.parents)):
        raise ValueError('artifact_retention_root')
    runs=[];skipped=[]
    for directory in base.iterdir():
        if not directory.is_dir() or directory.is_symlink() or os.name=='nt' and directory.is_junction():continue
        recipe=directory/'fresh-build-output.gradle';log=directory/'android-build.log'
        if not recipe.is_file() or not log.is_file():continue
        if recipe.is_symlink() or log.is_symlink() or recipe.stat().st_size>4096:raise ValueError('artifact_retention_marker')
        match=RECIPE.fullmatch(recipe.read_text(encoding='utf-8-sig'))
        output=directory/'gradle-output'
        if not match or Path(match[1]).resolve()!=output.resolve():
            skipped.append(dict(name=directory.name,reason='recipe_not_owned'));continue
        with log.open('rb') as stream:
            stream.seek(max(0,log.stat().st_size-8192));tail=stream.read().decode('utf-8',errors='replace')
        if not re.search(r'BUILD (?:SUCCESSFUL|FAILED) in ',tail):
            skipped.append(dict(name=directory.name,reason='not_confirmed_terminal'));continue
        targets=[]
        if (directory/'project-cache').is_dir():targets.append(directory/'project-cache')
        if output.is_dir():
            for module in output.iterdir():
                if module.is_dir():targets.extend(module/name for name in GENERATED if (module/name).is_dir())
        runs.append(dict(name=directory.name,modified=max(recipe.stat().st_mtime,log.stat().st_mtime),targets=targets))
    runs.sort(key=lambda r:r['modified'],reverse=True)
    return base,runs[keep:],runs[:keep],skipped


def validate_target(target: Path, base: Path):
    target=Path(target)
    resolved=target.resolve(strict=True)
    if not resolved.is_relative_to(base.resolve()) or resolved==base.resolve():raise ValueError('artifact_retention_path')
    for p in (target,*target.parents):
        if p.is_symlink() or os.name=='nt' and p.is_junction():raise ValueError('artifact_retention_reparse')
    # Scan the whole finite target before recursive removal; never follow a
    # junction into shared caches or SDKs. Only metadata is collected here.
    total=count=0;stack=[str(target)]
    while stack:
        with os.scandir(stack.pop()) as children:
            for item in children:
                info=item.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                    raise ValueError('artifact_retention_reparse')
                if stat.S_ISDIR(info.st_mode):stack.append(item.path)
                elif stat.S_ISREG(info.st_mode):total+=info.st_size;count+=1
                else:raise ValueError('artifact_retention_nonregular')
    return dict(path=str(resolved.relative_to(base.resolve())),bytes=total,files=count)


def execute(root: Path, *, apply=False,keep=5):
    root=root.resolve(strict=True);base,eligible,retained,skipped=inventory(root,keep=keep)
    plan=[]
    for run in eligible:
        for path in run['targets']:plan.append(validate_target(path,base))
    result=dict(scope='MARKED_ANDROID_INTERMEDIATES_ONLY',apply=apply,keepLatest=keep,
                protectedRuns=[r['name'] for r in retained],skipped=skipped,targets=plan,
                logicalBytes=sum(r['bytes'] for r in plan),removed=[],freeHostBefore=shutil.disk_usage(root).free,
                apksPreserved=True,reportsPreserved=True,sourcePreserved=True)
    receipt=root/'.local-pilot'/('android-intermediate-retention-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    write_json(receipt,result)
    if apply:
        if os.name=='nt':
            commands=subprocess.check_output(['powershell','-NoProfile','-Command',
                "@(Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^(java|gradle|aapt2|kotlinc)\\.exe$'} | Select-Object -ExpandProperty CommandLine) | ConvertTo-Json -Compress"],text=True)
            if 'artifact-builds' in commands.lower():raise RuntimeError('artifact_build_process_active')
        for row in plan:
            target=base/row['path']
            if validate_target(target,base)!=row:raise RuntimeError('artifact_output_changed')
            resolved=target.resolve(strict=True)
            if not resolved.is_relative_to(base.resolve()):raise ValueError('artifact_retention_path')
            # All final absolute paths were checked. Extended paths support
            # deeply nested generated KSP/Hilt names on Windows.
            text=str(resolved)
            if os.name=='nt' and not text.startswith('\\\\?\\'):text='\\\\?\\'+text
            shutil.rmtree(text)
            result['removed'].append(row['path']);write_json(receipt,result)
    result['freeHostAfter']=shutil.disk_usage(root).free
    write_json(receipt,result)
    return result|dict(receipt=str(receipt.relative_to(root)))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');parser.add_argument('--keep',type=int,default=5)
    args=parser.parse_args();r=execute(ROOT,apply=args.apply,keep=args.keep)
    print(json.dumps(dict(apply=args.apply,targets=len(r['targets']),GiB=round(r['logicalBytes']/2**30,3),removed=len(r['removed']),receipt=r['receipt'])))


if __name__=='__main__':main()
