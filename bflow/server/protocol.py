"""Messages exchanged with the browser, validated with Pydantic.

Every message is a JSON object with a ``type`` field. The server sends:

- ``layout``: the plant (nodes, belts and their map coordinates), once
  on connection;
- ``snapshot``: the simulated state, several times per real second;
- ``error``: a rejected command.

The browser sends commands: ``start``, ``pause``, ``reset``, ``set_speed``,
``set_rate``, ``stop_belt`` and ``restart_belt``. parse_command() accepts
only known commands with exactly their fields and values in range; anything
else raises pydantic.ValidationError before reaching the runner, which then
checks that the belt or input exists. The runner records each applied
command as a ``CommandRecord`` with the tick it was applied at.

Layout and snapshot carry the tick and simulated time they describe. The two
must agree (time_s = tick × 50 ms): a message cannot mix different instants.
Units are those of the engine: metres, m/s, simulated seconds.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from bflow.core.engine import STEP_MS, Engine
from bflow.core.events import Severity


class Message(BaseModel):
    """Common rules: unknown fields, NaN and infinity are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class TimedMessage(Message):
    """A message that describes the simulation at a given tick."""

    tick: int = Field(ge=0)
    time_s: float = Field(ge=0)

    @model_validator(mode="after")
    def _time_matches_tick(self):
        if self.time_s != self.tick * STEP_MS / 1000:
            raise ValueError("time_s must equal tick × step duration")
        return self


# Server → browser


class PointInfo(Message):
    """A point on the map, in metres; y grows downwards."""

    x_m: float
    y_m: float


class NodeInfo(Message):
    """A merge or a sorter: where belts join or split."""

    id: str = Field(min_length=1)
    position: PointInfo


class LabelledNodeInfo(NodeInfo):
    """An input (check-in desk letter) or an output (demo flight code)."""

    label: str = Field(min_length=1)


class BeltInfo(Message):
    """A straight belt; position 0 is at ``start`` and ``length_m`` at ``end``."""

    id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    start: PointInfo
    end: PointInfo
    length_m: float = Field(gt=0)
    speed_m_s: float = Field(gt=0)


class LayoutMessage(TimedMessage):
    """Static description of the plant, sent once on connection.

    Elements are in layout order, as in the engine.
    """

    type: Literal["layout"] = "layout"
    step_ms: int = Field(gt=0)
    inputs: list[LabelledNodeInfo]
    merges: list[NodeInfo]
    sorters: list[NodeInfo]
    outputs: list[LabelledNodeInfo]
    belts: list[BeltInfo]
    baggage_length_m: float = Field(gt=0)
    min_gap_m: float = Field(ge=0)


class BaggageState(Message):
    """A bag on a belt; position_m is its rear edge, as in the engine.

    entered_at_s is the simulated time of its admission: the bag's travel
    time so far is the snapshot's time_s minus it.
    """

    id: str = Field(min_length=1)
    destination_id: str = Field(min_length=1)
    conveyor_id: str = Field(min_length=1)
    position_m: float = Field(ge=0)
    length_m: float = Field(gt=0)
    entered_at_s: float = Field(ge=0)


class InputState(Message):
    """An input's current arrival rate, which the operator can change."""

    id: str = Field(min_length=1)
    arrival_rate_bags_s: float = Field(ge=0)


class BeltState(Message):
    """The operator's local stop of one belt (not the global pause)."""

    id: str = Field(min_length=1)
    stopped: bool


class BeltStatsState(Message):
    """Bags on one belt against the most it can hold, as the engine counts them."""

    belt_id: str = Field(min_length=1)
    bags: int = Field(ge=0)
    capacity: int = Field(ge=1)
    occupancy: float = Field(ge=0)


class InputStatsState(Message):
    """Bags generated at one input and still waiting to be admitted."""

    input_id: str = Field(min_length=1)
    waiting: int = Field(ge=0)


class StatsState(Message):
    """Counters computed by the engine; the browser displays them as they are."""

    generated: int = Field(ge=0)
    waiting: int = Field(ge=0)
    admitted: int = Field(ge=0)
    correctly_delivered: int = Field(ge=0)
    misdelivered: int = Field(ge=0)
    in_transit: int = Field(ge=0)
    mean_travel_time_s: float | None = Field(ge=0)
    errors: int = Field(ge=0)
    warnings: int = Field(ge=0)
    # One entry per belt and per input, in layout order.
    belts: list[BeltStatsState]
    inputs: list[InputStatsState]


class EventState(TimedMessage):
    id: int = Field(ge=1)
    severity: Severity
    kind: str = Field(min_length=1)
    message: str
    element_id: str | None
    baggage_id: str | None


class SnapshotMessage(TimedMessage):
    """Simulated state at one tick, with only the events the reader has not seen."""

    type: Literal["snapshot"] = "snapshot"
    # 1 for the first run, +1 at every reset: a new number means the bags,
    # events and times belong to a new run, even if the tick did not go back.
    run: int = Field(ge=1)
    running: bool
    # Simulated seconds per real second: 1, 2 or 5.
    speed: int = Field(ge=1)
    # One entry per input and per belt, in layout order.
    inputs: list[InputState]
    belts: list[BeltState]
    baggage: list[BaggageState]
    stats: StatsState
    events: list[EventState]


class ErrorMessage(Message):
    type: Literal["error"] = "error"
    message: str


def layout_message(engine: Engine) -> LayoutMessage:
    """Describes the engine's plant, copied from its layout configuration."""
    layout = engine.layout

    def copy(model, elements):
        return [model.model_validate(element, from_attributes=True) for element in elements]

    return LayoutMessage(
        tick=engine.tick,
        time_s=engine.time_s,
        step_ms=STEP_MS,
        inputs=copy(LabelledNodeInfo, layout.inputs),
        merges=copy(NodeInfo, layout.merges),
        sorters=copy(NodeInfo, layout.sorters),
        outputs=copy(LabelledNodeInfo, layout.outputs),
        belts=copy(BeltInfo, layout.belts),
        baggage_length_m=layout.baggage_length_m,
        min_gap_m=layout.min_gap_m,
    )


def snapshot_message(engine: Engine, *, running: bool, speed: int = 1, run: int = 1,
                     after_event_id: int = 0) -> SnapshotMessage:
    """Builds the snapshot; events are those with an id greater than after_event_id."""
    return SnapshotMessage(
        tick=engine.tick,
        time_s=engine.time_s,
        run=run,
        running=running,
        speed=speed,
        inputs=[InputState(id=input_id, arrival_rate_bags_s=rate)
                for input_id, rate in engine.arrival_rates.items()],
        belts=[BeltState(id=belt_id, stopped=conveyor.stopped)
               for belt_id, conveyor in engine.conveyors.items()],
        baggage=[BaggageState.model_validate(baggage, from_attributes=True)
                 for conveyor in engine.conveyors.values() for baggage in conveyor.baggage],
        stats=StatsState.model_validate(engine.stats(), from_attributes=True),
        events=[EventState.model_validate(event, from_attributes=True)
                for event in engine.events.since(after_event_id)],
    )


# Browser → server


class StartCommand(Message):
    """Starts or resumes the simulation."""

    type: Literal["start"]


class PauseCommand(Message):
    """Freezes simulated time; commands are still applied."""

    type: Literal["pause"]


class ResetCommand(Message):
    """Restores the initial plant, rates and seed, paused at tick 0."""

    type: Literal["reset"]


# Simulation speeds offered to the operator: simulated seconds per real second.
SPEEDS = (1, 2, 5)
# Highest arrival rate an operator can set on one input, in bags per second.
MAX_RATE_BAGS_S = 1.0


class SetSpeedCommand(Message):
    """Runs more steps per real second; the step itself stays 50 ms."""

    type: Literal["set_speed"]
    speed: Literal[SPEEDS]


class SetRateCommand(Message):
    """Changes the arrival rate of one input."""

    type: Literal["set_rate"]
    input_id: str = Field(min_length=1)
    rate_bags_s: float = Field(ge=0, le=MAX_RATE_BAGS_S)


class StopBeltCommand(Message):
    """The operator's local stop of one belt."""

    type: Literal["stop_belt"]
    belt_id: str = Field(min_length=1)


class RestartBeltCommand(Message):
    """Restarts a belt stopped by the operator."""

    type: Literal["restart_belt"]
    belt_id: str = Field(min_length=1)


Command = Annotated[
    StartCommand | PauseCommand | ResetCommand | SetSpeedCommand | SetRateCommand
    | StopBeltCommand | RestartBeltCommand,
    Field(discriminator="type"),
]
_command_adapter: TypeAdapter[Command] = TypeAdapter(Command)


class CommandRecord(TimedMessage):
    """A command as the runner applied it, between ``tick`` and the next step."""

    command: Command


def parse_command(raw: str | bytes) -> Command:
    """Validates a JSON command from the browser; raises pydantic.ValidationError."""
    return _command_adapter.validate_json(raw)
