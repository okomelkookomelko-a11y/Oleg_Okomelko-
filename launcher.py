"""Daemon launcher: keeps a long-lived parent so Chromium has a stable ancestor."""
import os, sys, subprocess

# First fork: original parent prints PID and exits to free relay
pid = os.fork()
if pid > 0:
    print(f"detached PID={pid}", flush=True)
    sys.exit(0)

# Child: become session leader (no controlling terminal)
os.setsid()

# Close inherited pipe FDs from cmd_runner so it sees EOF immediately
# Without this, cmd_runner blocks waiting for pipe close until gmail_register exits
devnull_fd = os.open('/dev/null', os.O_RDWR)
os.dup2(devnull_fd, 0)
os.dup2(devnull_fd, 1)
os.dup2(devnull_fd, 2)
if devnull_fd > 2:
    os.close(devnull_fd)

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
