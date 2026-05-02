import os
import signal
import subprocess
import threading
import time
import logging
import sys

logger = logging.getLogger("restart")

# ANSI colors for signal stream
_COLORS = {
    "[THINK]": "\033[36m",  # cyan
    "[ACT]":   "\033[33m",  # yellow
    "[OBS]":   "\033[32m",  # green
}
_RESET = "\033[0m"

_signal_lock = threading.Lock()
_signal_line_count = 0

def _echo_signal(proc_name, text):
    """Print agent signal lines to terminal with color."""
    global _signal_line_count
    color = next((c for tag, c in _COLORS.items() if text.startswith(tag)), "")
    with _signal_lock:
        _signal_line_count += 1
        count = _signal_line_count
    if count % 5 == 1:
        text = time.strftime("[%H:%M:%S] ") + text
    try:
        print(f"{color}{text}{_RESET}", flush=True)
    except Exception:
        pass

class ManagedProcess:
    def __init__(self, name, args):
        self.name = name
        self.args = args
        self.proc = None
        self.env = {}
        self.output_thread = None
        self.last_start = 0.0
        self.backoff = 1.0
        self.restart_count = 0

    def start(self):
        try:
            logger.info("Starting %s: %s", self.name, " ".join(self.args))
            env_vars = os.environ.copy()
            env_vars.update(self.env or {})
            self.proc = subprocess.Popen(
                self.args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
                env=env_vars,
            )
            self.last_start = time.time()
            self.output_thread = threading.Thread(target=self._pipe_output, daemon=True)
            self.output_thread.start()
            logger.info("%s started pid=%s", self.name, self.proc.pid)
            return True
        except Exception:
            logger.exception("Failed to start %s", self.name)
            self.proc = None
            return False

    def _pipe_output(self):
        if not self.proc or not self.proc.stdout:
            return
        try:
            for raw in iter(self.proc.stdout.readline, b""):
                if raw is None:
                    break
                try:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    line = str(raw)
                logger.info("[%s] %s", self.name, line)
                # Echo agent signal lines directly to terminal
                if line.startswith(">> "):
                    _echo_signal(self.name, line[3:])
        except Exception:
            logger.exception("Error reading output for %s", self.name)
        finally:
            try:
                if self.proc and self.proc.stdout:
                    self.proc.stdout.close()
            except Exception:
                pass

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout=10.0):
        if not self.proc:
            return
        try:
            if self.proc.poll() is None:
                logger.info("Stopping %s pid=%s", self.name, self.proc.pid)
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                except Exception:
                    try:
                        self.proc.terminate()
                    except Exception:
                        pass
                try:
                    self.proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    logger.warning("%s did not exit in time, killing", self.name)
                    try:
                        os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                    except Exception:
                        try:
                            self.proc.kill()
                        except Exception:
                            pass
                    try:
                        self.proc.wait(timeout=5)
                    except Exception:
                        pass
        except Exception:
            logger.exception("Error stopping %s", self.name)
        finally:
            self.proc = None
            if self.output_thread and self.output_thread.is_alive():
                self.output_thread.join(timeout=1.0)
            self.output_thread = None
