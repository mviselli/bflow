"""FastAPI application: starts the runner with the server and stops it on exit.

    uv run uvicorn bflow.server.app:app

Handlers never call Engine.step(): they read the state or hand commands to
the runner, which applies them in its own loop.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

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

    return app


app = create_app()
