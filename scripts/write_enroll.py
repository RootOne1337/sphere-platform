import os, subprocess, sys

adb = r"C:\Users\dimas\AppData\Local\Android\Sdk\platform-tools\adb.exe"

# Build the full shell command as one string
# Use single quotes around URI to prevent & interpretation by Android shell
uri = "sphere://enroll?server=http%3A%2F%2F127.0.0.1%3A8888&key=sphr_deve_2aed17e41c2446e9f11eb26960576cebd81b4be9eb98d8e828ac99081d350357&device=433aaeb1-b2b8-40ab-af4c-f89b1868987c"

# Write as a shell script, using double quotes to protect &
script_content = f'am start -a android.intent.action.VIEW -d "{uri}" com.sphereplatform.agent.dev.debug\n'

tmp = os.path.join(os.environ["TEMP"], "enroll.sh")
with open(tmp, "w", newline="\n") as f:
    f.write(script_content)

subprocess.run([adb, "-s", "emulator-5554", "push", tmp, "/data/local/tmp/enroll.sh"], check=True)
result = subprocess.run(
    [adb, "-s", "emulator-5554", "shell", "sh", "/data/local/tmp/enroll.sh"],
    capture_output=True, text=True)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("Return code:", result.returncode)
