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
first FastAPI server owns the engine, advances it in real time, streams the
route layout and state snapshots, and accepts start, pause, and resume commands
over a WebSocket. The page draws the belt and the bags from these snapshots,
with start, pause, and resume buttons and the engine counters. The graphics
are drawn in code, with textures, shadows, and several suitcase styles. Bags
and the belt surface move smoothly: the page draws the simulation a fraction
of a second behind the newest snapshot and places each bag between the two
positions the engine reported, so nothing is extrapolated. When paused, the
bags and the belt stop at the paused instant.
The full plant is also described in Python: three check-in desks, a merge,
a common line, a sorter and three output branches, with belt connections,
speeds and map coordinates in metres from which belt lengths are derived. A
plant is checked when it is created: connections must match on the map, every
output must be reachable from every input by exactly one route, and cycles or
unconnected elements are rejected. The engine can run this plant from
the check-in desks to the outputs: each desk generates bags at its own rate,
each destined for one of the three outputs at random, with its own waiting
queue, and bags pass from one belt to the next around corners. At the merge the
three lines take turns onto the common line, one bag at a time, keeping the
spacing; a line with no bag ready is skipped. The sorter sends each bag onto
the branch of its destination; when that branch has no room, the bag waits at
the sorter and the bags behind it queue up. A single belt can be stopped and
restarted while the rest of the plant keeps running: its bags stay put, a queue
builds up behind it, and after the restart the flow resumes. The engine reports,
besides the overall counters, how full each belt is (bags compared with the
most it can hold at the minimum spacing), how many bags are waiting at each
check-in desk, and the throughput: correct deliveries in the last 60 simulated
seconds, and the arrivals at each output. The command line runs the whole
plant; the page still shows the single-belt route.

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

Development uses two processes, each in its own terminal: the Python
simulation server and the Vite development server for the page.

```sh
uv run uvicorn bflow.server.app:app
npm --prefix frontend run dev
```

Open the address printed by Vite, usually
[http://127.0.0.1:5173](http://127.0.0.1:5173). Vite forwards the page's
`/ws` and `/api` requests to the Python server on port 8000 and updates the
page when JavaScript or CSS changes. The page shows a top-down view of the
route: a check-in desk, the belt with its rails and drums, and an output chute
on a terminal floor. Each suitcase is drawn at the position and length computed
by the engine, with a style and colour that depend on its identifier and a tag
showing its destination. **Start** runs the simulation, **Pause** freezes it,
and **Resume** continues from the same instant; the simulated time and the
engine counters are shown as the server sends them. If the Python server is
not running, the page shows that it is disconnected and retries every second.
Both servers listen only on the local machine; stop them with `Ctrl+C`.
To check start, pause, resume, the counters and reconnection by hand, follow
the [manual checklist](docs/manual-checklist.md).

Run the frontend tests, which check the conversion from metres to screen
coordinates, how suitcases are labelled and styled, and the smooth movement
between snapshots (including stopping on pause), with
`npm --prefix frontend test`.

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
real-time runner, validation of the messages exchanged with the browser,
start, pause, and resume over the WebSocket, and the layout and snapshots sent
to the browser.

## Command-line run

```sh
uv run python -m bflow.cli --duration 600 --seed 42
```

Runs the whole plant without the browser, as fast as possible, and prints
generated, waiting, admitted, correctly delivered, misdelivered, and in-transit
baggage, the mean travel time (`—` before the first exit), the throughput
(correct deliveries in the last 60 simulated seconds), errors and warnings;
then the bags waiting at each check-in desk, the correct and wrong arrivals at
each output, the bags on each belt against its capacity, and the conservation
check `admitted = delivered + misdelivered + in transit`. `--duration` is in
simulated seconds and must be a multiple of 50 ms (default 600); `--seed`
defaults to 42; `--layout minimal` runs the single-belt route shown by the page
instead of the full plant. The command exits with status 1 if conservation
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

The browser and the server talk over the WebSocket at `ws://127.0.0.1:8000/ws`
using JSON messages with a `type` field. On connection the server sends a
`layout` message with the route (identifiers, belt length and speed, bag length,
minimum gap, step duration), then `snapshot` messages about 12 times per
second, running or paused. Each snapshot has the tick and simulated time, the
running state, the bags on the belt with their position and length in metres,
the engine counters, and only the events not yet sent on that connection; a new
connection receives the full current state.

Commands go the other way: `{"type": "start"}` starts the simulation or
resumes it after a pause, and `{"type": "pause"}` freezes simulated time.
Commands are applied even while paused, and repeating one has no effect. An
invalid command receives an `{"type": "error", "message": ...}` reply and the
connection stays open. The page's buttons send these commands; to send them by
hand, open the browser developer console on any page and run:

```js
const ws = new WebSocket("ws://127.0.0.1:8000/ws");
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.type === "snapshot") document.title = `tick ${message.tick}`;
  else console.log(message);
};
ws.onopen = () => ws.send(JSON.stringify({ type: "start" }));
```

The tab title shows the tick advancing about 20 times per second; send
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
