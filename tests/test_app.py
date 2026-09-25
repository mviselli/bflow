"""FastAPI app: start, pause and resume through the WebSocket, as a browser would.

The app runs its own runner loop in a background thread. Tests never call the
runner directly: they send commands, move the fake clock and wait until the
status shows the expected state.
"""

import json
import time

from fastapi.testclient import TestClient

from bflow.server.app import create_app
from bflow.server.runner import Runner


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make_app():
    clock = FakeClock()
    runner = Runner(clock=clock)
    return create_app(runner), runner, clock


def wait_for_status(client: TestClient, expected: dict) -> None:
    """Polls until the runner loop has applied commands and ticks (at most 2 s)."""
    deadline = time.monotonic() + 2
    while (status := client.get("/api/status").json()) != expected:
        assert time.monotonic() < deadline, f"status stayed {status}, expected {expected}"
        time.sleep(0.005)


def settle() -> None:
    """Leaves the runner loop time for several updates (one every 20 ms)."""
    time.sleep(0.1)


def test_app_starts_stopped_at_tick_zero():
    app, runner, clock = make_app()
    with TestClient(app) as client:
        assert app.state.runner is runner
        clock.now += 5
        settle()
        assert client.get("/api/status").json() == {"tick": 0, "time_s": 0.0, "running": False}


def test_start_pause_and_resume_through_the_websocket():
    app, _, clock = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text('{"type": "start"}')
        wait_for_status(client, {"tick": 0, "time_s": 0.0, "running": True})
        clock.now += 1
        wait_for_status(client, {"tick": 20, "time_s": 1.0, "running": True})

        ws.send_text('{"type": "pause"}')
        wait_for_status(client, {"tick": 20, "time_s": 1.0, "running": False})
        clock.now += 5
        settle()
        assert client.get("/api/status").json()["tick"] == 20

        # Resume is start while paused: time continues from the paused tick,
        # the 5 real seconds spent paused are not simulated.
        ws.send_text('{"type": "start"}')
        wait_for_status(client, {"tick": 20, "time_s": 1.0, "running": True})
        clock.now += 0.5
        wait_for_status(client, {"tick": 30, "time_s": 1.5, "running": True})


def test_repeated_commands_change_nothing():
    app, _, clock = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text('{"type": "pause"}')
        settle()
        assert client.get("/api/status").json()["running"] is False
        ws.send_text('{"type": "start"}')
        wait_for_status(client, {"tick": 0, "time_s": 0.0, "running": True})
        clock.now += 0.25
        wait_for_status(client, {"tick": 5, "time_s": 0.25, "running": True})
        ws.send_text('{"type": "start"}')
        settle()
        clock.now += 0.25
        wait_for_status(client, {"tick": 10, "time_s": 0.5, "running": True})


def test_invalid_command_gets_an_error_and_the_connection_stays_open():
    app, _, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text('{"type": "explode"}')
        reply = json.loads(ws.receive_text())
        assert reply["type"] == "error"
        assert reply["message"].startswith("Invalid command")
        assert "explode" in reply["message"]

        ws.send_text("not json")
        assert json.loads(ws.receive_text())["type"] == "error"

        ws.send_text('{"type": "start"}')
        wait_for_status(client, {"tick": 0, "time_s": 0.0, "running": True})


def test_binary_frames_are_accepted():
    app, _, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_bytes(b'{"type": "start"}')
        wait_for_status(client, {"tick": 0, "time_s": 0.0, "running": True})


def test_the_simulation_keeps_running_after_the_client_disconnects():
    app, _, clock = make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text('{"type": "start"}')
            wait_for_status(client, {"tick": 0, "time_s": 0.0, "running": True})
        clock.now += 1
        wait_for_status(client, {"tick": 20, "time_s": 1.0, "running": True})
