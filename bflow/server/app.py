"""FastAPI application: starts the runner with the server and stops it on exit.

    uv run uvicorn bflow.server.app:app

Handlers never call Engine.step(): they read the state or hand commands to
the runner, which applies them in its own loop.

The browser talks to the server over the WebSocket at /ws. On connection
the server sends the ``layout`` once, then a ``snapshot`` immediately and
about every SNAPSHOT_INTERVAL_S real seconds, while running or paused. Each
connection remembers the last event it sent, so a snapshot carries only new
events; a new connection receives the full current state and the recent
events. Snapshots are built on the same event loop as the runner, whose
updates never yield midway, so they never show a half-applied group of ticks.

At the same time the browser sends commands as JSON. A command is
validated, then queued: it takes effect at the runner's next update, even
while the simulation is paused. An invalid command gets an ``error`` message
back and the connection stays open.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from bflow.server.protocol import ErrorMessage, layout_message, parse_command, snapshot_message
from bflow.server.runner import Runner


# About 12 snapshots per real second, within the 10–15 Hz target.
SNAPSHOT_INTERVAL_S = 1 / 12


def create_app(runner: Runner | None = None) -> FastAPI:
    """Builds the app around a runner; tests can pass their own."""
    runner = runner if runner is not None else Runner()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(runner.run())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="BaggageFlow", lifespan=lifespan)
    app.state.runner = runner

    # async: it runs on the same event loop as the runner, never in a thread.
    @app.get("/api/status")
    async def status() -> dict:
        return {
            "tick": runner.engine.tick,
            "time_s": runner.engine.time_s,
            "running": runner.running,
        }

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text(layout_message(runner.engine).model_dump_json())
        sender = asyncio.create_task(_send_snapshots(websocket, runner))
        try:
            await _receive_commands(websocket, runner)
        finally:
            sender.cancel()
            try:
                await sender
            # Cancelled while waiting, or the client left during a send.
            except (asyncio.CancelledError, WebSocketDisconnect, OSError):
                pass

    return app


async def _send_snapshots(websocket: WebSocket, runner: Runner) -> None:
    last_event_id = 0
    while True:
        snapshot = snapshot_message(runner.engine, running=runner.running,
                                    after_event_id=last_event_id)
        await websocket.send_text(snapshot.model_dump_json())
        if snapshot.events:
            last_event_id = snapshot.events[-1].id
        await asyncio.sleep(SNAPSHOT_INTERVAL_S)


async def _receive_commands(websocket: WebSocket, runner: Runner) -> None:
    """Queues valid commands until the browser disconnects."""
    while True:
        frame = await websocket.receive()
        if frame["type"] == "websocket.disconnect":
            return
        # Text or binary frame: parse_command accepts both.
        raw = frame.get("text") or frame.get("bytes") or ""
        try:
            command = parse_command(raw)
        except ValidationError as error:
            await websocket.send_text(ErrorMessage(message=_describe(error)).model_dump_json())
            continue
        runner.submit(command)


def _describe(error: ValidationError) -> str:
    """Short, readable reason for the first problem found in a command."""
    first = error.errors(include_url=False)[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"Invalid command: {where + ': ' if where else ''}{first['msg']}"


app = create_app()
