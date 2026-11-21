#!/usr/bin/env python3
"""Rehearse MinIO data in an isolated container; compare S3 keys and SHA-256."""
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import boto3
from botocore.config import Config


def run(*args, **kwargs):
    return subprocess.run(['docker', *args], check=True, **kwargs)


def main():
    folder = Path(sys.argv[1]).resolve()
    config = json.loads((folder / 'container-configs-sensitive.json').read_text())
    item = next(x for x in config if x['Name'].endswith('-minio-1'))
    env = dict(e.split('=', 1) for e in item['Config']['Env'] if '=' in e)
    process_env = os.environ.copy()
    for k in ('MINIO_ROOT_USER', 'MINIO_ROOT_PASSWORD'):
        process_env[k] = env[k]
    image = item['Image']
    volume = 'sphere-migration-test-' + uuid.uuid4().hex
    cid = None
    try:
        run('volume', 'create', volume, capture_output=True)
        with (folder / 'volume-minio_data.tar.gz').open('rb') as f:
            run('run', '--rm', '-i', '--network', 'none', '--mount', f'type=volume,src={volume},dst=/data',
                'alpine:latest', 'tar', 'xzf', '-', '-C', '/data', stdin=f, capture_output=True)
        cid = run('run', '-d', '--network', 'none', '-e', 'MINIO_ROOT_USER', '-e', 'MINIO_ROOT_PASSWORD',
                  '--mount', f'type=volume,src={volume},dst=/data', image, 'server', '/data',
                  env=process_env, capture_output=True, text=True).stdout.strip()
        shell = 'export MC_HOST_migr="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@127.0.0.1:9000"; exec mc "$@"'
        def mc(*args):
            return subprocess.run(['docker', 'exec', cid, 'sh', '-c', shell, 'sh', *args], capture_output=True)
        for _ in range(60):
            listing = mc('ls', '--json', 'migr')
            if listing.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Isolated MinIO did not become ready')
        buckets = [json.loads(line)['key'].rstrip('/') for line in listing.stdout.splitlines()]
        old = {}
        for bucket in buckets:
            listing = mc('ls', '--recursive', '--json', 'migr/' + bucket)
            if listing.returncode:
                raise RuntimeError('Cannot list restored bucket')
            for line in listing.stdout.splitlines():
                data = json.loads(line)
                if data.get('type') == 'file':
                    old[(bucket, data['key'])] = data['size']
        client = boto3.client('s3', endpoint_url='http://127.0.0.1:19000', aws_access_key_id=env['MINIO_ROOT_USER'],
                              aws_secret_access_key=env['MINIO_ROOT_PASSWORD'], config=Config(signature_version='s3v4'))
        live_buckets = [x['Name'] for x in client.list_buckets()['Buckets']]
        live = {}
        for bucket in live_buckets:
            for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket):
                for obj in page.get('Contents', []):
                    live[(bucket, obj['Key'])] = obj['Size']
        mismatched = 0
        for (bucket, key) in old.keys() & live.keys():
            restored = mc('cat', 'migr/' + bucket + '/' + key)
            if restored.returncode:
                raise RuntimeError('Cannot read restored object')
            original = client.get_object(Bucket=bucket, Key=key)['Body']
            h = hashlib.sha256()
            for chunk in iter(lambda: original.read(1024 * 1024), b''):
                h.update(chunk)
            mismatched += h.digest() != hashlib.sha256(restored.stdout).digest()
        print(f"Buckets: restored {len(buckets)}, live {len(live_buckets)}, symmetric differences {len(set(buckets)^set(live_buckets))}.")
        print(f"Objects: restored {len(old)}, live {len(live)}, differing key/size entries {len(set(old.items())^set(live.items()))}, SHA-256 mismatches {mismatched}.")
        print('Comparison is against current live state, which may change during capture.')
    finally:
        if cid:
            subprocess.run(['docker', 'rm', '-f', cid], capture_output=True)
        subprocess.run(['docker', 'volume', 'rm', volume], capture_output=True)


if __name__ == '__main__':
    main()
