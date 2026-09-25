# BaggageFlow

An educational airport baggage sorting simulator with a Python engine and
a 2D interface built with PixiJS.

## Project status

The initial foundation is available: the `bflow` Python package, dependencies,
and a Vite frontend with a static scene that verifies PixiJS initialization.
Python data models for baggage, conveyors, and the minimal route configuration
are available with validation tests. The engine has a fixed 50 ms simulation
clock and an independent seeded random generator. Regular arrivals queue at the
entrance and enter only when baggage length and minimum spacing fit. Generated
and admitted counts are tracked separately. Baggage moves at the configured
belt speed, maintaining spacing without overtaking, and leaves through the
output. Transfers are evaluated after movement and applied separately; bags
behind a departing bag use the freed space on the next tick. Correct and incorrect
exit counts, baggage in transit, and mean travel time are available from the
engine. Travel time excludes waiting before admission and includes all exits;
the mean is `None` until the first exit. Only the current tick’s departed bags
are retained. The engine produces an immutable statistics snapshot and an
event log with progressive identifiers, severity, and a bounded recent
history; an entrance queue is recorded when it starts and when it clears, not
on every tick. A command-line run prints the summary without a browser. A
first FastAPI server owns the engine, advances it in real time, and accepts
start, pause, and resume commands over a WebSocket; the interface does not yet
display the simulation or offer controls.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) to manage Python and dependencies.
- Python 3.14 for development, selected by `.python-version`; uv can install it
  automatically. The package declares support for Python >=3.12.
- Node.js 22.12+ within the 22.x series, or 24+, with npm, to develop and build
  the frontend (see the [Vite requirements](https://vite.dev/guide/)).
- A recent desktop browser with WebGL enabled.

## Initial setup

From the repository root:

```sh
uv sync --locked
npm --prefix frontend ci
```

`uv sync` creates `.venv` and installs pytest from the `dev` dependency group.
The `uv.lock` and `frontend/package-lock.json` files pin dependency versions
and should be kept in version control. After updating the project, run these
commands again to synchronize your environment with the lockfiles.

## Development

```sh
npm --prefix frontend run dev
```

Open the address printed in the terminal, usually
[http://127.0.0.1:5173](http://127.0.0.1:5173). Vite updates the page when
JavaScript or CSS changes. The server listens only on the local machine;
stop it with `Ctrl+C`.

To check the Python environment:

```sh
uv run python -c "import bflow; import bflow.core; import bflow.server"
uv run pytest --version
```

Run the Python tests with `uv run pytest`. The current suite checks data model
validation, simulated timestamps, configuration boundaries, fixed simulation
steps, seeded random reproducibility, arrival rates, entrance queues, and
admission spacing, movement, deterministic exits, baggage conservation, the
event log, statistics snapshots, the command-line summary, the server's
real-time runner, validation of the messages exchanged with the browser, and
start, pause, and resume over the WebSocket.

## Command-line run

```sh
uv run python -m bflow.cli --duration 600 --seed 42
```

Runs the default route without the browser, as fast as possible, and prints
generated, waiting, admitted, correctly delivered, misdelivered, and in-transit
baggage, the mean travel time (`—` before the first exit), errors, warnings, and
the conservation check `admitted = delivered + misdelivered + in transit`.
`--duration` is in simulated seconds and must be a multiple of 50 ms (default
600); `--seed` defaults to 42. The command exits with status 1 if conservation
fails.

## Simulation server

```sh
uv run uvicorn bflow.server.app:app
```

Starts the FastAPI server at [http://127.0.0.1:8000](http://127.0.0.1:8000).
A single runner owns the engine: it applies queued commands, then runs the
50 ms steps that real time says are due, in small groups so the server stays
responsive. If the machine falls behind, the simulation slows down instead of
catching up in a burst. The simulation starts stopped; `GET /api/status`
returns the current tick, simulated time, and whether it is running.

Commands are JSON messages sent over the WebSocket at `ws://127.0.0.1:8000/ws`:
`{"type": "start"}` starts the simulation or resumes it after a pause, and
`{"type": "pause"}` freezes simulated time. Commands are applied even while
paused, and repeating one has no effect. An invalid command receives an
`{"type": "error", "message": ...}` reply and the connection stays open.
Buttons in the interface are not yet connected; to try the commands, open the
browser developer console on any page and run:

```js
const ws = new WebSocket("ws://127.0.0.1:8000/ws");
ws.onmessage = (event) => console.log(event.data);
ws.onopen = () => ws.send(JSON.stringify({ type: "start" }));
```

Then reload `/api/status` to watch the tick advance, and send
`ws.send(JSON.stringify({ type: "pause" }))` to stop it.

## Build and preview

```sh
npm --prefix frontend run build
npm --prefix frontend run preview
```

The build generates `frontend/dist/`. The build preview is usually available at
[http://127.0.0.1:4173](http://127.0.0.1:4173); use the actual address printed
in the terminal. Use `preview` to inspect the local build.
Rebuild when the frontend changes, rather than before every launch.

## Running the complete application

Running the application with only the Python server is not yet available.
Once implemented, FastAPI will serve the compiled frontend files. Node will
be needed for development and builds, but not to serve an existing build.
Backend and frontend development will use two separate processes.

## Structure

```text
bflow/core/              Simulation engine, independent of server and graphics
bflow/server/            FastAPI server and real-time runner
tests/                   Python tests
frontend/src/            JavaScript and CSS
frontend/public/assets/  Graphics assets
```

The Python distribution is named `baggageflow`; the importable package is `bflow`.
