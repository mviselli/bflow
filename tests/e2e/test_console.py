"""The console in a real browser: what the operator sees after each command.

Only observable effects are checked (texts, buttons, counters, the
server's status and command record), never the animation: the map is
left alone, the clock is the fake one of the `plant` fixture.
"""

import pytest

pytest.importorskip("pytest_playwright")

from playwright.sync_api import Page, expect  # noqa: E402

expect.set_options(timeout=10_000)


def open_console(page: Page, plant) -> None:
    page.goto(plant.url)
    expect(page.locator("#connection")).to_have_text("Live")
    expect(page.locator("#tick")).to_have_text("tick 0")
    expect(page.locator("#toggle .label")).to_have_text("Start")


def kpi(page: Page, name: str):
    """A tile of the strip under the map, by its name."""
    return page.locator("#kpis button").filter(has=page.get_by_text(name, exact=True))


def open_page(page: Page, name: str) -> None:
    """Shows a page in the side panel (a click on the open page's button would close it)."""
    button = page.locator(f'.rail button[data-page="{name}"]')
    if not (button.get_attribute("aria-pressed") == "true"
            and page.locator(".app").get_attribute("data-dock") == "open"):
        button.click()
    expect(page.locator(f'.dock .page[data-page="{name}"]')).to_be_visible()


def belt_row(page: Page, belt_id: str):
    open_page(page, "operate")
    page.locator('.page.operate .tabs button[data-view="belts"]').click()
    return page.locator("#belt-list li").filter(has=page.get_by_text(belt_id, exact=True))


def recorded(plant) -> list[tuple[int, str]]:
    return [(record["tick"], record["command"]["type"]) for record in plant.commands()]


def test_start_pause_and_resume_move_the_clock_only_while_running(page: Page, plant):
    open_console(page, plant)
    toggle = page.locator("#toggle")

    toggle.click()
    expect(toggle).to_have_attribute("data-running", "true")
    expect(toggle.locator(".label")).to_have_text("Pause")
    plant.run_ticks(40)
    expect(page.locator("#tick")).to_have_text("tick 40")
    expect(page.locator("#time")).to_have_text("00:02.00")

    toggle.click()
    expect(toggle.locator(".label")).to_have_text("Resume")
    plant.wait_for(lambda status: not status["running"])
    plant.idle(5)  # real time passes while paused
    assert plant.status()["tick"] == 40
    expect(page.locator("#tick")).to_have_text("tick 40")

    toggle.click()
    expect(toggle.locator(".label")).to_have_text("Pause")
    plant.wait_for(lambda status: status["running"])
    # Resuming goes on from the paused tick: the 5 s spent paused are not simulated.
    assert plant.status()["tick"] == 40
    plant.run_ticks(20)
    expect(page.locator("#tick")).to_have_text("tick 60")
    assert recorded(plant) == [(0, "start"), (40, "pause"), (40, "start")]


def test_reset_starts_the_run_over_paused_and_clears_the_operator_commands(page: Page, plant):
    open_console(page, plant)
    page.locator("#toggle").click()
    plant.wait_for(lambda status: status["running"])
    belt_row(page, "line-1").get_by_role("button", name="Stop", exact=True).click()
    expect(belt_row(page, "line-1").locator("small")).to_have_text("Stopped by the operator")
    plant.run_ticks(600)
    expect(page.locator("#tick")).to_have_text("tick 600")
    expect(kpi(page, "In transit").locator(".value")).not_to_have_text("0")
    open_page(page, "events")
    expect(page.locator("#event-list li:not(.empty)")).not_to_have_count(0)

    page.locator("#reset").click()
    expect(page.locator("#toggle .label")).to_have_text("Start")
    status = plant.wait_for(lambda status: status["run"] == 2)
    assert (status["tick"], status["running"], status["scenario"]) == (0, False, "normal")
    expect(page.locator("#tick")).to_have_text("tick 0")
    for name in ("Waiting", "In transit", "Delivered", "Active warnings"):
        expect(kpi(page, name).locator(".value")).to_have_text("0")
    expect(page.locator("#event-list li:not(.empty)")).to_have_count(0)
    expect(page.locator("#events-note")).to_have_text("No events yet")
    expect(belt_row(page, "line-1").locator("small")).to_have_text("Running")

    plant.idle(2)  # the new run waits for Start
    assert plant.status()["tick"] == 0
    assert recorded(plant) == [(0, "reset")]


def test_a_fault_raises_an_alarm_that_only_the_repair_clears(page: Page, plant):
    open_console(page, plant)
    row = belt_row(page, "line-2")
    row.get_by_role("button", name="Fault", exact=True).click()
    expect(row.locator("small")).to_have_text("Faulty · needs repair")
    active_errors = kpi(page, "Active errors")
    expect(active_errors.locator(".value")).to_have_text("1")
    expect(active_errors).to_have_attribute("data-alert", "error")
    expect(page.locator("#alarms-badge")).to_have_text("1")

    # Starting the simulation does not clear the fault.
    page.locator("#toggle").click()
    plant.wait_for(lambda status: status["running"])
    plant.run_ticks(400)
    expect(page.locator("#tick")).to_have_text("tick 400")
    expect(row.locator("small")).to_have_text("Faulty · needs repair")
    expect(row.get_by_role("button", name="Repair", exact=True)).to_be_visible()

    # Acknowledging silences the alarm but leaves it open.
    open_page(page, "alarms")
    alarm = page.locator("#alarm-groups li").filter(has_text="line-2")
    alarm.get_by_role("button", name="Acknowledge", exact=True).click()
    expect(page.locator("#alarms-badge")).to_be_hidden()
    expect(active_errors.locator(".value")).to_have_text("1")

    # The repair, from the belt's details.
    belt_row(page, "line-2").locator("button.name").click()
    open_page(page, "inspect")
    expect(page.locator("#panel-title")).to_have_text("Belt line-2")
    page.locator("#panel-actions").get_by_role("button", name="Repair belt").click()
    expect(active_errors.locator(".value")).to_have_text("0")
    expect(active_errors).not_to_have_attribute("data-alert", "error")
    expect(page.locator("#panel-actions").get_by_role("button", name="Simulate a fault")).to_be_visible()
    open_page(page, "events")
    expect(page.locator("#event-list li:not(.empty)").filter(has_text="line-2").first).to_be_visible()

    types = [kind for _, kind in recorded(plant)]
    assert types == ["fault_belt", "start", "acknowledge_alarm", "repair_belt"]


def test_the_hall_view_shows_the_same_plant_and_is_remembered(page: Page, plant):
    open_console(page, plant)
    view = page.locator("#map")
    hall = page.locator('.view-switch button[data-view="hall"]')
    turn = page.locator("#turn-left")
    expect(view).to_have_attribute("data-view", "map")
    expect(turn).to_be_hidden()

    hall.click()
    expect(hall).to_have_attribute("aria-pressed", "true")
    expect(view).to_have_attribute("data-view", "hall")
    expect(turn).to_be_visible()
    # The hall follows the run like the map; turning it changes nothing in the plant.
    page.locator("#toggle").click()
    expect(page.locator("#toggle")).to_have_attribute("data-running", "true")
    plant.run_ticks(200)
    expect(page.locator("#tick")).to_have_text("tick 200")
    turn.click()
    page.keyboard.press("e")

    page.reload()
    expect(page.locator("#connection")).to_have_text("Live")
    expect(view).to_have_attribute("data-view", "hall")
    page.locator('.view-switch button[data-view="map"]').click()
    expect(view).to_have_attribute("data-view", "map")
    expect(turn).to_be_hidden()
    assert [kind for _, kind in recorded(plant)] == ["start"]


@pytest.fixture(autouse=True)
def no_console_errors(page: Page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: message.type == "error" and errors.append(message.text))
    yield
    assert errors == []
