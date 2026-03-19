#!/usr/bin/env python3
"""Проверяет Redis-лог прогресса таска."""
import json
import os
import sys
import redis

task_id = sys.argv[1] if len(sys.argv) > 1 else "1d42b978-5e36-49b7-a2c1-d201c9235810"

rc = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"), decode_responses=True)
key = f"task_progress_log:{task_id}"
entries = rc.lrange(key, 0, -1)
print(f"Log entries: {len(entries)}")
for e in entries[-40:]:
    d = json.loads(e)
    node_id = d.get("node_id", "?")
    done = d.get("nodes_done", 0)
    print(f"  [{done:3d}] {node_id}")
