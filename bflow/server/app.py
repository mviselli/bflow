"""FastAPI application: starts the runner with the server and stops it on exit.

    uv run uvicorn bflow.server.app:app

It also serves the page built by Vite (frontend/dist, made by
``npm --prefix frontend run build``) at http://127.0.0.1:8000/, so the built
application needs this single process. Without a build the API and the
WebSocket still work, and / says how to build the page.

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
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from bflow.server.protocol import (
    CommandRecord, ErrorMessage, layout_message, parse_command, snapshot_message,
)
from bflow.server.runner import Runner


# About 12 snapshots per real second, within the 10–15 Hz target.
SNAPSHOT_INTERVAL_S = 1 / 12
# Where Vite writes the built page: frontend/dist next to the bflow package.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

NOT_BUILT_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>BaggageFlow</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40em; margin: 3em auto">
<h1>BaggageFlow</h1>
<p>The simulation server is running, but the page has not been built yet.
Build it once, then restart this server:</p>
<pre>npm --prefix frontend ci
npm --prefix frontend run build</pre>
<p>During development you can use the Vite server instead
(<code>npm --prefix frontend run dev</code>).</p>
</body></html>
"""


def create_app(runner: Runner | None = None, *, frontend_dir: Path = FRONTEND_DIST) -> FastAPI:
    """Builds the app around a runner; tests can pass their own runner and page."""
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
            "speed": runner.speed,
            "run": runner.run_number,
        }

    # The commands applied in the current run, each with its tick: replayed
    # at the same ticks on a new engine they give the same run.
    @app.get("/api/commands")
    async def commands() -> list[CommandRecord]:
        return list(runner.record)

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

    _serve_frontend(app, frontend_dir)
    return app


def _serve_frontend(app: FastAPI, frontend_dir: Path) -> None:
    """Serves the built page after the API and the WebSocket, which keep priority.

    The page is index.html plus the files Vite puts next to it (assets/).
    Whether a build exists is checked once, when the app is created: after a
    first build, restart the server.
    """
    index = frontend_dir / "index.html"
    if not index.is_file():
        @app.get("/", include_in_schema=False)
        async def not_built() -> HTMLResponse:
            return HTMLResponse(NOT_BUILT_PAGE, status_code=503)
        return

    @app.get("/", include_in_schema=False)
    async def page() -> FileResponse:
        # Always revalidated: a new build links to assets with new names.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=frontend_dir), name="frontend")


async def _send_snapshots(websocket: WebSocket, runner: Runner) -> None:
    engine = runner.engine
    last_event_id = 0
    while True:
        # After a reset the new engine numbers its events from 1 again.
        if runner.engine is not engine:
            engine = runner.engine
            last_event_id = 0
        snapshot = snapshot_message(engine, running=runner.running, speed=runner.speed,
                                    run=runner.run_number, after_event_id=last_event_id)
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
            runner.submit(parse_command(raw))
        except ValidationError as error:
            await websocket.send_text(ErrorMessage(message=_describe(error)).model_dump_json())
        except ValueError as error:  # a belt or input that is not in the plant
            await websocket.send_text(ErrorMessage(message=f"Invalid command: {error}").model_dump_json())


def _describe(error: ValidationError) -> str:
    """Short, readable reason for the first problem found in a command."""
    first = error.errors(include_url=False)[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"Invalid command: {where + ': ' if where else ''}{first['msg']}"


app = create_app()
