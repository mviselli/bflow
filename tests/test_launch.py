"""The one-step launcher: when it builds the page, which port it takes, and
that it only opens the page when BaggageFlow already runs."""

import os
import socket
import threading
import time

import pytest
import uvicorn

from bflow import launch
from bflow.server.app import create_app
from bflow.server.runner import Runner


def make_frontend(tmp_path, built: bool):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.js").write_text("// page")
    (tmp_path / "index.html").write_text("<!doctype html>")
    if built:
        (tmp_path / "dist").mkdir()
        (tmp_path / "dist" / "index.html").write_text("<!doctype html>")
    return tmp_path


def age(path, seconds):
    """Makes a file look `seconds` old."""
    when = time.time() - seconds
    os.utime(path, (when, when))


def test_a_build_newer_than_its_sources_is_used_as_it_is(tmp_path):
    frontend = make_frontend(tmp_path, built=True)
    age(frontend / "src" / "main.js", 60)
    age(frontend / "index.html", 60)
    assert not launch.needs_build(frontend)


def test_no_build_or_a_changed_source_needs_a_build(tmp_path):
    (tmp_path / "none").mkdir()
    assert launch.needs_build(make_frontend(tmp_path / "none", built=False))
    (tmp_path / "old").mkdir()
    frontend = make_frontend(tmp_path / "old", built=True)
    age(frontend / "dist" / "index.html", 60)
    assert launch.needs_build(frontend)


def test_without_npm_an_existing_build_is_kept_and_a_missing_one_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(launch.shutil, "which", lambda name: None)
    ran = []
    monkeypatch.setattr(launch.subprocess, "run", lambda *args, **kwargs: ran.append(args))
    (tmp_path / "old").mkdir()
    old = make_frontend(tmp_path / "old", built=True)
    age(old / "dist" / "index.html", 60)
    assert launch.build_page(old)
    (tmp_path / "none").mkdir()
    assert not launch.build_page(make_frontend(tmp_path / "none", built=False))
    assert ran == []


def test_a_missing_build_is_made_with_npm_installing_first(tmp_path, monkeypatch):
    frontend = make_frontend(tmp_path, built=False)
    monkeypatch.setattr(launch.shutil, "which", lambda name: "/usr/bin/npm")
    steps = []

    class Done:
        returncode = 0

    def run(step, cwd):
        steps.append(step[1:])
        assert cwd == frontend
        return Done()

    monkeypatch.setattr(launch.subprocess, "run", run)
    assert launch.build_page(frontend)
    assert steps == [["ci"], ["run", "build"]]


def test_a_port_in_use_is_not_free_and_a_free_one_is_found():
    with socket.socket() as busy:
        busy.bind((launch.HOST, 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert not launch.port_is_free(port)
        assert not launch.is_baggageflow(port)  # something listens, but not BaggageFlow
    other = launch.free_port()
    assert launch.port_is_free(other)


@pytest.fixture
def running_server():
    app = create_app(Runner(clock=lambda: 100.0))
    server = uvicorn.Server(uvicorn.Config(app, host=launch.HOST, port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline
        time.sleep(0.01)
    yield server.servers[0].sockets[0].getsockname()[1]
    server.should_exit = True
    thread.join(timeout=10)


def test_when_baggageflow_already_runs_it_only_opens_the_page(running_server, monkeypatch):
    opened = []
    monkeypatch.setattr(launch.webbrowser, "open", opened.append)
    monkeypatch.setattr(launch, "build_page", lambda: pytest.fail("no build needed"))
    monkeypatch.setattr(launch.uvicorn, "run", lambda *args, **kwargs: pytest.fail("no second server"))
    assert launch.is_baggageflow(running_server)
    assert launch.main(["--port", str(running_server)]) == 0
    assert opened == [f"http://{launch.HOST}:{running_server}/"]


def test_a_busy_port_moves_the_server_to_a_free_one(monkeypatch):
    started = {}
    monkeypatch.setattr(launch, "build_page", lambda: True)
    monkeypatch.setattr(launch.uvicorn, "run", lambda app, host, port, log_level: started.update(host=host, port=port))
    with socket.socket() as busy:
        busy.bind((launch.HOST, 0))
        busy.listen()
        taken = busy.getsockname()[1]
        assert launch.main(["--port", str(taken), "--no-browser"]) == 0
    assert started["host"] == "127.0.0.1"
    assert started["port"] != taken
