# restart

A generic, configuration-driven restart daemon deployed as a Python module.
It runs a configured `pre_health_command`, polls a health endpoint, and then starts a `post_health_command`, restarting either if they exit unexpectedly.

## Installation

```sh
cd /home/user_a/projects/sandbox/restart
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

Create or edit `config.json` in the root folder. See the default `config.json` for managing the local Docker container and `agent.py`.

## Usage (Interactive)

```sh
/home/user_a/projects/sandbox/restart/.venv/bin/python -m restart --config /home/user_a/projects/sandbox/restart/config.json
```

Logs are written to `restart_daemon.log` (configurable in JSON) and printed to stdout. On exit, logs are automatically cleaned up and output to `cleaned.log`.

## systemd Service Example

You can copy the provided `restart_daemon.service` into `/etc/systemd/system/` to run it as a background daemon.

```sh
sudo cp restart_daemon.service /etc/systemd/system/restart_daemon.service
sudo systemctl daemon-reload
sudo systemctl enable --now restart_daemon.service
```

## Stopping the daemon

### systemd-managed
Use `systemctl` to stop, disable, or check the service:

```bash
sudo systemctl stop restart_daemon.service
sudo systemctl disable restart_daemon.service   # prevent auto-start on boot
sudo systemctl status restart_daemon.service    # verify state and recent logs
```

### Interactive (foreground)
If you started the daemon in the foreground, stop it with Ctrl+C (SIGINT). Expect the process to exit cleanly and write cleaned logs to `cleaned.log` as described above.

```bash
/home/user_a/projects/sandbox/restart/.venv/bin/python -m restart --config /home/user_a/projects/sandbox/restart/config.json
# then press Ctrl+C to stop
```

### Background (no systemd: nohup / & / screen / tmux)
If the daemon was started in the background (nohup, `&`, or inside `screen`/`tmux`), find its PID and send SIGTERM:

```bash
# find candidate processes (adjust pattern if needed)
ps aux | grep -i "python.*-m restart" | grep -v grep
# or use pgrep to get PIDs
pgrep -f "python -m restart"

# send SIGTERM to a single PID
kill -TERM <PID>

# safe pkill example (matches full command line, sends SIGTERM)
pkill -15 -f "python -m restart"
```

Be careful with `pkill -f` and narrow the pattern to avoid killing unrelated processes.

### Verify it's stopped
Use `ps` or `systemctl` to confirm the daemon is no longer running:

```bash
ps aux | grep -i "python.*-m restart" | grep -v grep
# or for systemd-managed service
sudo systemctl status restart_daemon.service
```

### Logs
On clean shutdown the daemon writes cleaned logs to `cleaned.log` (see the Usage section). If you forcibly kill the process, inspect `restart_daemon.log` and `cleaned.log` and remove or archive them as needed.


## Notes

- The daemon uses exponential backoff (1s -> 2s -> 4s ... up to 60s) when a process repeatedly exits quickly.
- If a process runs for 30 seconds or more, its backoff is reset to 1 second.

## LLM Configuration

The agent reads LLM settings from `agent-core/.env` at startup. Edit that file to switch providers, then use the matching config:

| Provider | `.env` block to activate | Config file |
|---|---|---|
| Local llama.cpp | `# --- Local llama.cpp ---` block | `config.local.json` |
| Google Gemini | `# --- Google Gemini ---` block | `config.gemini.json` |

### Local llama.cpp

```sh
/home/user_a/projects/sandbox/restart/.venv/bin/python -m restart --config /home/user_a/projects/sandbox/restart/config.local.json
```

Starts Docker + llama.cpp, waits for health check, then starts the agent.

### Google Gemini

Edit `agent-core/.env`: comment out the local block, uncomment the Gemini block, and fill in your API key. Then:

```sh
/home/user_a/projects/sandbox/restart/.venv/bin/python -m restart --config /home/user_a/projects/sandbox/restart/config.gemini.json
```

No Docker is started — the agent connects directly to the Gemini API.

> **Security**: `agent-core/.env` contains your API key. Do not commit it to version control.
