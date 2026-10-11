"""The real app in a browser, with the runner on a fake clock.

Each test gets its own server, in a thread, serving the Vite build: the
page connects to it as it would to uvicorn. The runner's clock only moves
when a test moves it, so the page shows exactly the ticks the test ran.
Skipped when Playwright or the build is missing:

    uv add --dev pytest-playwright && uv run playwright install chromium
    npm --prefix frontend run build
"""

import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn

from bflow.core.engine import STEP_SECONDS
from bflow.server.app import FRONTEND_DIST, create_app
from bflow.server.runner import Runner


HERE = Path(__file__).parent


def pytest_collection_modifyitems(items):
    """Runs the browser tests last: Playwright's sync API keeps an event loop
    running in the main thread until the session ends, and a later test
    calling asyncio.run() would fail."""
    items.sort(key=lambda item: HERE in item.path.parents)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Plant:
    """The server of one test: its address, its clock and a way to run ticks."""

    def __init__(self, url: str, clock: FakeClock) -> None:
        self.url = url
        self.clock = clock

    def status(self) -> dict:
        with urllib.request.urlopen(f"{self.url}/api/status") as response:
            return json.load(response)

    def commands(self) -> list[dict]:
        with urllib.request.urlopen(f"{self.url}/api/commands") as response:
            return json.load(response)

    def wait_for(self, condition, timeout: float = 5.0) -> dict:
        """Polls /api/status until condition(status) holds, and returns it."""
        deadline = time.monotonic() + timeout
        while not condition(status := self.status()):
            if time.monotonic() > deadline:
                raise AssertionError(f"status still {status}")
            time.sleep(0.01)
        return status

    def run_ticks(self, ticks: int) -> int:
        """Moves the clock until the running engine has stepped `ticks` more (at 1×).

        At most 5 ticks of real time at a time, each waited for, so the
        runner never drops a backlog. Returns the tick reached.
        """
        target = self.status()["tick"] + ticks
        while (tick := self.status()["tick"]) < target:
            self.clock.now += min(target - tick, 5) * STEP_SECONDS
            self.wait_for(lambda status: status["tick"] > tick)
        return target

    def idle(self, seconds: float) -> None:
        """Moves the clock with nothing expected to happen (paused)."""
        self.clock.now += seconds
        time.sleep(0.1)  # a few runner updates


@pytest.fixture
def plant():
    if not (FRONTEND_DIST / "index.html").is_file():
        pytest.skip("no frontend build: npm --prefix frontend run build")
    clock = FakeClock()
    app = create_app(Runner(clock=clock))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("the test server did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield Plant(f"http://127.0.0.1:{port}", clock)
    server.should_exit = True
    thread.join(timeout=10)
