"""Owner of the server's engine: real-time clock and command queue.

A single Runner owns the Engine. Nobody else calls step() or changes the
engine: web handlers only put commands in the queue. At every update the
runner first applies all pending commands, then runs the ticks that real
time says are due, in a limited group, and returns control to the server.
The speed multiplies the ticks due per real second; reset replaces the
engine with a new one built from the same layout and seed.

Every applied command is recorded with the tick it was applied at: it takes
effect from the next step, tick + 1. Replaying the recorded commands at the
same ticks on a new engine with the same layout and seed gives the same run,
whatever the speed or real timing (apply_to_engine is the shared part).
Each reset starts a new run (runs are numbered from 1) whose record begins
with the reset itself, at tick 0.
"""

import asyncio
import time
from collections import deque
from collections.abc import Callable

from bflow.core.engine import STEP_MS, Engine
from bflow.core.layout import default_layout
from bflow.server.protocol import (
    BELT_COMMANDS, AcknowledgeAlarmCommand, Command, CommandRecord, FaultBeltCommand, ForceMissortCommand, PauseCommand,
    RepairBeltCommand, ResetCommand, RestartBeltCommand, SetMissortProbabilityCommand,
    SetRateCommand, SetSpeedCommand, StartCommand, StopBeltCommand,
)


# Real seconds between two updates of the loop.
UPDATE_INTERVAL_S = 0.02
# At most 1 simulated second per update, so that commands stay responsive
# (at 5× an update normally runs about 2 ticks).
MAX_TICKS_PER_UPDATE = 20
# The record keeps at most this many commands per run, the newest ones:
# far more than an operator sends, but a bound against a flooding client.
MAX_RECORDED_COMMANDS = 10_000


class Runner:
    """Advances the engine at 1×, 2× or 5× real time while running.

    The clock is a function returning real seconds (time.monotonic by
    default): tests pass a fake clock and call update() directly, without
    waiting. Without an engine it runs the full plant (default_layout()),
    starting stopped at tick 0.
    """

    def __init__(self, engine: Engine | None = None, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.engine = engine if engine is not None else Engine(default_layout())
        self.clock = clock
        self.commands: asyncio.Queue[Command] = asyncio.Queue()
        self.running = False
        self.speed = 1
        # Number of the current run: 1 at start, +1 at every reset, so that
        # readers can tell a new run from the old one even at the same tick.
        self.run_number = 1
        # Commands applied in the current run, oldest first.
        self.record: deque[CommandRecord] = deque(maxlen=MAX_RECORDED_COMMANDS)
        # Real time and tick at which the current run started: the ticks due
        # are counted from here, without accumulating real time deltas.
        self._started_at = 0.0
        self._started_tick = 0

    def submit(self, command: Command) -> None:
        """Queues a validated command; it is applied at the start of the next update.

        Raises ValueError for a belt or input that is not in the plant, or
        an alarm the engine has not raised, so the sender can be told at
        once. The layout never changes, not even on reset, so the check
        stays valid until the command is applied; alarms start over at a
        reset (see _apply).
        """
        layout = self.engine.layout
        if isinstance(command, BELT_COMMANDS):
            if command.belt_id not in {belt.id for belt in layout.belts}:
                raise ValueError(f"Unknown belt: {command.belt_id}")
        elif isinstance(command, SetRateCommand):
            if command.input_id not in {node.id for node in layout.inputs}:
                raise ValueError(f"Unknown input: {command.input_id}")
        elif isinstance(command, AcknowledgeAlarmCommand):
            if command.alarm_id > self.engine.last_alarm_id:
                raise ValueError(f"Unknown alarm: {command.alarm_id}")
        self.commands.put_nowait(command)

    def update(self) -> int:
        """Applies and records the pending commands, then runs the due ticks.

        Commands are applied even while paused. Returns the number of ticks
        run. If the ticks due exceed MAX_TICKS_PER_UPDATE (a slow machine or
        a long blocking call) the backlog is dropped: the simulation slows
        down instead of catching up in a burst.
        """
        now = self.clock()
        while not self.commands.empty():
            self._apply(self.commands.get_nowait(), now)
        if not self.running:
            return 0
        # Whole milliseconds: 100.1 - 100.0 gives 0.0999..., which must not lose a tick.
        elapsed_ms = round((now - self._started_at) * 1000)
        due = self._started_tick + elapsed_ms * self.speed // STEP_MS
        count = min(due - self.engine.tick, MAX_TICKS_PER_UPDATE)
        for _ in range(count):
            self.engine.step()
        if due > self.engine.tick:
            self._restart_clock(now)
        return count

    async def run(self) -> None:
        """Updates forever at a fixed real interval; cancel the task to stop."""
        while True:
            self.update()
            await asyncio.sleep(UPDATE_INTERVAL_S)

    def _apply(self, command: Command, now: float) -> None:
        """Start also resumes after a pause; repeated commands change nothing.

        Resuming and changing speed restart the real-time reference, so the
        real time spent paused is never simulated afterwards and a new speed
        applies only from now. Reset keeps the speed and leaves the new
        engine paused at tick 0, in a new run whose record starts with the
        reset itself. An acknowledgement checked against the old engine but
        queued behind a reset names an alarm of the old run: the new engine
        has raised none yet, so it is dropped unrecorded.
        """
        if (isinstance(command, AcknowledgeAlarmCommand)
                and command.alarm_id > self.engine.last_alarm_id):
            return
        if isinstance(command, ResetCommand):
            self.engine = Engine(self.engine.layout, seed=self.engine.seed)
            self.running = False
            self.run_number += 1
            self.record.clear()
        self.record.append(CommandRecord(tick=self.engine.tick, time_s=self.engine.time_s,
                                         command=command))
        if isinstance(command, StartCommand) and not self.running:
            self.running = True
            self._restart_clock(now)
        elif isinstance(command, PauseCommand):
            self.running = False
        elif isinstance(command, SetSpeedCommand) and command.speed != self.speed:
            self.speed = command.speed
            self._restart_clock(now)
        else:
            apply_to_engine(self.engine, command)

    def _restart_clock(self, now: float) -> None:
        self._started_at = now
        self._started_tick = self.engine.tick


def apply_to_engine(engine: Engine, command: Command) -> None:
    """Applies a command that changes the simulated plant; ignores the others.

    Start, pause, speed and reset only decide which ticks run and when, so
    a replay of a recorded run needs just this function and the ticks.
    """
    if isinstance(command, StopBeltCommand):
        engine.stop_belt(command.belt_id)
    elif isinstance(command, RestartBeltCommand):
        engine.restart_belt(command.belt_id)
    elif isinstance(command, FaultBeltCommand):
        engine.fault_belt(command.belt_id)
    elif isinstance(command, RepairBeltCommand):
        engine.repair_belt(command.belt_id)
    elif isinstance(command, SetRateCommand):
        engine.set_arrival_rate(command.input_id, command.rate_bags_s)
    elif isinstance(command, SetMissortProbabilityCommand):
        engine.set_missort_probability(command.probability)
    elif isinstance(command, ForceMissortCommand):
        engine.force_missort()
    elif isinstance(command, AcknowledgeAlarmCommand):
        engine.acknowledge_alarm(command.alarm_id)
