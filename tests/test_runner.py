"""Server runner: owns the engine, queues commands, paces ticks by real time."""

import asyncio

import pytest

from bflow.core.engine import Engine
from bflow.core.layout import default_layout
from bflow.server import runner as runner_module
from bflow.server.protocol import (
    PauseCommand, ResetCommand, RestartBeltCommand, SetRateCommand, SetSpeedCommand, StartCommand,
    StopBeltCommand,
)
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


def test_runner_runs_the_full_plant_by_default():
    runner, _ = make_runner()
    assert runner.engine.layout == default_layout()


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
    engine = Engine(default_layout())
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


def speed(value):
    return SetSpeedCommand(type="set_speed", speed=value)


@pytest.mark.parametrize("factor", [1, 2, 5])
def test_speed_multiplies_the_ticks_per_real_second(factor):
    runner, clock = make_runner()
    runner.submit(speed(factor))
    runner.submit(START)
    runner.update()
    for _ in range(10):
        clock.now += 0.1
        runner.update()
    assert runner.engine.tick == 20 * factor


def test_a_new_speed_applies_from_the_moment_it_is_set():
    runner, clock = make_runner()
    runner.submit(START)
    runner.update()
    clock.now += 1
    runner.update()
    assert runner.engine.tick == 20
    runner.submit(speed(5))
    runner.update()
    for _ in range(5):  # 10 ticks per update, below MAX_TICKS_PER_UPDATE
        clock.now += 0.1
        runner.update()
    # 1 s at 1×, then 0.5 s at 5×: 20 + 50 ticks, none recounted at the new speed.
    assert runner.engine.tick == 70
    runner.submit(speed(5))  # the same speed again: nothing restarts
    clock.now += 0.02
    runner.update()
    assert runner.engine.tick == 72


def test_the_same_commands_give_the_same_run_at_any_speed():
    # Commands at the same ticks, but at different real times.
    results = []
    for factor in (1, 5):
        runner, clock = make_runner()
        runner.submit(speed(factor))
        runner.submit(START)
        runner.update()
        commands = {600: StopBeltCommand(type="stop_belt", belt_id="line-2"),
                    1200: RestartBeltCommand(type="restart_belt", belt_id="line-2"),
                    1500: SetRateCommand(type="set_rate", input_id="input-a1", rate_bags_s=0.5)}
        while runner.engine.tick < 2400:
            if runner.engine.tick in commands:
                runner.submit(commands.pop(runner.engine.tick))
            clock.now += 0.05 / factor  # one tick per update
            runner.update()
        engine = runner.engine
        results.append((engine.stats(), [(b.id, b.conveyor_id, b.position_m)
                                         for c in engine.conveyors.values() for b in c.baggage]))
    assert results[0] == results[1]


def test_reset_restores_a_fresh_paused_engine_with_the_same_layout_and_seed():
    runner, clock = make_runner()
    old = runner.engine
    runner.submit(START)
    runner.submit(SetRateCommand(type="set_rate", input_id="input-a1", rate_bags_s=1))
    runner.submit(StopBeltCommand(type="stop_belt", belt_id="line-1"))
    runner.update()
    clock.now += 1
    runner.update()
    runner.submit(speed(2))
    runner.submit(ResetCommand(type="reset"))
    runner.update()
    assert runner.engine is not old
    assert (runner.engine.tick, runner.running, runner.speed) == (0, False, 2)
    assert runner.engine.layout == old.layout and runner.engine.seed == old.seed
    assert runner.engine.arrival_rates["input-a1"] == 0.15
    assert not runner.engine.conveyors["line-1"].stopped
    # After reset it runs exactly like a new engine.
    runner.submit(START)
    runner.update()
    for _ in range(20):
        clock.now += 0.5
        runner.update()
    fresh = Engine(default_layout())
    for _ in range(runner.engine.tick):
        fresh.step()
    assert runner.engine.stats() == fresh.stats()


def test_belt_and_rate_commands_reach_the_engine():
    runner, _ = make_runner()
    runner.submit(StopBeltCommand(type="stop_belt", belt_id="branch-2"))
    runner.submit(SetRateCommand(type="set_rate", input_id="input-b3", rate_bags_s=0.4))
    runner.update()
    assert runner.engine.conveyors["branch-2"].stopped
    assert runner.engine.arrival_rates["input-b3"] == 0.4
    runner.submit(RestartBeltCommand(type="restart_belt", belt_id="branch-2"))
    runner.update()
    assert not runner.engine.conveyors["branch-2"].stopped


@pytest.mark.parametrize("command", [
    StopBeltCommand(type="stop_belt", belt_id="belt-x"),
    RestartBeltCommand(type="restart_belt", belt_id="input-a1"),
    SetRateCommand(type="set_rate", input_id="line-1", rate_bags_s=0.1),
])
def test_commands_for_elements_not_in_the_plant_are_refused_at_once(command):
    runner, _ = make_runner()
    with pytest.raises(ValueError, match="Unknown"):
        runner.submit(command)
    assert runner.commands.empty()
