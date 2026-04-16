import argparse
import json
import logging
import os
import shlex
import signal
import sys
import threading
import time
import urllib.request

from .logger import setup_logger
from .process import ManagedProcess
from .cleaner import clean_log
from .log_utils import parse_crash_context

logger = logging.getLogger("restart")

INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 60.0
RESET_AFTER = 30.0


def build_crash_context_payload(ctx):
    """Build a plain-text crash narrative for the Scribe LLM."""
    parts = []

    last_cmd = str(ctx.get("last_command") or "").strip()
    if last_cmd:
        parts.append(f"Last action: {last_cmd}")

    env_state = [str(line).strip() for line in (ctx.get("environmental_state", []) or []) if str(line).strip()]
    if env_state:
        parts.append("\nRecent events:")
        parts.extend(env_state)

    fatal_errors = [
        str(err).strip()
        for err in (ctx.get("fatal_errors", []) or [])
        if str(err).strip()
    ]
    if fatal_errors:
        parts.append("\nFatal errors:")
        parts.extend(fatal_errors)

    return "\n".join(parts)


def run_log_cleaner(input_log, output_log):
    if not os.path.exists(input_log):
        return
    logger.info("Running log cleaner: %s -> %s", input_log, output_log)
    try:
        clean_log(input_log, output_log)
        logger.info("Log cleaner finished")
    except Exception:
        logger.exception("Error running log cleaner")

def main():
    parser = argparse.ArgumentParser(description="Configuration-driven restart daemon")
    parser.add_argument("--config", required=True, help="Path to config.json")
    args = parser.parse_args()

    try:
        with open(args.config, "r") as f:
            config = json.load(f)
    except Exception as e:
        print(f"Failed to load config from {args.config}: {e}")
        sys.exit(1)

    logfile = config.get("logfile", "restart_daemon.log")
    log_level = os.getenv("RESTART_DAEMON_LOG_LEVEL", "INFO")
    setup_logger(logfile, log_level)

    quiet = config.get("quiet", False)
    if quiet:
        # Suppress daemon lifecycle messages from terminal, keep in log file
        for handler in logging.getLogger("restart").handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handler.setLevel(logging.WARNING)

    # Path to write large crash context payloads. Can be overridden in config
    crash_ctx_file = config.get("crash_context_file")
    if not crash_ctx_file:
        crash_ctx_file = os.path.join(os.path.dirname(os.path.abspath(args.config)), ".crash_context.log")
    else:
        crash_ctx_file = os.path.abspath(crash_ctx_file)

    stopping = threading.Event()

    def _handle(signum, frame):
        logger.info("Received signal %s, shutting down", signum)
        stopping.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    procs = []
    post_cfg = None

    pre_cfg = config.get("pre_health_command")
    if pre_cfg:
        pre_cmd = shlex.split(pre_cfg["command"])
        pre_proc = ManagedProcess(pre_cfg["name"], pre_cmd)
        procs.append(pre_proc)
        pre_proc.start()

        health_url = pre_cfg.get("health_url")
        if health_url:
            health_ok = False
            timeout = pre_cfg.get("health_timeout", 300.0)
            poll_int = pre_cfg.get("health_poll_interval", 2.0)
            
            deadline = time.time() + timeout
            logger.info("Waiting up to %.0f seconds for %s", timeout, health_url)
            last_err = None

            while time.time() < deadline and not stopping.is_set():
                if not pre_proc.is_running():
                    logger.warning("%s is not running while waiting for health; restarting", pre_proc.name)
                    pre_proc.start()

                try:
                    req = urllib.request.Request(health_url, method="GET")
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        status = resp.getcode()
                        if status == 200:
                            logger.info("Health endpoint returned 200 OK")
                            health_ok = True
                            break
                        elif str(status) != last_err:
                            logger.info("Health endpoint returned %s", status)
                            last_err = str(status)
                except Exception as e:
                    msg = str(e)
                    if msg != last_err:
                        logger.info("Health check error: %s", msg)
                        last_err = msg

                if stopping.is_set():
                    break
                time.sleep(poll_int)

            if not health_ok:
                logger.error("Health check failed within timeout. Exiting.")
                stopping.set()
    
    if not stopping.is_set():
        post_cfg = config.get("post_health_command")
        if post_cfg:
            post_cmd = shlex.split(post_cfg["command"])
            post_proc = ManagedProcess(post_cfg["name"], post_cmd)
            procs.append(post_proc)
            post_proc.start()

    try:
        while not stopping.is_set():
            for p in procs:
                if stopping.is_set():
                    break

                if p.is_running():
                    continue

                exit_code = p.proc.poll() if p.proc else None
                if exit_code is not None:
                    logger.info("%s exited with code %s", p.name, exit_code)
                    
                    if pre_cfg and p.name == pre_cfg.get("name") and post_cfg:
                        # Docker died. Stop agent to remain consistent.
                        for other_p in procs:
                            if other_p != p and other_p.name == post_cfg.get("name") and other_p.is_running():
                                logger.warning("Docker stopped unexpectedly. Stopping agent.")
                                other_p.stop()

                    # If the process crashed and this is the post-health (agent) process,
                    # parse the cleaned logfile for crash context and expose it via env.
                    if exit_code != 0 and post_cfg and p.name == post_cfg.get("name"):
                        try:
                            # Clear old env first to prevent passing stale context
                            p.env = {}
                            cleaned_log = config.get("cleaned_log")
                            target_log_for_ctx = logfile
                            if cleaned_log:
                                # Ensure we parse the cleaned log as the log utils expect
                                target_log_for_ctx = os.path.abspath(cleaned_log)
                                run_log_cleaner(logfile, target_log_for_ctx)
                                
                            ctx = parse_crash_context(target_log_for_ctx)
                            if "error" not in ctx:
                                payload = build_crash_context_payload(ctx)
                                if payload:
                                    try:
                                        with open(crash_ctx_file, "w", encoding="utf-8") as cf:
                                            cf.write(payload)
                                            cf.write("\n")
                                        p.env = {"CRASH_CONTEXT_PATH": crash_ctx_file}
                                    except Exception:
                                        logger.exception("Failed writing crash context file for %s", p.name)
                        except Exception:
                            logger.exception("Error parsing crash context for %s", p.name)
                    else:
                        # On clean exit, ensure no crash context is propagated
                        if exit_code == 0:
                            p.env = {}
                            try:
                                if os.path.exists(crash_ctx_file):
                                    os.remove(crash_ctx_file)
                            except Exception:
                                logger.exception("Failed to remove crash context file %s", crash_ctx_file)
                else:
                    logger.info("%s is not running", p.name)

                runtime = time.time() - p.last_start if p.last_start else 0.0
                if p.last_start and runtime >= RESET_AFTER:
                    p.backoff = INITIAL_BACKOFF
                elif p.last_start:
                    p.backoff = min(p.backoff * 2, MAX_BACKOFF)
                else:
                    p.backoff = INITIAL_BACKOFF

                logger.info("Will restart %s in %.1f seconds (last runtime %.1f s)", p.name, p.backoff, runtime)

                slept = 0.0
                while slept < p.backoff and not stopping.is_set():
                    time.sleep(0.5)
                    slept += 0.5

                if stopping.is_set():
                    break

                if not p.start():
                    p.backoff = min(p.backoff * 2, MAX_BACKOFF)

            time.sleep(0.5)
    finally:
        logger.info("Shutting down child processes")
        for p in procs:
            p.stop()
        
        cleaned_log = config.get("cleaned_log")
        if cleaned_log:
            run_log_cleaner(logfile, cleaned_log)

if __name__ == "__main__":
    main()
