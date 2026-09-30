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

## Setup

```sh
uv sync --locked
npm --prefix frontend ci
```

## Run in the browser

Start the simulation server and the page, each in its own terminal:

```sh
uv run uvicorn bflow.server.app:app
npm --prefix frontend run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Use **Start**, **Pause**
and **Resume**, **Reset** to start again from the beginning, and **1×**, **2×**
or **5×** to change the speed; the counters come from the engine. Scroll over
the map to zoom, drag to move the view and use **Fit** to see the whole plant
again. Click a bag, a belt or a check-in desk to see its details in the side panel
(a belt's state and occupancy, a bag's destination, position and travel time,
a desk's queue and arrival rate). From the panel you can stop and restart a
belt, or change how many bags arrive at a desk. `Esc` clears the selection. Stop
both servers with `Ctrl+C`.

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
