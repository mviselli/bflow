# BaggageFlow

An educational airport baggage sorting simulator with a Python engine and
an Italian-language 2D interface built with PixiJS.

## Project status

The initial foundation is available: the `bflow` Python package, dependencies,
and a Vite frontend with a static scene that verifies PixiJS initialization.
Python data models for baggage, conveyors, and the minimal route configuration
are available with validation tests. The engine has a fixed 50 ms simulation
clock and an independent seeded random generator. Regular arrivals queue at the
entrance and enter only when baggage length and minimum spacing fit. Generated
and admitted counts are tracked separately. Movement, the CLI, FastAPI server,
and simulation controls are not yet implemented; admitted baggage currently
stays at the entrance while subsequent arrivals wait.

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
admission spacing.

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
bflow/server/            Future FastAPI server
tests/                   Python tests
frontend/src/            JavaScript and CSS
frontend/public/assets/  Graphics assets
```

The Python distribution is named `baggageflow`; the importable package is `bflow`.
