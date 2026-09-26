"""FastAPI app: layout, snapshots and commands through the WebSocket, as a browser would.

The app runs its own runner loop in a background thread. Tests never call the
runner directly: they send commands, move the fake clock and wait until the
status or the snapshots show the expected state.
"""

import time

from fastapi.testclient import TestClient

from bflow.core.engine import Engine
from bflow.core.models import SimulationConfig
from bflow.server.app import SNAPSHOT_INTERVAL_S, create_app
from bflow.server.protocol import layout_message, snapshot_message
from bflow.server.runner import Runner


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make_app(engine: Engine | None = None):
    clock = FakeClock()
    runner = Runner(engine, clock=clock)
    return create_app(runner), runner, clock


def receive_until(ws, predicate, limit: int = 200) -> dict:
    """Reads messages until one satisfies predicate; snapshots keep arriving."""
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("no matching message received")


def is_snapshot(tick: int, running: bool):
    return lambda message: (message["type"] == "snapshot" and message["tick"] == tick
                            and message["running"] is running)


def is_error(message: dict) -> bool:
    return message["type"] == "error"


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
        reply = receive_until(ws, is_error)
        assert reply["type"] == "error"
        assert reply["message"].startswith("Invalid command")
        assert "explode" in reply["message"]

        ws.send_text("not json")
        receive_until(ws, is_error)

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


# Layout and snapshots


def test_layout_then_full_snapshot_on_connection():
    app, _, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == layout_message(Engine()).model_dump(mode="json")
        assert ws.receive_json() == snapshot_message(Engine(), running=False).model_dump(mode="json")


def test_snapshots_follow_start_pause_and_resume():
    app, _, clock = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text('{"type": "start"}')
        receive_until(ws, is_snapshot(0, True))
        # One second at a time: a larger jump would exceed the per-update
        # tick limit and the runner would drop the backlog.
        for tick in (20, 40, 60):
            clock.now += 1
            snapshot = receive_until(ws, is_snapshot(tick, True))
        # The first bag arrives at 2 s: the same state as an engine stepped
        # directly, bags and counters included.
        engine = Engine()
        for _ in range(60):
            engine.step()
        assert snapshot == snapshot_message(engine, running=True).model_dump(mode="json")
        assert snapshot["baggage"]

        ws.send_text('{"type": "pause"}')
        receive_until(ws, is_snapshot(60, False))
        clock.now += 5
        # Snapshots keep arriving while paused, with frozen time.
        for _ in range(3):
            assert is_snapshot(60, False)(ws.receive_json())

        ws.send_text('{"type": "start"}')
        # Wait until the runner has resumed before moving the clock.
        receive_until(ws, is_snapshot(60, True))
        clock.now += 0.5
        receive_until(ws, is_snapshot(70, True))


def test_each_event_is_sent_once_per_connection():
    # Arrivals faster than the belt can admit start an entrance queue event.
    app, _, clock = make_app(Engine(SimulationConfig(arrival_rate_bags_s=5.0)))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text('{"type": "start"}')
            received = []
            for _ in range(30):
                clock.now += 0.25
                message = receive_until(ws, lambda m: m["type"] == "snapshot")
                received += [event["id"] for event in message["events"]]
            assert received
            assert received == list(range(1, len(received) + 1))

        # A new connection receives the retained events again, as full state.
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # layout
            first = ws.receive_json()
            assert [event["id"] for event in first["events"]][:len(received)] == received


def test_snapshots_arrive_at_about_twelve_per_second():
    assert 1 / 15 <= SNAPSHOT_INTERVAL_S <= 1 / 10
    app, _, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()  # layout
        ws.receive_json()  # immediate snapshot
        started = time.monotonic()
        for _ in range(6):
            assert ws.receive_json()["type"] == "snapshot"
        elapsed = time.monotonic() - started
        # Six intervals of 1/12 s are 0.5 s; loose bounds for a busy machine.
        assert 0.4 <= elapsed <= 1.0
