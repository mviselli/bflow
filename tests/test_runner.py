"""Server runner: owns the engine, queues commands, paces ticks by real time."""

import asyncio

import pytest

from bflow.core.engine import Engine
from bflow.core.layout import default_layout
from bflow.server import runner as runner_module
from bflow.server.protocol import (
    FaultBeltCommand, PauseCommand, RepairBeltCommand, ResetCommand, RestartBeltCommand,
    SetRateCommand, SetSpeedCommand, StartCommand, StopBeltCommand,
)
from bflow.server.runner import MAX_RECORDED_COMMANDS, MAX_TICKS_PER_UPDATE, Runner, apply_to_engine


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


def test_neither_restart_nor_start_clears_a_fault_only_repair_does():
    runner, clock = make_runner()
    runner.submit(FaultBeltCommand(type="fault_belt", belt_id="line-1"))
    runner.submit(RestartBeltCommand(type="restart_belt", belt_id="line-1"))
    runner.submit(START)
    runner.submit(PAUSE)
    runner.submit(START)
    runner.update()
    clock.now += 1
    runner.update()
    assert runner.engine.conveyors["line-1"].faulty
    runner.submit(RepairBeltCommand(type="repair_belt", belt_id="line-1"))
    runner.update()
    assert not runner.engine.conveyors["line-1"].halted
    assert recorded(runner)[-1] == (20, "repair_belt")
    # A reset brings back the plant with no fault.
    runner.submit(FaultBeltCommand(type="fault_belt", belt_id="line-1"))
    runner.submit(ResetCommand(type="reset"))
    runner.update()
    assert not runner.engine.conveyors["line-1"].faulty


@pytest.mark.parametrize("command", [
    StopBeltCommand(type="stop_belt", belt_id="belt-x"),
    RestartBeltCommand(type="restart_belt", belt_id="input-a1"),
    FaultBeltCommand(type="fault_belt", belt_id="merge-main"),
    RepairBeltCommand(type="repair_belt", belt_id="output-1"),
    SetRateCommand(type="set_rate", input_id="line-1", rate_bags_s=0.1),
])
def test_commands_for_elements_not_in_the_plant_are_refused_at_once(command):
    runner, _ = make_runner()
    with pytest.raises(ValueError, match="Unknown"):
        runner.submit(command)
    assert runner.commands.empty()


def recorded(runner):
    return [(record.tick, record.command.type) for record in runner.record]


def test_each_applied_command_is_recorded_with_the_tick_it_was_applied_at():
    runner, clock = make_runner()
    stop = StopBeltCommand(type="stop_belt", belt_id="line-1")
    runner.submit(stop)  # while paused, at tick 0
    runner.submit(START)
    runner.update()
    assert recorded(runner) == [(0, "stop_belt"), (0, "start")]
    clock.now += 0.5  # 10 ticks
    runner.update()
    runner.submit(speed(5))
    runner.submit(START)  # already running: recorded, changes nothing
    runner.update()
    clock.now += 0.1  # 10 more ticks at 5×
    runner.update()
    runner.submit(PAUSE)
    runner.update()
    assert recorded(runner) == [(0, "stop_belt"), (0, "start"), (10, "set_speed"), (10, "start"),
                                (20, "pause")]
    assert runner.record[0].command == stop
    assert runner.record[-1].time_s == 1.0
    # Submitted but not yet applied: not in the record.
    runner.submit(START)
    assert len(runner.record) == 5


def test_reset_starts_a_new_run_whose_record_begins_with_the_reset():
    runner, clock = make_runner()
    assert runner.run_number == 1
    runner.submit(START)
    runner.update()
    clock.now += 1
    runner.update()
    runner.submit(ResetCommand(type="reset"))
    runner.submit(StopBeltCommand(type="stop_belt", belt_id="line-2"))
    runner.update()
    assert runner.run_number == 2
    assert recorded(runner) == [(0, "reset"), (0, "stop_belt")]
    assert runner.engine.conveyors["line-2"].stopped
    runner.submit(ResetCommand(type="reset"))
    runner.update()
    assert runner.run_number == 3
    assert recorded(runner) == [(0, "reset")]
    assert not runner.engine.conveyors["line-2"].stopped


def test_the_record_keeps_only_the_newest_commands():
    runner, _ = make_runner()
    for _ in range(MAX_RECORDED_COMMANDS + 5):
        runner.submit(PAUSE)
    runner.update()
    assert len(runner.record) == MAX_RECORDED_COMMANDS


def test_replaying_the_record_at_the_same_ticks_gives_the_same_run():
    # The operator acts at uneven real times, at 5×, pausing in between;
    # a new engine stepped directly with the recorded commands ends equal.
    runner, clock = make_runner()
    runner.submit(speed(5))
    runner.submit(START)
    runner.update()
    actions = [StopBeltCommand(type="stop_belt", belt_id="branch-1"),
               SetRateCommand(type="set_rate", input_id="input-b1", rate_bags_s=0.8),
               PAUSE,
               RestartBeltCommand(type="restart_belt", belt_id="branch-1"),
               START,
               FaultBeltCommand(type="fault_belt", belt_id="island-a-3"),
               RepairBeltCommand(type="repair_belt", belt_id="island-a-3"),
               SetRateCommand(type="set_rate", input_id="input-a2", rate_bags_s=0.0)]
    for step in range(500):
        clock.now += 0.013 + (step % 7) * 0.004
        if step % 60 == 30 and actions:
            runner.submit(actions.pop(0))
        runner.update()
    assert not actions

    replay = Engine(default_layout())
    commands = list(runner.record)
    while replay.tick < runner.engine.tick:
        while commands and commands[0].tick == replay.tick:
            apply_to_engine(replay, commands.pop(0).command)
        replay.step()
    assert not commands
    assert replay.stats() == runner.engine.stats()
    assert replay.events.counts == runner.engine.events.counts
    assert [(b.id, b.conveyor_id, b.position_m) for c in replay.conveyors.values() for b in c.baggage] \
        == [(b.id, b.conveyor_id, b.position_m) for c in runner.engine.conveyors.values() for b in c.baggage]
