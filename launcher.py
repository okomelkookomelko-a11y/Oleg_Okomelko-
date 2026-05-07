"""Daemon launcher: keeps a long-lived parent so Chromium has a stable ancestor."""
import os, sys, subprocess, time

# First fork: original parent prints PID and exits to free relay
pid = os.fork()
if pid > 0:
    print(f"detached PID={pid}")
    sys.exit(0)

# Child: become session leader (no controlling terminal)
os.setsid()

# Open log files for gmail_register.py output
log_out = open("/home/bot/my-bot/gmail_register.log", "ab", buffering=0)
log_err = open("/home/bot/my-bot/gmail_register.err", "ab", buffering=0)
devnull_in = open("/dev/null", "rb")

# Spawn the actual gmail_register.py — keep this process alive as parent
proc = subprocess.Popen(
    ["/home/bot/my-bot/venv/bin/python3", "-u", "/home/bot/my-bot/gmail_register.py"],
    stdin=devnull_in, stdout=log_out, stderr=log_err,
    cwd="/home/bot/my-bot",
)

# Wait for child to complete (so Chromium has a live ancestor)
proc.wait()
