"""Получить свежие логи Android agent — WS и стрим."""
import subprocess
import re

ADB = r"C:\LDPlayer\LDPlayer9\adb.exe"

# Получаем PID агента
pid_out = subprocess.check_output([ADB, "shell", "pidof", "com.sphereplatform.agent.dev.debug"], text=True).strip()
print(f"Agent PID: {pid_out}")

if not pid_out:
    print("Agent not running!")
    exit(1)

# Получаем logcat для этого PID
out = subprocess.check_output([ADB, "logcat", "-d", f"--pid={pid_out}"], text=True, timeout=10)
lines = out.strip().split("\n")
# Фильтруем по ключевым словам
keywords = re.compile(r"socket|ws|connect|onOpen|onClose|onFail|stream|auth|token|error|fail|close|heartbeat|pong|ping", re.IGNORECASE)
filtered = [l for l in lines if keywords.search(l)]
print(f"\n=== Last {min(40, len(filtered))} WS/stream lines ===")
for line in filtered[-40:]:
    print(line)

print(f"\n=== Last 20 lines (all) ===")
for line in lines[-20:]:
    print(line)
