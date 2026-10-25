"""Install pinned local reconstruction tools, without changing system packages."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import httpx

from scripts.pilot.atomic_json import write_json
from scripts.pilot.resource_guard import collect, evaluate

ROOT = Path(__file__).resolve().parents[2]
WHEEL_SHA = 'b6a562b33bcbf0757c7b28c33b9166e095fa5451f9a4b38236018cf8a8d49380'
BRUSH_SHA = 'b68e3e9cf052d51bf3ee30776fa5a364de7f2ba13b58443128ff797bb7bcfcd6'


def download(client, url, path, expected, maximum):
    if path.exists():
        with path.open('rb') as file:
            if hashlib.file_digest(file, 'sha256').hexdigest() != expected:
                raise ValueError('existing_tool_hash_mismatch')
        return
    temporary = path.with_suffix(path.suffix + '.part')
    digest, used = hashlib.sha256(), 0
    with temporary.open('xb') as file, client.stream('GET', url) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes(1024**2):
            used += len(chunk)
            if used > maximum:
                raise ValueError('tool_download_quota')
            digest.update(chunk)
            file.write(chunk)
    if digest.hexdigest() != expected:
        raise ValueError('tool_download_hash_mismatch')
    temporary.rename(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, default=ROOT / '.local-pilot/motor-amd-venv/Scripts/python.exe')
    parser.add_argument('--uv', default=shutil.which('uv'))
    parser.add_argument('--learned-matching', action='store_true',
                        help='Install only the pinned optional LightGlue source/weights; GPU Python runtime stays unchanged')
    args = parser.parse_args()
    if not args.uv or evaluate(collect(ROOT)):
        raise RuntimeError('uv_or_resource_guard')
    folder = ROOT / '.local-pilot/reconstruction-tools'
    folder.mkdir(exist_ok=True)
    with httpx.Client(trust_env=False, follow_redirects=True, timeout=90) as client:
        package = client.get('https://pypi.org/pypi/pycolmap/4.2.1/json').raise_for_status().json()
        wheel = next(row for row in package['urls'] if row['filename'] == 'pycolmap-4.2.1-cp312-cp312-win_amd64.whl')
        path = folder / wheel['filename']
        download(client, wheel['url'], path, WHEEL_SHA, 30 * 1024**2)
        target = folder / 'pycolmap-4.2.1'
        if not (target / 'pycolmap').is_dir():
            subprocess.run([args.uv, 'pip', 'install', '--python', str(args.python), '--target', str(target), '--no-deps', str(path)], check=True)
        # Decoder stays isolated alongside COLMAP; the GPU environment is unchanged.
        av = client.get('https://pypi.org/pypi/av/16.1.0/json').raise_for_status().json()
        av_wheel = next(row for row in av['urls'] if row['filename'] == 'av-16.1.0-cp312-cp312-win_amd64.whl')
        av_path = folder / av_wheel['filename']
        download(client, av_wheel['url'], av_path, av_wheel['digests']['sha256'], 40 * 1024**2)
        if not (target / 'av').is_dir():
            subprocess.run([args.uv, 'pip', 'install', '--python', str(args.python), '--target', str(target), '--no-deps', str(av_path)], check=True)
        archive = folder / 'brush-app-v0.3.0-windows.zip'
        download(client, 'https://github.com/ArthurBrussee/brush/releases/download/v0.3.0/brush-app-x86_64-pc-windows-msvc.zip', archive, BRUSH_SHA, 180 * 1024**2)
        brush = folder / 'brush-v0.3.0'
        if not brush.exists():
            brush.mkdir()
            with zipfile.ZipFile(archive) as package:
                total = 0
                for entry in package.infolist():
                    if not (brush / entry.filename).resolve().is_relative_to(brush.resolve()):
                        raise ValueError('tool_archive_path_escape')
                    total += entry.file_size
                    if entry.file_size > 600 * 1024**2 or total > 1024**3:
                        raise ValueError('tool_archive_quota')
                package.extractall(brush)
        receipt = dict(pycolmap='4.2.1', pycolmap_sha256=WHEEL_SHA, av='16.1.0',
                       av_sha256=av_wheel['digests']['sha256'], brush='0.3.0',
                       brush_sha256=BRUSH_SHA, system_packages_changed=False)
        if args.learned_matching:
            from scripts.pilot.learned_route_features import SOURCE, WEIGHTS, paths, validate_assets

            source, weights = paths(ROOT)
            if not source.exists():
                source.mkdir()
                for command in (["git", "init", str(source)],
                                ["git", "-C", str(source), "remote", "add", "origin", "https://github.com/cvg/LightGlue.git"],
                                ["git", "-C", str(source), "fetch", "--depth", "1", "origin", SOURCE],
                                ["git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD"]):
                    if evaluate(collect(ROOT)):
                        raise RuntimeError('resource_guard')
                    subprocess.run(command, check=True, timeout=180,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            weights.parent.mkdir(parents=True, exist_ok=True)
            download(client, 'https://github.com/cvg/LightGlue/releases/download/v0.1_arxiv/sift_lightglue.pth',
                     weights, WEIGHTS, 60 * 1024**2)
            validate_assets(ROOT)
            receipt['lightglue'] = dict(source=SOURCE, weights_sha256=WEIGHTS, gpu_runtime_modified=False)
        write_json(folder / 'pinned-delivery.json', receipt)
        print(json.dumps(receipt))


if __name__ == '__main__':
    main()
