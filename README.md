# BaggageFlow

An educational airport baggage-sorting simulator: a Python engine and a 2D
browser view built with PixiJS.

The engine models a small airport plant: six check-in desks in two islands,
whose belts join one sort line, and three diverts along the line that send
each bag to one of four flights. Bags arrive at each desk, take turns wherever
two belts merge and are sorted to their destination. Belts can be stopped and
restarted. The browser shows the whole plant; the command line runs it
without the browser.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (installs Python automatically)
- Node.js 22.12+ or 24+, with npm
- A desktop browser with WebGL

Node.js is needed only to build the page (once, and again after changing the
frontend) or to develop it; running an existing build needs only uv.

## Installation

```sh
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend run build
```

The last command writes the page to `frontend/dist/`.

## Run

```sh
uv run uvicorn bflow.server.app:app
```

This single process runs the simulation and serves the page: open
[http://127.0.0.1:8000](http://127.0.0.1:8000). Stop it with `Ctrl+C`. If the
page has not been built, the address says how to build it; after building,
restart the server.

## Use

Use **Start**, **Pause** and **Resume**, **Reset** to start again from the
beginning, and **1×**, **2×** or **5×** to change the speed. Scroll over the
map to zoom, drag to move the view and use **Fit** to see the whole plant
again. Click a bag, a belt or a check-in desk to see its details in the side
panel (a belt's state and occupancy, a bag's destination, position and travel
time, a desk's queue and arrival rate). From the panel you can stop and
restart a belt, or change how many bags arrive at a desk. `Esc` clears the
selection.

The indicators under the map come from the engine, in three groups: bag flow
(generated, waiting at the desks, admitted, in transit), deliveries
(delivered, wrong exits, throughput over the last 60 simulated seconds, mean
travel time) and alarms (errors, warnings); hover over one for its meaning.

If the server stops or the network drops, the page says so over the map,
disables the commands and keeps the last state received, dimmed; it reconnects
by itself and then shows the current state, keeping your zoom and selected belt
or desk.

The server records every command with the simulation step it was applied at.
[http://127.0.0.1:8000/api/commands](http://127.0.0.1:8000/api/commands) lists
the commands of the current run (a reset starts a new one): the same seed and
the same commands at the same steps always give the same run, at any speed.

## Develop the page

While changing the frontend, run the simulation server and the Vite
development server, each in its own terminal:

```sh
uv run uvicorn bflow.server.app:app
npm --prefix frontend run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173): the page reloads when
a frontend file changes, and Vite forwards `/ws` and `/api` to the Python
server. Stop both with `Ctrl+C`. Build again (`npm --prefix frontend run
build`) to update the page served on port 8000.

## Run from the command line

```sh
uv run python -m bflow.cli --duration 600 --seed 42
```

Runs the whole plant as fast as possible and prints a summary: totals,
throughput, and figures for each check-in desk, output and belt.

| Option | Meaning | Default |
| --- | --- | --- |
| `--duration` | simulated seconds (multiple of 0.05) | `600` |
| `--seed` | random seed; the same seed gives the same run | `42` |
| `--layout` | `full` plant or `minimal` single belt | `full` |

The command exits with status 1 if bags are lost or duplicated.

## Tests

```sh
uv run pytest
npm --prefix frontend test
```

Manual browser checks are listed in [docs/manual-checklist.md](docs/manual-checklist.md).

## Project layout

```text
bflow/core/     simulation engine (no server or graphics)
bflow/server/   FastAPI server and WebSocket
frontend/       PixiJS page (Vite)
tests/          Python tests
```

## License

[AGPL-3.0](LICENSE)
