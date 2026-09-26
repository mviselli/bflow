# Manual checklist

Checks to run by hand in the browser before a demo or after changing the
server, the protocol or the page. Each check lists what to do and what you
should see. Automated tests cover the engine and the messages; this list
covers what only a person looking at the page can judge.

Record each run at the bottom: date, browser, result, and any problem found.

## Setup

1. Start the two processes, each in its own terminal:

   ```sh
   uv run uvicorn bflow.server.app:app
   npm --prefix frontend run dev
   ```

2. Open [http://127.0.0.1:5173](http://127.0.0.1:5173) in a recent desktop
   browser and open the developer console.
3. If the server was already running, restart it first: the checks below
   expect a fresh simulation at tick 0.

The reference values below are for the default configuration: a 10 m belt at
1 m/s, one 0.6 m bag every 2 simulated seconds, a 0.2 m minimum gap.

## Counter rules

These must hold every time you look at the counters, running or paused:

- **Generated = Admitted + Waiting**
- **Admitted = Delivered + Misdelivered + In transit**

The page copies the counters from the server without computing anything, so
a mismatch points to the engine or to the message, not to the page.

The picture runs about 0.15 s behind the counters, so right after an
admission or a delivery the counters may briefly count a bag that is not
drawn yet, or one that is still fading out at the output.

## 1. Initial state

- [ ] The page shows the floor, the check-in desk, the belt and the output
      chute, with no bags.
- [ ] The connection indicator reads **Connected** and the button reads
      **Start** and is enabled.
- [ ] The time reads `00:00.00 · tick 0`.
- [ ] Every counter is `0` and **Mean time** is `—`.
- [ ] The belt surface does not move.
- [ ] The console shows no errors.

## 2. Start

- [ ] Click **Start**: the button changes to **Pause** and the time starts
      counting at about one simulated second per real second.
- [ ] The tick is always 20 × the seconds shown (e.g. `00:10.00 · tick 200`).
- [ ] The button stays in place while the time and tick grow.
- [ ] The belt surface scrolls from the desk (left) towards the chute (right).
- [ ] The first bag appears at the desk end at about `00:02` and a new one
      every 2 s; bags move smoothly, without jumps, and never overlap.
- [ ] Each bag keeps the same look (style, colour, destination tag) for its
      whole trip.
- [ ] The first bag leaves at the chute at about `00:11.45`: **Delivered**
      becomes 1 and **Mean time** shows `9.45 s`.

## 3. Pause

- [ ] Let it run past `00:20`, then click **Pause**: the button changes to
      **Resume**.
- [ ] Bags and the belt surface stop within a fraction of a second and then
      stay perfectly still; the time and tick stop changing.
- [ ] Wait at least 10 real seconds: nothing moves, the time and the
      counters do not change, and no bag appears or disappears.
- [ ] The counter rules hold.

## 4. Resume

- [ ] Click **Resume**: the button changes to **Pause**.
- [ ] The time continues from the paused value, with no jump for the real
      time spent paused.
- [ ] Bags continue from where they stopped, without jumping forwards or
      backwards, and the belt surface scrolls again.
- [ ] Pause and resume a few times in quick succession: the state stays
      consistent and nothing jumps.

## 5. Counter consistency while running

Pause at a few moments (for example around `00:30` and `01:00`) and check:

- [ ] The counter rules hold.
- [ ] **Waiting** is `0` and **Misdelivered** is `0` (the belt has room for
      every bag, and there is only one output).
- [ ] After the first delivery, **In transit** stays at 4–5, and the number
      of bags drawn on the belt matches it (allowing for the 0.15 s lag).
- [ ] **Mean time** stays at `9.45 s`.
- [ ] At exactly `00:30.00 · tick 600`, if you manage to pause there, the
      counters are generated 15, admitted 15, delivered 10, in transit 5.

## 6. Connection

- [ ] Stop the Python server with `Ctrl+C`: the indicator reads
      **Disconnected · retrying…** and the button is disabled; the scene
      stops moving.
- [ ] Start the server again: within about a second the page reconnects, the
      button is enabled again and the state is the new server's (tick 0,
      counters at zero, no bags).
- [ ] With the simulation running, reload the page: it reconnects and shows
      the current time and bags without replaying the missed movement.
- [ ] Switch to another tab for 10 seconds while running, then come back: the
      scene shows the current state straight away, with no fast replay.

## Record

| Date | Browser | Result | Problems and fixes |
| ---- | ------- | ------ | ------------------ |
| 2026-09-26 | Chrome (desktop, driven by Claude) | All checks passed (hidden tab checked by the user) | The Start/Pause button moved sideways whenever the tick gained a digit: the time label now has a fixed minimum width. The browser automation could not hide the tab, so the user ran that check. |
