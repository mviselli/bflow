"""Owner of the server's engine: real-time clock and command queue.

A single Runner owns the Engine. Nobody else calls step() or changes the
engine: web handlers only put commands in the queue. At every update the
runner first applies all pending commands, then runs the ticks that real
time says are due, in a limited group, and returns control to the server.
"""

import asyncio
import time
from collections.abc import Callable

from bflow.core.engine import STEP_MS, Engine
from bflow.server.protocol import Command, PauseCommand, StartCommand


# Real seconds between two updates of the loop.
UPDATE_INTERVAL_S = 0.02
# At most 1 simulated second per update, so that commands stay responsive.
MAX_TICKS_PER_UPDATE = 20


class Runner:
    """Advances the engine at 1× real time while running.

    The clock is a function returning real seconds (time.monotonic by
    default): tests pass a fake clock and call update() directly, without
    waiting. The engine starts stopped at tick 0.
    """

    def __init__(self, engine: Engine | None = None, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.engine = engine if engine is not None else Engine()
        self.clock = clock
        self.commands: asyncio.Queue[Command] = asyncio.Queue()
        self.running = False
        # Real time and tick at which the current run started: the ticks due
        # are counted from here, without accumulating real time deltas.
        self._started_at = 0.0
        self._started_tick = 0

    def submit(self, command: Command) -> None:
        """Queues a validated command; it is applied at the start of the next update."""
        self.commands.put_nowait(command)

    def update(self) -> int:
        """Applies the pending commands, then runs the due ticks.

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
        due = self._started_tick + elapsed_ms // STEP_MS
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
        if isinstance(command, StartCommand) and not self.running:
            self.running = True
            self._restart_clock(now)
        elif isinstance(command, PauseCommand):
            self.running = False

    def _restart_clock(self, now: float) -> None:
        self._started_at = now
        self._started_tick = self.engine.tick
