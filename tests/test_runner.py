"""Server runner: owns the engine, queues commands, paces ticks by real time."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from bflow.core.engine import Engine
from bflow.server import runner as runner_module
from bflow.server.app import create_app
from bflow.server.protocol import PauseCommand, StartCommand
from bflow.server.runner import MAX_TICKS_PER_UPDATE, Runner


START = StartCommand(type="start")
PAUSE = PauseCommand(type="pause")


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make_runner() -> tuple[Runner, FakeClock]:
    clock = FakeClock()
    return Runner(clock=clock), clock


def test_runner_starts_stopped_at_tick_zero():
    runner, clock = make_runner()
    clock.now += 5
    assert runner.update() == 0
    assert runner.engine.tick == 0
    assert not runner.running


def test_submit_only_queues_the_command():
    runner, _ = make_runner()
    runner.submit(START)
    assert not runner.running
    assert runner.commands.qsize() == 1
    runner.update()
    assert runner.running
    assert runner.commands.empty()


def test_ticks_follow_real_time_at_exact_thresholds():
    runner, clock = make_runner()
    runner.submit(START)
    runner.update()
    clock.now += 0.049
    assert runner.update() == 0
    clock.now += 0.001
    assert runner.update() == 1
    clock.now += 0.5
    assert runner.update() == 10
    assert runner.engine.tick == 11


def test_long_gap_runs_a_limited_group_and_drops_the_backlog():
    runner, clock = make_runner()
    runner.submit(START)
    runner.update()
    clock.now += 60
    assert runner.update() == MAX_TICKS_PER_UPDATE
    # The dropped backlog is not caught up later: time restarts from here.
    assert runner.update() == 0
    clock.now += 0.1
    assert runner.update() == 2
    assert runner.engine.tick == MAX_TICKS_PER_UPDATE + 2


def test_commands_are_applied_while_paused_and_pause_freezes_time():
    runner, clock = make_runner()
    runner.submit(START)
    runner.update()
    clock.now += 1
    runner.update()
    runner.submit(PAUSE)
    clock.now += 1
    assert runner.update() == 0
    assert runner.engine.tick == 20
    clock.now += 30
    runner.submit(START)
    runner.update()
    clock.now += 0.25
    assert runner.update() == 5
    assert runner.engine.tick == 25


def test_repeated_start_does_not_restart_the_clock():
    runner, clock = make_runner()
    runner.submit(START)
    runner.update()
    clock.now += 0.03
    runner.submit(START)
    runner.update()
    clock.now += 0.02
    assert runner.update() == 1


def test_commands_are_applied_in_order_before_the_ticks():
    runner, clock = make_runner()
    runner.submit(START)
    runner.update()
    clock.now += 0.5
    runner.submit(PAUSE)
    assert runner.update() == 0
    assert runner.engine.tick == 0


def test_runner_matches_an_engine_stepped_directly():
    runner, clock = make_runner()
    runner.submit(START)
    runner.update()
    for _ in range(600):
        clock.now += 0.05
        runner.update()
    engine = Engine()
    for _ in range(600):
        engine.step()
    assert runner.engine.stats() == engine.stats()


def test_run_loop_advances_the_engine_in_real_time(monkeypatch):
    monkeypatch.setattr(runner_module, "UPDATE_INTERVAL_S", 0.001)

    async def scenario():
        runner, clock = make_runner()
        task = asyncio.create_task(runner.run())
        runner.submit(START)
        await asyncio.sleep(0.01)
        clock.now += 0.1
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return runner.engine.tick

    assert asyncio.run(scenario()) == 2


def test_app_starts_the_runner_and_reports_status():
    runner, clock = make_runner()
    app = create_app(runner)
    with TestClient(app) as client:
        assert app.state.runner is runner
        assert client.get("/api/status").json() == {
            "tick": 0, "time_s": 0.0, "running": False,
        }
        runner.submit(START)
        runner.update()
        clock.now += 1
        runner.update()
        assert client.get("/api/status").json() == {
            "tick": 20, "time_s": 1.0, "running": True,
        }
