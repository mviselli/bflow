"""FastAPI application: starts the runner with the server and stops it on exit.

    uv run uvicorn bflow.server.app:app

Handlers never call Engine.step(): they read the state or hand commands to
the runner, which applies them in its own loop.

The browser sends commands as JSON over the WebSocket at /ws. A command is
validated, then queued: it takes effect at the runner's next update, even
while the simulation is paused. An invalid command gets an ``error`` message
back and the connection stays open.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from pydantic import ValidationError

from bflow.server.protocol import ErrorMessage, parse_command
from bflow.server.runner import Runner


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

    return app


def _describe(error: ValidationError) -> str:
    """Short, readable reason for the first problem found in a command."""
    first = error.errors(include_url=False)[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"Invalid command: {where + ': ' if where else ''}{first['msg']}"


app = create_app()
