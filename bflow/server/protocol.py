"""Messages exchanged with the browser, validated with Pydantic.

Every message is a JSON object with a ``type`` field. The server sends:

- ``layout``: the route configuration, once on connection;
- ``snapshot``: the simulated state, several times per real second;
- ``error``: a rejected command.

The browser sends commands (``start``, ``pause``). parse_command() accepts
only known commands with exactly their fields; anything else raises
pydantic.ValidationError before reaching the runner.

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


class ConveyorInfo(Message):
    id: str = Field(min_length=1)
    length_m: float = Field(gt=0)
    speed_m_s: float = Field(gt=0)


class LayoutMessage(TimedMessage):
    """Static description of the route, sent once on connection."""

    type: Literal["layout"] = "layout"
    step_ms: int = Field(gt=0)
    input_id: str = Field(min_length=1)
    output_id: str = Field(min_length=1)
    conveyors: list[ConveyorInfo]
    baggage_length_m: float = Field(gt=0)
    min_gap_m: float = Field(ge=0)


class BaggageState(Message):
    """A bag on a belt; position_m is its rear edge, as in the engine."""

    id: str = Field(min_length=1)
    destination_id: str = Field(min_length=1)
    conveyor_id: str = Field(min_length=1)
    position_m: float = Field(ge=0)
    length_m: float = Field(gt=0)


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
    running: bool
    baggage: list[BaggageState]
    stats: StatsState
    events: list[EventState]


class ErrorMessage(Message):
    type: Literal["error"] = "error"
    message: str


def layout_message(engine: Engine) -> LayoutMessage:
    config = engine.config
    return LayoutMessage(
        tick=engine.tick,
        time_s=engine.time_s,
        step_ms=STEP_MS,
        input_id=config.input_id,
        output_id=config.output_id,
        conveyors=[ConveyorInfo.model_validate(config.conveyor, from_attributes=True)],
        baggage_length_m=config.baggage_length_m,
        min_gap_m=config.min_gap_m,
    )


def snapshot_message(engine: Engine, *, running: bool, after_event_id: int = 0) -> SnapshotMessage:
    """Builds the snapshot; events are those with an id greater than after_event_id."""
    return SnapshotMessage(
        tick=engine.tick,
        time_s=engine.time_s,
        running=running,
        baggage=[BaggageState.model_validate(baggage, from_attributes=True)
                 for baggage in engine.conveyor.baggage],
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


Command = Annotated[StartCommand | PauseCommand, Field(discriminator="type")]
_command_adapter: TypeAdapter[Command] = TypeAdapter(Command)


def parse_command(raw: str | bytes) -> Command:
    """Validates a JSON command from the browser; raises pydantic.ValidationError."""
    return _command_adapter.validate_json(raw)
