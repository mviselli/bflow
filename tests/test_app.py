"""FastAPI app: layout, snapshots and commands through the WebSocket, as a browser would.

The app runs its own runner loop in a background thread. Tests never call the
runner directly: they send commands, move the fake clock and wait until the
status or the snapshots show the expected state.
"""

import time

from fastapi.testclient import TestClient

from bflow.core.engine import Engine
from bflow.core.layout import default_layout, minimal_layout
from bflow.server.app import FRONTEND_DIST, SNAPSHOT_INTERVAL_S, create_app
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
    """Polls until the runner loop has applied commands and ticks (at most 2 s).

    Only the keys in expected are compared.
    """
    deadline = time.monotonic() + 2
    while True:
        status = client.get("/api/status").json()
        if {key: status[key] for key in expected} == expected:
            return
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
        assert client.get("/api/status").json() == {
            "tick": 0, "time_s": 0.0, "running": False, "speed": 1, "run": 1}


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
    # The default server runs the full plant.
    app, _, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        plant = Engine(default_layout())
        assert ws.receive_json() == layout_message(plant).model_dump(mode="json")
        assert ws.receive_json() == snapshot_message(plant, running=False).model_dump(mode="json")


def test_snapshots_follow_start_pause_and_resume():
    app, _, clock = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text('{"type": "start"}')
        receive_until(ws, is_snapshot(0, True))
        # One second at a time: a larger jump would exceed the per-update
        # tick limit and the runner would drop the backlog.
        for tick in range(20, 160, 20):
            clock.now += 1
            snapshot = receive_until(ws, is_snapshot(tick, True))
        # The first bags arrive at 6.67 s: the same state as an engine stepped
        # directly, bags and counters included.
        engine = Engine(default_layout())
        for _ in range(140):
            engine.step()
        assert snapshot == snapshot_message(engine, running=True).model_dump(mode="json")
        assert snapshot["baggage"]

        ws.send_text('{"type": "pause"}')
        receive_until(ws, is_snapshot(140, False))
        clock.now += 5
        # Snapshots keep arriving while paused, with frozen time.
        for _ in range(3):
            assert is_snapshot(140, False)(ws.receive_json())

        ws.send_text('{"type": "start"}')
        # Wait until the runner has resumed before moving the clock.
        receive_until(ws, is_snapshot(140, True))
        clock.now += 0.5
        receive_until(ws, is_snapshot(150, True))


def test_each_event_is_sent_once_per_connection():
    # Arrivals faster than the belt can admit start an entrance queue event.
    app, _, clock = make_app(Engine(minimal_layout(arrival_rate_bags_s=5.0)))
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


def test_a_belt_not_in_the_plant_gets_an_error_and_a_real_one_stops():
    app, runner, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text('{"type": "stop_belt", "belt_id": "belt-x"}')
        reply = receive_until(ws, is_error)
        assert reply["message"] == "Invalid command: Unknown belt: belt-x"
        ws.send_text('{"type": "stop_belt", "belt_id": "line-2"}')
        stopped = receive_until(ws, lambda m: m["type"] == "snapshot" and any(
            belt["id"] == "line-2" and belt["stopped"] for belt in m["belts"]))
        assert stopped["events"][-1]["kind"] == "belt_stopped"


def test_a_fault_reaches_the_snapshot_as_an_error_and_a_repair_clears_it():
    app, _, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text('{"type": "fault_belt", "belt_id": "branch-3"}')
        faulty = receive_until(ws, lambda m: m["type"] == "snapshot" and any(
            belt["id"] == "branch-3" and belt["faulty"] for belt in m["belts"]))
        assert faulty["events"][-1]["kind"] == "belt_fault"
        assert faulty["stats"]["errors"] == 1
        ws.send_text('{"type": "repair_belt", "belt_id": "branch-3"}')
        repaired = receive_until(ws, lambda m: m["type"] == "snapshot" and not any(
            belt["faulty"] for belt in m["belts"]))
        assert repaired["events"][-1]["kind"] == "belt_repaired"
        assert repaired["stats"]["errors"] == 1


def test_a_forced_wrong_sorting_reaches_the_snapshot():
    app, _, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text('{"type": "set_missort_probability", "probability": 0.25}')
        ws.send_text('{"type": "force_missort"}')
        forced = receive_until(ws, lambda m: m["type"] == "snapshot" and m["missort_forced"])
        assert forced["missort_probability"] == 0.25
        assert [event["kind"] for event in forced["events"]][-2:] == [
            "missort_probability_changed", "missort_forced"]
        ws.send_text('{"type": "set_missort_probability", "probability": 2}')
        assert receive_until(ws, is_error)["message"].startswith("Invalid command")


def test_after_a_reset_the_new_engine_events_reach_an_open_connection():
    app, _, clock = make_app(Engine(minimal_layout(arrival_rate_bags_s=5.0)))
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text('{"type": "start"}')
        receive_until(ws, is_snapshot(0, True))
        clock.now += 1
        receive_until(ws, lambda m: m["type"] == "snapshot" and m["events"])
        ws.send_text('{"type": "reset"}')
        receive_until(ws, is_snapshot(0, False))
        ws.send_text('{"type": "start"}')
        receive_until(ws, is_snapshot(0, True))
        clock.now += 1
        # Event ids start again from 1 and the connection still sends them.
        after = receive_until(ws, lambda m: m["type"] == "snapshot" and m["events"])
        assert after["events"][0]["id"] == 1


def test_snapshots_carry_the_run_number_which_changes_at_every_reset():
    app, _, _ = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert receive_until(ws, is_snapshot(0, False))["run"] == 1
        # Still tick 0 and paused: only the run number tells the new run apart.
        ws.send_text('{"type": "reset"}')
        receive_until(ws, lambda m: m["type"] == "snapshot" and m["run"] == 2)
        wait_for_status(client, {"run": 2, "tick": 0})


def test_the_commands_of_the_current_run_can_be_read_with_their_ticks():
    app, _, clock = make_app()
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_text('{"type": "start"}')
        wait_for_status(client, {"running": True})
        clock.now += 0.5
        wait_for_status(client, {"tick": 10})
        ws.send_text('{"type": "stop_belt", "belt_id": "line-1"}')
        receive_until(ws, lambda m: m["type"] == "snapshot"
                      and any(belt["stopped"] for belt in m["belts"]))
        assert client.get("/api/commands").json() == [
            {"tick": 0, "time_s": 0.0, "command": {"type": "start"}},
            {"tick": 10, "time_s": 0.5, "command": {"type": "stop_belt", "belt_id": "line-1"}},
        ]
        ws.send_text('{"type": "reset"}')
        wait_for_status(client, {"run": 2})
        assert client.get("/api/commands").json() == [
            {"tick": 0, "time_s": 0.0, "command": {"type": "reset"}}]


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


# The built page


def fake_build(directory):
    """A minimal Vite build: index.html linking one hashed asset."""
    (directory / "assets").mkdir()
    (directory / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/index-abc123.js"></script>')
    (directory / "assets" / "index-abc123.js").write_text("console.log('page');")
    return directory


def test_the_built_page_and_its_assets_are_served_with_the_api(tmp_path):
    app = create_app(Runner(clock=FakeClock()), frontend_dir=fake_build(tmp_path))
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert page.headers["cache-control"] == "no-cache"
        assert "/assets/index-abc123.js" in page.text
        asset = client.get("/assets/index-abc123.js")
        assert asset.status_code == 200
        assert "javascript" in asset.headers["content-type"]
        assert client.get("/assets/missing.js").status_code == 404
        # The API and the WebSocket keep their paths.
        assert client.get("/api/status").json()["tick"] == 0
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "layout"


def test_without_a_build_the_page_says_how_to_build_it(tmp_path):
    app = create_app(Runner(clock=FakeClock()), frontend_dir=tmp_path / "dist")
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 503
        assert "npm --prefix frontend run build" in page.text
        assert client.get("/api/status").status_code == 200


def test_the_app_serves_the_frontend_build_folder_by_default():
    assert FRONTEND_DIST.parts[-2:] == ("frontend", "dist")
    assert (FRONTEND_DIST.parent / "index.html").is_file()
