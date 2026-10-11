"""Ready-made runs of the demo plant: a layout, a seed and timed actions.

A scenario is fully reproducible: the same scenario and the same operator
commands at the same ticks give the same run, in the CLI, the server and
the tests. Its actions are part of the run, like the layout's rates: the
engine applies each one at the start of the step that follows its tick,
exactly as if the operator had sent it then (see Engine.step).

- normal: the demo plant as configured, demand below the line's capacity.
- peak: every desk doubles its rate from 60 s to 180 s, above what the
  sort line can carry; queues grow, then clear once the rates come back.
- fault: line 2 breaks down at 60 s and stays faulty until the operator
  repairs it; the whole plant backs up behind it.
"""

from dataclasses import dataclass

from bflow.core.checks import check_identifier, check_quantity
from bflow.core.layout import LayoutConfig, default_layout


# Actions a scenario can schedule: engine method → what its target is.
BELT_ACTIONS = ("stop_belt", "restart_belt", "fault_belt", "repair_belt")
INPUT_ACTIONS = ("set_arrival_rate",)

# Rate of every desk during the peak: twice the demo plant's 0.15 bags/s,
# 1.8 bags/s in all against the 1.25 bags/s the sort line can carry.
PEAK_RATE_BAGS_S = 0.3


@dataclass(frozen=True)
class ScheduledAction:
    """An engine command applied after ``tick`` steps, before the next one.

    ``action`` is the name of the engine method; ``target_id`` the belt or
    input it acts on; ``value`` the new rate, only for set_arrival_rate.
    """

    tick: int
    action: str
    target_id: str
    value: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.tick, bool) or not isinstance(self.tick, int) or self.tick < 0:
            raise ValueError("tick must be a non-negative integer")
        if self.action not in BELT_ACTIONS + INPUT_ACTIONS:
            raise ValueError(f"Unknown scheduled action: {self.action!r}")
        check_identifier("target_id", self.target_id)
        if self.action in INPUT_ACTIONS:
            if self.value is None:
                raise ValueError(f"{self.action} needs a value")
            check_quantity("value", self.value)
        elif self.value is not None:
            raise ValueError(f"{self.action} takes no value")


@dataclass(frozen=True)
class Scenario:
    """A named run: the plant, the seed and the actions at known ticks."""

    id: str
    title: str
    description: str
    layout: LayoutConfig
    seed: int
    actions: tuple[ScheduledAction, ...] = ()

    def __post_init__(self) -> None:
        check_identifier("id", self.id)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        check_actions(self.layout, self.actions)


def check_actions(layout: LayoutConfig, actions: tuple[ScheduledAction, ...]) -> None:
    """Rejects actions on belts or inputs that are not in the layout.

    Checked before the run, so that a scenario cannot fail halfway through.
    """
    belt_ids = {belt.id for belt in layout.belts}
    input_ids = {node.id for node in layout.inputs}
    for action in actions:
        known = belt_ids if action.action in BELT_ACTIONS else input_ids
        if action.target_id not in known:
            raise ValueError(f"{action.action} at tick {action.tick}: "
                             f"unknown id {action.target_id!r}")


def normal_scenario() -> Scenario:
    return Scenario(
        "normal", "Normal traffic",
        "Each desk checks in 0.15 bags/s, below what the sort line can carry: "
        "no queues and no warnings.",
        default_layout(), seed=42)


def peak_scenario() -> Scenario:
    layout = default_layout()
    # From 60 s every desk at the peak rate, from 180 s back to its own rate.
    peak = tuple(ScheduledAction(1200, "set_arrival_rate", node.id, PEAK_RATE_BAGS_S)
                 for node in layout.inputs)
    back = tuple(ScheduledAction(3600, "set_arrival_rate", node.id, node.arrival_rate_bags_s)
                 for node in layout.inputs)
    return Scenario(
        "peak", "Peak traffic",
        f"From 60 s to 180 s every desk checks in {PEAK_RATE_BAGS_S:g} bags/s, more than "
        "the sort line can carry: queues grow at the desks farthest from the line, "
        "then clear once the rates come back to normal.",
        layout, seed=42, actions=peak + back)


def fault_scenario() -> Scenario:
    return Scenario(
        "fault", "Belt fault",
        "Normal traffic until line 2 breaks down at 60 s. It stays faulty until "
        "the operator repairs it, and the whole plant backs up behind it.",
        default_layout(), seed=42, actions=(ScheduledAction(1200, "fault_belt", "line-2"),))


# The scenarios in the order they are offered; the first is the default.
SCENARIOS = {scenario.id: scenario
             for scenario in (normal_scenario(), peak_scenario(), fault_scenario())}
