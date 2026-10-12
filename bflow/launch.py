"""Starts BaggageFlow in one step: builds the page if needed, starts the
server and opens the browser. Ctrl+C (or closing the window) stops it.

    uv run baggageflow                 # what BaggageFlow.command / .bat run
    uv run baggageflow --port 8080 --no-browser

It runs the same server as ``uv run uvicorn bflow.server.app:app``, always on
127.0.0.1, so only this computer can reach it. If BaggageFlow already runs on
the port, it just opens the page; if something else uses the port, it takes
a free one.
"""

import argparse
import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from bflow.server.app import FRONTEND_DIST, create_app


HOST = "127.0.0.1"
DEFAULT_PORT = 8000
FRONTEND_DIR = FRONTEND_DIST.parent
# What the build is made from: newer than the build means build again.
FRONTEND_SOURCES = ["index.html", "package.json", "package-lock.json", "vite.config.js", "src", "public"]
# How long to wait for the server before opening the browser anyway.
STARTUP_TIMEOUT_S = 15


def is_baggageflow(port: int) -> bool:
    """Whether a BaggageFlow server answers on the port."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/status", timeout=1) as response:
            status = json.load(response)
    except (OSError, ValueError):
        return False
    return isinstance(status, dict) and "tick" in status and "scenario" in status


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def free_port() -> int:
    """A port nothing listens on, chosen by the system."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def newest_change(paths: list[Path]) -> float:
    """The latest modification time among files under the paths (0 if none)."""
    times = [0.0]
    for path in paths:
        if path.is_file():
            times.append(path.stat().st_mtime)
        elif path.is_dir():
            times.extend(item.stat().st_mtime for item in path.rglob("*") if item.is_file())
    return max(times)


def needs_build(frontend_dir: Path = FRONTEND_DIR) -> bool:
    """No build yet, or the page's sources changed since it was built."""
    built = frontend_dir / "dist" / "index.html"
    if not built.is_file():
        return True
    sources = [frontend_dir / name for name in FRONTEND_SOURCES]
    return newest_change(sources) > built.stat().st_mtime


def build_page(frontend_dir: Path = FRONTEND_DIR) -> bool:
    """Builds the page with npm when needed. False if it cannot be built."""
    if not needs_build(frontend_dir):
        return True
    built = (frontend_dir / "dist" / "index.html").is_file()
    npm = shutil.which("npm")
    if npm is None:
        if built:
            print("The page's sources changed, but npm was not found: using the existing build.")
            return True
        print("The page has not been built, and building it needs Node.js with npm "
              "(https://nodejs.org). Install it, then start BaggageFlow again.")
        return False
    print("Building the page (this takes a moment the first time)…", flush=True)
    steps = [[npm, "run", "build"]]
    if not (frontend_dir / "node_modules").is_dir():
        steps.insert(0, [npm, "ci"])
    for step in steps:
        if subprocess.run(step, cwd=frontend_dir).returncode != 0:
            print(f"Building the page failed ({' '.join(step[1:])}).")
            return built
    return True


def open_when_ready(url: str, port: int) -> None:
    """Opens the page in the browser once the server answers."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while not is_baggageflow(port) and time.monotonic() < deadline:
        time.sleep(0.2)
    webbrowser.open(url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="baggageflow", description="Start BaggageFlow and open it in the browser.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to use (default {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)

    port = args.port
    if is_baggageflow(port):
        url = f"http://{HOST}:{port}/"
        print(f"BaggageFlow is already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    if not build_page():
        return 1
    if not port_is_free(port):
        port = free_port()
    url = f"http://{HOST}:{port}/"
    print(f"BaggageFlow is running at {url}")
    print("To stop it, press Ctrl+C here (or close this window).")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, port), daemon=True).start()
    uvicorn.run(create_app(), host=HOST, port=port, log_level="warning")
    print("BaggageFlow stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
