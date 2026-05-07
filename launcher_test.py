"""Same launcher pattern but for pw_test.py — to isolate if launcher.py or gmail_register.py is the culprit."""
import os, sys, subprocess

pid = os.fork()
if pid > 0:
    print(f"detached PID={pid}")
    sys.exit(0)

os.setsid()

pid2 = os.fork()
if pid2 > 0:
    sys.exit(0)

log = open("/home/bot/my-bot/pw_test.log", "ab", buffering=0)
devnull = open("/dev/null", "rb")
subprocess.Popen(
    ["/home/bot/my-bot/venv/bin/python3", "-u", "/home/bot/my-bot/pw_test.py"],
    stdin=devnull, stdout=log, stderr=log,
    cwd="/home/bot/my-bot",
    start_new_session=True,
    close_fds=True,
)
