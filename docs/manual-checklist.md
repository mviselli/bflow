# Manual checklist

Checks to run by hand in the browser before a demo or after changing the
server, the protocol or the page. Each check lists what to do and what you
should see. Automated tests cover the engine, the messages and the page's
pure modules; this list covers what only a person looking at the page can
judge.

Record each run at the bottom: date, browser, result, and any problem found.

## Setup

1. Build the page and start the server (one process):

   ```sh
   npm --prefix frontend run build
   uv run uvicorn bflow.server.app:app
   ```

   If the server was already running, restart it: the checks below expect a
   fresh simulation at tick 0 with the default seed.
2. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a recent desktop
   browser and open the developer console.

The reference values are for the default plant and seed 42: six check-in
desks (A1–A3, B1–B3) each sending one bag every 6.7 s (0.15 bag/s), four
outputs (BF 101, BF 205, BF 312, BF 418), every belt at 1 m/s. They hold at
exactly the tick given; when you pause a little later, expect values close
to them.

## Counter rules

These must hold every time you look at the indicators, running or paused:

- **Generated = Admitted + Waiting**
- **Admitted = Delivered + Wrong exits + In transit**
- **Throughput ≤ Delivered**, and the two are equal during the first minute.

The page copies the indicators from the server without computing anything,
so a mismatch points to the engine or to the message, not to the page.

The picture runs about 0.15 real seconds behind the indicators, so right
after an admission or a delivery they may briefly count a bag that is not
drawn yet, or one that is still fading out at its chute.

## 1. Initial state

- [ ] The map shows the whole plant: two islands of three check-in desks
      (signs A1–A3 at the top, B1–B3 at the bottom), their belts joining at
      the merges, the sort line with three sorters and four chutes with
      the signs BF 101, BF 205, BF 312 and BF 418. No bags.
- [ ] The toolbar reads **Start**, **Reset**, **1×** (pressed), **2×**,
      **5×**, `00:00.00 · tick 0` and **Connected**; no banner over the map.
- [ ] The side panel reads **Details** with the selection hint.
- [ ] Under the map, three groups of indicators: **Bag flow**
      (Generated, Waiting, Admitted, In transit), **Deliveries** (Delivered,
      Wrong exits, Throughput, Mean travel time) and **Alarms** (Errors,
      Warnings). Every value is `0` and the mean travel time is `—`.
- [ ] Hovering over an indicator shows its definition.
- [ ] The belt surfaces do not move. The console shows no errors.

## 2. Start, pause and resume at 1×

- [ ] Click **Start**: the button changes to **Pause** and the time counts
      about one simulated second per real second. The tick is always 20 ×
      the seconds shown (e.g. `00:10.00 · tick 200`), and the toolbar does
      not move while the numbers grow.
- [ ] Belt surfaces scroll in the direction of the yellow chevrons.
- [ ] At `00:06.70` one bag appears at each of the six desks.
- [ ] Bags move smoothly and never overlap; at a corner, merge or sorter
      they slide across the plate and turn instead of jumping. Each bag
      keeps the same look for its whole trip.
- [ ] At merges the belts take turns; each bag leaves the sort line on the
      branch whose sign has the colour and number of its tag (a 4 tag goes
      to the end of the line, BF 418).
- [ ] The first delivery comes at `00:28.30`: **Delivered** 1, **Throughput**
      1, **Mean travel time** `21.6 s`.
- [ ] Click **Pause** (button → **Resume**): bags and belt surfaces stop
      within a fraction of a second, then stay perfectly still. Wait 10 real
      seconds: the time and indicators do not change.
- [ ] Click **Resume**: the time continues from the paused value with no
      jump for the real time spent paused, and bags continue from where they
      stopped. Five quick Pause/Resume clicks leave a consistent state.

## 3. Indicator consistency

Pause near each time and compare (the counter rules must hold exactly):

| Time · tick | Generated | Waiting | Admitted | In transit | Delivered | Wrong exits | Mean travel time | Throughput |
| ----------- | --------- | ------- | -------- | ---------- | --------- | ----------- | ---------------- | ---------- |
| `00:30.00 · tick 600` | 24 | 0 | 24 | 23 | 1 | 0 | 21.6 s | 1 |
| `01:00.00 · tick 1200` | 54 | 0 | 54 | 29 | 25 | 0 | 26.0 s | 25 |
| `02:00.00 · tick 2400` | 108 | 0 | 108 | 31 | 77 | 0 | 28.2 s | 52 |

- [ ] The values match the table (or are close to it, for a later tick).
- [ ] After `01:00` **Throughput** is lower than **Delivered** (it counts
      only the last 60 simulated seconds).
- [ ] **Wrong exits**, **Errors** and **Warnings** stay `0` and are not
      highlighted (nothing in this phase causes them).
- [ ] The number of bags drawn on the map matches **In transit** (allowing
      for the 0.15 s lag).

## 4. Speed

- [ ] Click **5×** (it becomes the pressed button): the time now runs about
      five simulated seconds per real second; bags and belt surfaces move
      five times faster, still smoothly.
- [ ] Click **2×**, then **1×**: the speed changes at once, without a jump
      in time or position.
- [ ] Pause, change the speed, wait a few seconds: the time does not move.
      Resume: it continues at the new speed.

## 5. Zoom, panning and selection

- [ ] Scroll over the map: it zooms around the pointer and the page does not
      scroll; after a moment the textures are sharp again. **+** and **−**
      zoom around the centre.
- [ ] Drag the map: the view moves, without selecting anything. At the
      fitted view there is nothing to drag. **Fit** shows the whole plant.
- [ ] Click a bag: it gets a yellow outline and the panel shows
      **Bag bag-…** with its destination tag, Destination, On belt,
      Position (`x m of y m`), Admitted at and a Travel time that grows.
      The outline and the panel follow it from belt to belt.
- [ ] When that bag reaches its chute, the outline disappears and the panel
      goes back to **Details**.
- [ ] Click a belt (e.g. `line-1`): it is outlined and the panel shows
      **Belt line-1**: State **Running**, Bags `n of capacity`, Occupancy
      with its bar, Length, Speed, From, To, and a **Stop belt** button.
- [ ] Click a check-in desk (e.g. A1): it is outlined and the panel shows
      **Check-in A1**: Waiting, Arrival rate `0.15 bags/s · 9 per min`,
      Feeds belt, and a rate slider.
- [ ] `Esc` clears the selection.

## 6. Belt stop and restart

- [ ] At about `00:30`, select `branch-2` and click **Stop belt**: State
      becomes **Stopped by the operator**, the button becomes **Restart
      belt** and the branch's surface stops. The rest of the plant keeps
      moving.
- [ ] Bags going to BF 205 wait at the second sorter and the line backs up:
      **Delivered** stays around 10–11, **In transit** grows (about 43 at
      `01:00`), the island belts fill up and from about `01:27` bags wait at
      the desks (**Waiting** above 0).
- [ ] At about `01:30`, click **Restart belt**: the branch moves again,
      deliveries resume and **Waiting** goes back to `0` within about 10
      simulated seconds.

## 7. Arrival rate

- [ ] Select desk A1 and drag the slider to `1.00`, then release: the panel
      shows `1.00 bags/s · 60 per min` and bags leave A1 much more often.
- [ ] After about a minute A1 has about 20 bags waiting (its **Waiting** row
      and the **Waiting** indicator grow); the other desks stay at 0.
- [ ] Drag the slider to `0`: no new bag appears at A1 and its queue
      empties within about a minute.

## 8. Reset

Do this after checks 6 and 7, at 5×, with a belt stopped, a desk rate
changed and a bag selected.

- [ ] Click **Reset**: the map is empty at once, the time reads
      `00:00.00 · tick 0`, the button reads **Start**, every indicator is
      `0` and the mean travel time is `—`.
- [ ] The selected bag is no longer selected; **5×** is still pressed.
- [ ] The stopped belt is running again and the changed desk is back to
      `0.15 bags/s` (select them to check).
- [ ] Click **Start** immediately after another **Reset**: the new run
      starts (it does not pause). The first bags are `bag-1` to `bag-6`,
      at the same times as in check 2 (5× faster).
- [ ] [http://127.0.0.1:8000/api/commands](http://127.0.0.1:8000/api/commands)
      lists only the commands since the last reset, each with its tick,
      starting with the reset at tick 0.

## 9. Connection

- [ ] Zoom in a little and select a belt. Stop the server with `Ctrl+C`:
      within a second a banner over the map reads **Connection lost ·
      showing the last state received · reconnecting…**, the toolbar reads
      **Disconnected · retrying…** without moving, Start/Pause, Reset, the
      speeds and the panel's button or slider are disabled and look
      disabled, the panel and indicators are dimmed and the indicators read
      **Last values received before the connection was lost**.
- [ ] Start the server again: within about a second the banner goes, the
      controls are enabled and the page shows the new server's state (tick
      0, no bags, indicators at zero). The zoom and the selected belt are
      kept.
- [ ] With the simulation running, reload the page: it shows the current
      time and bags straight away, without replaying the missed movement.
- [ ] With the simulation running, switch to another tab for about a minute,
      then come back: the map shows the current state at once, with no fast
      replay, and the page is still **Connected**.

## Record

| Date | Browser | Result | Problems and fixes |
| ---- | ------- | ------ | ------------------ |
| 2026-09-26 (one-belt page, earlier version of this list) | Chrome (desktop, driven by Claude) | All checks passed (hidden tab checked by the user) | The Start/Pause button moved sideways whenever the tick gained a digit: the time label now has a fixed minimum width. The browser automation could not hide the tab, so the user ran that check. |
| 2026-09-28 (one-belt page, earlier version of this list) | Chrome (desktop, driven by Claude) | Checks 1–6 passed after the engine gained the merge, sorter, belt stop and new statistics: first delivery at `00:11.45 · tick 229` with 9.45 s; paused at tick 602 with 15 / 0 / 15 / 5 / 10 / 0; picture and counters unchanged while paused; resume without a jump; five quick toggles left it paused; server stop and restart; reload while running. No counter rule broken over 769 updates, no console errors | None. The hidden-tab check was not repeated (the automation cannot hide the tab; nothing in the page changed since the last run). |
