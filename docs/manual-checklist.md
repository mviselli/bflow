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
      the signs BF 101, BF 205, BF 312 and BF 418, each with a counter at
      `0`. No bags. Beside each desk an empty queue lane, with no
      passengers. Each sorter's plate has a steel gate lying along its left
      rail (seen along the line), and a photo-eye (two small housings on the rails, a dark LED)
      just before it. No belt has coloured edges.
- [ ] The page fills the window with no page scroll. The top bar reads
      **Start**, **Reset**, **1×** (pressed), **2×**, **5×**, `00:00.00`,
      `tick 0` and **Live**; no banner over the map.
- [ ] The rail on the left lists Details, Alarms, Events, Controls,
      Indicators and Legend, with no badge on Alarms. The **Details** page
      (open on a first visit) reads **Plant** with the selection hint, Wrong
      sorting `0 % of sorter passages`, Forced error **None**, Open alarms
      `0 errors · 0 warnings`, Sorters `3`.
- [ ] The strip under the map shows Waiting, In transit, Delivered, Wrong
      exits, Throughput, Active errors and Active warnings, all `0`, none
      highlighted.
- [ ] The **Indicators** page shows three groups: **Bag flow** (Generated,
      Waiting, Admitted, In transit), **Deliveries** (Delivered, Wrong
      exits, Throughput, Mean travel time) and **Alarms** (Active errors,
      Active warnings, Errors, Warnings). Every value is `0` and the mean
      travel time is `—`. Hovering over an indicator (here or in the strip)
      shows its definition.
- [ ] The **Alarms** page reads **None open** (Acknowledge all disabled)
      with an empty-state note; the **Events** page reads **No events
      yet**, with three severity buttons (Errors 0, Warnings 0, Info 0) all
      pressed.
- [ ] Every belt has a small steady grey dot beside it, near its start.
- [ ] The belt surfaces do not move. The console shows no errors.

## 2. Start, pause and resume at 1×

- [ ] Click **Start**: the button changes to **Pause** and the time counts
      about one simulated second per real second. The tick is always 20 ×
      the seconds shown (e.g. `00:10.00` and `tick 200`), and the top bar
      does not move while the numbers grow.
- [ ] Belt surfaces scroll in the direction of the pale floor chevrons.
- [ ] At `00:06.70` one bag appears at each of the six desks.
- [ ] Bags move smoothly and never overlap; at a corner, merge or sorter
      they slide across the plate and turn instead of jumping. Each bag
      keeps the same look for its whole trip.
- [ ] At merges the belts take turns; each bag leaves the sort line on the
      branch whose sign has the colour and number of its tag (a 4 tag goes
      to the end of the line, BF 418).
- [ ] Zoomed in on a sorter: as a bag for its branch comes near, the gate,
      hinged at the plate's upstream left corner, swings 45° across it, and
      the bag meets it, slides along its face and turns into the right-hand
      branch (taking under a second, faster than the belt) instead of
      turning on the spot; once the bag is past, the gate closes. For bags
      going straight on it stays along the rail. The photo-eye's LED lights
      white while a bag covers it. Pause: gate and bag stop where they are.
- [ ] Each chute's counter goes up by one as a bag drops into it, and
      matches the sum shown under **Delivered**.
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
- [ ] **Wrong exits**, the four alarm indicators, the Alarms page and the
      Events page stay at `0` / empty (with nothing stopped, faulty or
      missorted, the plant below capacity never warns), and every light stays
      a grey dot.
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
      zoom around the centre (buttons in the map's bottom-right corner).
- [ ] Drag the map: the view moves, without selecting anything. At the
      fitted view there is nothing to drag. The corner-arrows button shows
      the whole plant.
- [ ] With another page open (e.g. Legend), click a bag: the side panel
      switches to **Details**. The bag gets a white outline and the page shows
      **Bag bag-…** with its destination tag, Destination, On belt,
      Position (`x m of y m`), Admitted at and a Travel time that grows.
      The outline and the page follow it from belt to belt.
- [ ] When that bag reaches its chute, the outline disappears and the page
      goes back to **Plant**.
- [ ] Click a belt (e.g. `line-1`): it is outlined and the page shows
      **Belt line-1**: State **Running**, Bags `n of capacity`, Occupancy
      with its bar, Length, Speed, From, To, Congestion **None**, Alarms
      **None**, and the **Stop belt** and **Simulate a fault** buttons.
- [ ] Click a check-in desk (e.g. A1): it is outlined and the page shows
      **Check-in A1**: Waiting, Arrival rate `0.15 bags/s · 9 per min`,
      Feeds belt, and a rate slider.
- [ ] `Esc` clears the selection.

## 6. Belt stop and restart

- [ ] At about `00:30`, select `branch-2` and click **Stop belt**: State
      becomes **Stopped by the operator**, the button becomes **Restart
      belt**, the branch's surface stops, its light becomes a blue square
      and both its edges turn solid blue.
      The rest of the plant keeps moving. The Events page shows an info line **Belt
      stopped by the operator** for Belt branch-2 (a stop is information, not
      a fault).
- [ ] Bags going to BF 205 wait at the second sorter and the line backs up:
      **Delivered** stays around 10–11, **In transit** grows (about 43 at
      `01:00`), the island belts fill up and from about `01:27` bags wait at
      the desks (**Waiting** above 0). A congested belt's edges show long
      amber dashes; a bag still for 30 s carries a small amber clock on its
      rear end, also on belts that are not congested (its belt's light is
      an amber triangle either way).
- [ ] The backed-up belts warn: the first congestion at about `00:52`, the
      first bags held still for 30 s at `01:00`. Their lights become amber
      triangles and blink, **Active warnings** is highlighted in the strip,
      the Alarms rail button shows an amber badge and the warnings are listed
      on the Alarms page under Congestion and Prolonged waits. The stopped
      branch's blue square stays until a bag waits on it for 30 s, then it
      turns into an amber triangle too.
- [ ] At about `01:30`, click **Restart belt**: the branch moves again,
      deliveries resume and **Waiting** goes back to `0` within about 10
      simulated seconds (with a stop a few ticks after `00:30`, short queues
      may come back now and then while the line drains, for up to a couple
      of minutes). The prolonged waits resolve at once; the
      congestions clear as the line drains (for a stop at `00:30.00` and a
      restart at `01:30.00`: 9 congestions and 38 prolonged waits, so
      **Warnings** 47, **Errors** 0, and no alarm left from `04:04.35`).

## 7. Arrival rate

Click **Reset**, then **Start** at 1× (the values below are for a fresh run;
with belts already full the queue grows faster and takes longer to clear).

- [ ] At about `00:10`, select desk A1, drag the slider to `1.00` and
      release: the Details page shows `1.00 bags/s · 60 per min` and bags leave A1
      much more often.
- [ ] At about `01:10` A1 has about 21 bags waiting: its **Waiting** row
      and the **Waiting** indicator show the same number (the other desks
      stay at 0).
- [ ] A1's lane holds passengers: one beside the weighing plate and six in
      the lane, with a **+N** badge where N is the waiting count minus 7.
      Each time a bag leaves A1, the passenger at the plate walks off and
      the line steps forward; the other desks have no passengers. Pause:
      the passengers stop mid-step, if they were moving.
- [ ] On the **Controls** page (Desks), A1's slider reads the same rate and
      its queue the same number. Drag A1's slider there to `0`: no new bag
      appears at A1 and its queue empties in about 50 simulated seconds.
      The badge counts down to nothing, then the passengers leave one by
      one until the lane is empty.

## 8. Reset

Do this after check 7, at 5×, with a belt stopped, a desk rate changed and
a bag selected.

- [ ] Click **Reset**: the map is empty at once, the time reads
      `00:00.00` and `tick 0`, the button reads **Start**, every indicator is
      `0` and the mean travel time is `—`, the Alarms page reads **None
      open** with no badge on the rail, the Events page **No events yet**,
      and every light is a grey dot.
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
      showing the last state received · reconnecting…**, the top bar reads
      **Reconnecting…** in amber without moving, Start/Pause, Reset, the
      speeds, the Details page's buttons or slider and the Controls page are
      disabled and look disabled, the details, strip and lists are dimmed and
      the Indicators page reads **Last values received before the connection
      was lost**.
- [ ] Start the server again: within about a second the banner goes, the
      controls are enabled and the page shows the new server's state (tick
      0, no bags, indicators at zero). The zoom and the selected belt are
      kept.
- [ ] With the simulation running, reload the page: it shows the current
      time and bags straight away, without replaying the missed movement.
- [ ] With the simulation running, switch to another tab for about a minute,
      then come back: the map shows the current state at once, with no fast
      replay, and the page is still **Live**.

## 10. Fault and repair

Click **Reset**, **5×**, then **Start**. The reference values are for a
fault at exactly `00:30.00` and the repair at `02:30.00` (pause at those
times, act, then resume); a little later gives values close to them.

- [ ] At `00:30`, select `line-2` and click **Simulate a fault**: its
      edges show short red dashes (over any amber of a congestion), State
      reads **Faulty · needs repair** in red, Alarms **Fault · active · open
      for … s** (highlighted in red; a row of warnings only is amber), the second button becomes **Repair belt**,
      the belt's surface stops and its light becomes a red cross and blinks.
      **Active errors** `1` (highlighted in red in the strip) and **Errors**
      `1` on the Indicators page (`1 fault · 0 wrong sortings`, not
      highlighted); the Alarms badge turns red and the fault tops the Alarms
      page under Faults; the Events page
      has one red `error` line, Belt line-2, **Belt fault: halted until
      repaired**.
- [ ] Click **Stop belt** then **Restart belt**, and **Pause** then
      **Resume**: the belt stays faulty (only Repair clears a fault).
- [ ] Bags pile up on line-2 and behind it: **Delivered** stops at `9`; the
      first congestion at about `00:46`, the first prolonged waits exactly
      at `01:00.00` (30 s after the fault), bags waiting at the desks from
      about `01:13`. At `01:00.00`: Active warnings 5; at `02:00.00`:
      Waiting 26, In transit 73, Active warnings 73. Errors stays `1`
      however long the fault lasts.
- [ ] At `02:30`, click **Repair belt**: State **Running**, the light goes
      back to a grey dot (or an amber triangle while bags on it still wait),
      **Active errors** `0` at once, **Errors** still `1`. Deliveries
      resume, the prolonged waits resolve within about 9 s, the desks'
      queues clear by about `06:47`, the congestions by `08:43.30`, after
      which the Alarms page reads **None open**. With demand below capacity the
      whole backlog clears by itself.
- [ ] In the end **Errors** `1` and **Warnings** `90` (`16 congestions ·
      74 prolonged waits`), both not highlighted; the counter rules hold.

## 11. Forced error and wrong sorting

- [ ] Click **Reset** (1×). On the **Controls** page, **Sorting** view,
      click **Force a wrong sorting**: the button is disabled, the note **The
      next bag sorted will go down a wrong branch.** appears, the Details
      page (nothing selected) reads Forced error **On the next bag sorted**,
      highlighted, and the Events page shows an info line **Wrong sorting
      forced on the next bag**.
- [ ] Click **Start**. At `00:20.55` bag-3 (tag 3, BF 312) is sent down the
      first branch — the first sorter's gate, closed for it until then,
      swings open just as it is sorted and the bag slides into the
      branch: Forced error goes back to **None**, the button is
      enabled again, **Errors** `1` (`0 faults · 1 wrong sorting`) and the
      Events page has one `error` line, bag-3 · divert-1. Selecting bag-3
      shows **Sorting error · sent to Output BF 101** in red.
- [ ] At `00:24.50` bag-3 drops into the BF 101 chute: the chute flashes red
      for about 3 simulated seconds, **Wrong exits** `1` (highlighted), and
      the Events page adds an `info` line **Arrived at the wrong output**
      for bag-3 at Output BF 101. **Errors** stays `1`: the wrong exit is
      not a second error. At `01:00`: Delivered 24, Wrong exits 1.
- [ ] Wrong sorting is not an alarm: the Alarms page stays **None open**.
- [ ] Drag the probability slider to `10 %` and release: the Details page reads
      `10 % of sorter passages` and wrong sortings now happen now and then;
      each one adds one error and, when the bag exits, one wrong exit and no
      further error. Back to `0 %`: no more errors.
- [ ] At 5× the red flash at a chute is short (about 0.6 real seconds) but
      still visible.

## 12. Alarm handling

Use the fault of check 10 (or repeat it) with many alarms open.

- [ ] The Alarms page groups the open alarms by kind — Faults, Congestion,
      Prolonged waits, in that order — each group with its symbol, count and
      an **Acknowledge N** button; inside a group, those to acknowledge first,
      the newest first. Each row shows what it concerns (`Belt line-2`,
      `bag-… · Belt …`), how long it has been open and an **Acknowledge**
      button. The rail badge counts the alarms to acknowledge.
- [ ] Click a group's name: it collapses, and stays collapsed as snapshots
      arrive; click again to open it.
- [ ] Click a row (not its button): the belt or bag is selected on the map
      and the Alarms page stays open (the Details page shows it).
- [ ] Click **Acknowledge** on the fault: it reads **acknowledged**, the
      belt is still **Faulty · needs repair**, the Details page's Alarms row
      is no longer highlighted, and the belt's light
      stops blinking (steady red) unless a bag on it still has an active
      alarm. **Active errors** stays `1`, **Errors** does not change, and
      the Events page adds an info line **Alarm acknowledged: …**.
- [ ] Click **Acknowledge all**: every row reads **acknowledged**, the note
      reads `… open · 0 to acknowledge`, the button is disabled, the badge
      disappears and every light is steady. New alarms raised afterwards come back blinking and active.
- [ ] Pause for 10 real seconds: the ages of the open alarms do not change.
- [ ] Repair the belt: the fault leaves the list; the warnings leave it as
      the backlog clears, acknowledged or not.
- [ ] Events page: the severity buttons hide and show their lines (e.g. only
      Errors shows the fault and any wrong sortings — still there after the
      repair of check 10, when about 300 events have been recorded: the page
      keeps the latest 200 of each severity); the note then reads
      `Latest … of N events in this run`.
- [ ] **Reset** empties the Alarms and Events pages and turns every light
      back to a grey dot.

## 13. Layout and pages

- [ ] Each rail button opens its page with a short fade; clicking the page
      already open (or the arrow in the panel's corner) hides the side panel
      and the map widens smoothly to the whole width, then sharpens. Clicking
      a rail button shows the panel again. Reload: the page last open (and
      whether the panel was hidden) is remembered.
- [ ] Click a value in the strip under the map: the flow and delivery values
      open the Indicators page, the active alarms the Alarms page.
- [ ] **Controls** page: the Desks / Belts / Sorting / Scenario tabs switch views. In
      Belts, each belt shows the same symbol as its light on the map, its
      state, and **Stop**/**Restart** and **Fault**/**Repair**; clicking a
      belt's name outlines it on the map and keeps the Controls page open;
      **Stop** on a belt gives the same result as **Stop belt** on its
      Details page.
- [ ] The **Legend** page shows the four light symbols and the blinking one,
      the four destination codes with their colours, and how to use the map.
- [ ] Narrow the window below about 860 px: the side panel floats over the
      map instead of narrowing it, the strip keeps four values and the top
      bar stays on one line.
- [ ] Tab through the page with the keyboard: every button shows a visible
      focus ring. With reduced motion turned on in the system, pages and the
      panel switch without animation.

## 14. Scenarios

Reference values computed with the engine (seed 42, every scenario on the
demo plant).

- [ ] At load the top bar shows **Scenario · Normal traffic**. Click it: the
      Controls page opens on its Scenario view, listing Normal traffic
      (marked **Current**, button **Start over**), Peak traffic and Belt
      fault (button **Choose**), each with its description.
- [ ] Choose **Belt fault**: the run starts over, paused at `00:00.00` with
      **Start**, the speed kept; the top bar reads **Belt fault** and it is
      now the current one. `/api/status` shows `"scenario": "fault"` and
      `/api/commands` starts with `{"type": "reset", "scenario_id": "fault"}`.
- [ ] Start at 5×: at `01:00.00` line-2 turns faulty by itself (one error
      line in the Events page, a red light, Active errors 1); at `02:00`:
      Delivered 32, Waiting 10, 53 active warnings; at `03:00`: Waiting 57,
      Throughput 0, 87 active warnings.
- [ ] Pause near `03:00`, repair line-2 from Controls → Belts and resume
      (reference: repaired at `03:00.50`, tick 3610): the desks' queues are
      empty from `07:40.75`, the last alarm closes at `09:34.45`, and at
      `10:00` Delivered reads 512 with no alarm open (Errors 1, Warnings 87).
- [ ] Click **Reset**: the fault scenario starts over (still **Belt fault**,
      line-2 running again until `01:00`).
- [ ] Choose **Peak traffic** and start: at `01:00` six "Arrival rate set to
      0.3 bags/s" lines; at `03:00`: Waiting 34 (none at A3 and B3), Delivered
      159, then six lines back to 0.15 bags/s; the queues clear at
      `05:40.95` and no alarm is open at `10:00` (Delivered 618).

## 15. Charts

- [ ] Choose **Peak traffic**, start at 5× and open **Indicators** →
      **Charts**: before the first second each chart says "Start the
      simulation to draw the chart"; then the lines grow from `0:00`, one
      point per simulated second.
- [ ] At about `03:10`: "Bags in the plant" shows In transit near 75 and
      Waiting rising from `2:00`; "Delivered per minute" levels off near 70.
      The legend values are those of the last sample, with its time ("at
      3:10"): paused, they equal In transit, Waiting and Throughput in the
      strip under the map at that second.
- [ ] Hover over `2:00`: the tooltip reads `2:00`, 71 in transit, 3
      waiting (the engine's values at tick 2400); focus a chart with Tab and
      move along it with the arrow keys.
- [ ] Reload the page while running: the charts come back with the whole
      run so far, not only from the reload.
- [ ] Click **Reset**: both charts empty at once and start again with the new run.

## 16. Hall view

- [ ] Click **Hall** over the map: the flat map tilts up into the hall in
      about a second, the signs fade in at the end, and two turn buttons
      appear above the zoom buttons. The slab fits the map area with a small
      margin; walls stand on its two far sides.
- [ ] Pause: the bags, gates and passengers are the map's (switch back and
      forth); click a bag in the hall: a white box frames it and Details
      shows it; **Map** lays the hall back down and the map shows the same
      bag outlined.
- [ ] **Q**, **E** and the turn buttons turn the hall a quarter turn,
      smoothly; the walls move to the far sides; zoom, drag and the Fit
      button work as on the map; the zoom is kept by a turn.
- [ ] Stop a belt: its tower lights the bottom (blue) lamp and its rails turn
      solid blue. Simulate a fault on line-2: the top (red) lamp blinks with
      a red cross over it and its rails are dashed red; acknowledge the alarm
      and the lamp stays lit; congested belts get amber dashes and their
      middle lamp, waiting bags their clock. Unlit lamps show no colour.
- [ ] A1 at 1 bag/s: passengers queue in A1's lane, the first beside the
      scale, "+N" beyond the seventh; they leave one by one as bags are taken.
- [ ] Zoom in on a sort line: the bags' tag codes appear over them; the
      gates swing for the bags they divert and the photo-eye's LED lights.
- [ ] Reload: the hall view is remembered (shown at once, without the tilt).
      With reduced motion turned on, switching and turning are instant.

## Record

| Date | Browser | Result | Problems and fixes |
| ---- | ------- | ------ | ------------------ |
| 2026-09-26 (one-belt page, earlier version of this list) | Chrome (desktop, driven by Claude) | All checks passed (hidden tab checked by the user) | The Start/Pause button moved sideways whenever the tick gained a digit: the time label now has a fixed minimum width. The browser automation could not hide the tab, so the user ran that check. |
| 2026-09-28 (one-belt page, earlier version of this list) | Chrome (desktop, driven by Claude) | Checks 1–6 passed after the engine gained the merge, sorter, belt stop and new statistics: first delivery at `00:11.45 · tick 229` with 9.45 s; paused at tick 602 with 15 / 0 / 15 / 5 / 10 / 0; picture and counters unchanged while paused; resume without a jump; five quick toggles left it paused; server stop and restart; reload while running. No counter rule broken over 769 updates, no console errors | None. The hidden-tab check was not repeated (the automation cannot hide the tab; nothing in the page changed since the last run). |
| 2026-10-02 | Chrome (desktop, driven by Claude), single process on :8000 | Checks 1–9 passed except the hidden tab (pending, needs the user). Exact matches with the reference values: first bags at `00:06.70` (6), first delivery 21.6 s, rows at ticks 601, 1200 and 2400 equal to the table; counter rules held on all 1,804 updates of the first run; 31 bags counted on the map at tick 2400 = In transit; speeds measured 1.00 / 2.00 / 4.99 simulated s per real s; bag-202 followed across five belts to BF 101; branch-2 stopped at tick 598 → 43 in transit and 11 delivered at `01:00`, desks waiting from `01:26.70`, queue cleared 8.1 s after the restart; A1 at 1 bag/s → 20 waiting at `01:10`, drained in 50.3 s; Reset at 5× cleared plant, indicators and bag selection, restored branch-2 and A1, kept 5×; Start right after Reset started bag-1…6; server stop/restart and reload as described; no console errors | Check 7 first ran after check 6 on a busy plant (42 waiting, 117 s to drain, confirmed equal to an engine replay of `/api/commands`): it now starts with a Reset, and its reference values are for a fresh run. Not judged by the automation: smoothness by eye at 5× and a stopped belt's surface standing still (covered by unit tests). |
| 2026-10-10 | Chrome (desktop, driven by Claude), single process on :8000; tab hidden throughout (time-critical actions triggered from a WebSocket handler in the page, compared with an engine replay of `/api/commands`) | Checks 1–12 passed. 1: Plant panel, four alarm tiles, None open, No events yet, all lights green. 2: first delivery 21.6 s, still for 10 s paused, no jump on resume, five toggles consistent. 3: ticks 604/1201/2400 equal to the table; counter rules held on every update (≥ 1,875 per run, also errors = faults + wrong sortings and warnings = congestions + prolonged waits). 4: 4.95 / 1.99 / 1.01 sim s per real s, speed changed while paused without moving time. 5: wheel zoom without page scroll, drag, bag-153 followed line-2 → line-3, belt line-3 panel with Stop belt and Simulate a fault, desk A1, Esc. 6: stop at tick 609, restart at 1804: Delivered 11 and In transit 43 at `01:00` (replay), 47 warnings (9 congestions, 38 prolonged waits), 0 errors, no alarm from `04:04.45`; queue at 0 at tick 1965 (8 s after the restart), then short queues again until tick 2555 (replay identical). 7: A1 at 1 bag/s from tick 206 → 20 waiting at `01:10`, drained in 46.7 s. 8: Reset with branch-3 stopped and faulty, A1 at 0 and bag-233 selected → everything cleared, 5× kept; Start right after Reset started run 6 from bag-1; `/api/commands` began with the reset. 9: disconnection banner, every control disabled, lists dimmed; reconnected ~2.4 s after the restart with zoom and line-2 kept; reload while running showed the current time in 0.29 s. 10: fault at `00:30.10` (one error line, Repair offered, Stop/Restart and Pause/Resume left it faulty); `01:00`: 9 delivered, 5 active warnings; `02:00`: Waiting 26, In transit 73, 73 active warnings; repair at tick 3003 → Active errors 0 at once, waits resolved by `02:39.25`, all alarms resolved at `08:44.40`, Errors 1, Warnings 90 (16 + 74). 11: forced error decided at `00:20.55` (bag-3, divert-1), wrong exit at `00:24.50` at BF 101, Errors 1 not 2, no alarm; the chute's red flash seen (paused on a second forced error); 10 % → 21 wrong sortings, each followed by exactly one wrong exit, none after 0 %. 12: order active → acknowledged, errors first, newest first; row click selected bag-76; acknowledging the fault: one info event, belt still faulty, Active errors 1, Errors unchanged; Acknowledge all → 0 to acknowledge, lights steady; ages frozen for 10 s paused; new alarms come back active; Reset empties both lists. No console or server errors | Check 12 first failed: after the long fault (294 events) the error filter was empty — the ~200 info lines that follow a repair had pushed the fault out of the page's single 200-event history. The page now keeps the latest 200 events of each severity; re-run: 216 events, the fault still listed under Errors after the recovery. Check 3's "bags drawn = In transit" and check 2's smoothness by eye could not be judged with the tab hidden (`requestAnimationFrame` does not run: the map updates only when a screenshot is taken, and a click can hit a bag of an earlier frame). |
| 2026-10-11 (Phase 6 verification: checks 14 and 15 in full) | Chrome (desktop, driven by Claude), single process on :8000, tab hidden; each run compared with an engine replay of its scenario and `/api/commands` | **Normal** to tick 11997: strip, counters and replay equal (Delivered 512, In transit 22, Throughput 55, no event, no alarm). **Peak** to 11992: equal (Generated 642, Delivered 618, Warnings 4 congestions, no alarm open); the event log's 54 rows = the run's 54 events (12 rate changes, 17 queues started and cleared, 4 congestions); samples at `2:00` (3 waiting) and `3:00` (34 waiting, 159 delivered) as referenced; queues empty from `05:40.95` (replay). Reload at `3:26` while running: the chart came back with all 207 points from `0:00`. Arrow keys moved the crosshair (`3:52` → `3:50`). **Fault**: paused at tick 3610 — Waiting 57, Delivered 32, Throughput 0, Active errors 1, Active warnings 87, badge 88 — repaired line-2 from Controls → Belts, ran to 11994: queues empty from `07:30.55`, no alarm from `09:34.45`, Delivered 512, Errors 1, Warnings 87, 210 event rows = 210 events; all equal to the replay. No console or server errors | **Fixed by the run:** the charts' legend (last sample, whole second) and the strip (newest tick) differed by up to a second (Delivered 56 vs Throughput 55 at `09:59.85`) with nothing saying why: the legend now shows its sample's time ("at 9:59"). `formatMinutes` rounded after splitting minutes (59.6 s → "0:60"); fixed, with a test. Not verifiable here: the tooltip hiding on blur (the automated window has no focus, so no focus/blur events fire). |
| 2026-10-11 (check 15) | Chrome (desktop, driven by Claude), single process on :8000, tab hidden | Peak at 5×, Charts tab at `03:10`: In transit ~74, Waiting rising from `2:00` to 33, Delivered per minute ~70; legend = strip; tooltip at `2:02`: 68 in transit, 3 waiting; a new connection received all 264 samples from tick 0, at tick 2400 equal to the engine (71 / 3 / 88 delivered); Reset → no lines, empty message, legend 0. No console errors | Keyboard navigation and the reload were not exercised in this run (covered by the cursor tests in `test_app.py` / `test_series.py`). |
| 2026-10-11 (check 14, first part) | Chrome (desktop, driven by Claude), single process on :8000, tab hidden | Chip read Normal traffic and opened the Controls page on the Scenario view (Normal marked current, Start over; Peak and Fault with Choose). Choose Belt fault → run 2, paused at tick 0, scenario fault; at 5× line-2 faulty with its `belt_fault` event at tick 1200, Active errors 1, chip Belt fault, list marking it current; `/api/commands` = reset (scenario fault), set_speed 5, start. Reset → run 3, still fault, 5× kept, button Start; Choose Peak → run 4, scenario peak, record starting with reset (scenario peak). No console errors | The time-dependent values of the peak and of the fault at `02:00`/`03:00` were not read in the browser (they are equal to engine runs in `test_after_selecting_a_scenario_the_run_is_the_scenario_itself`); to be run in full with the phase verification. |
| 2026-10-05 | Chrome (desktop, driven by Claude), single process on :8000 | Checks 1–9 passed. First bags at `00:06.70` (6), first delivery 21.6 s; tick 600 and 1200 rows equal to the table, tick 2399 equal to the engine (the 18th arrivals land on tick 2400); counter rules held on all 3,883 updates read by a second WebSocket; bags on the map = In transit (29 at tick 1200); picture and tick unchanged after 10 s paused; resume without a jump; speeds measured 5.00 / 2.05 / 1.02 simulated s per real s, speed changed while paused without moving time; bag-95 followed across island-b-4, line-1 and branch-1 to BF 101; branch-2 stopped at tick 594 → 43 in transit and 11 delivered at `01:00`, desks waiting from `01:26.70` (both from an engine replay of `/api/commands`, which matched the page at tick 1795), queue cleared 8.05 s after the restart; A1 at 1 bag/s → 21 waiting at `01:10`, drained in 49.95 s; Reset at 5× cleared plant, indicators and bag-5's selection, restored branch-2 and A1, kept 5×; Start right after Reset started a new run from bag-1, `/api/commands` = reset and start at 0; server stop/restart (zoom and branch-1 kept) and reload as described; hidden tab for 14 s → current state at once, still connected; no console errors | None. The tab could only be hidden for 14 s, not a minute (the automation brought it back); the silent-link timeout stays covered by unit tests. |
| 2026-10-12 (check 16, first run) | Chrome (desktop, driven by Claude), single process on :8000, tab hidden (frames only on screenshots) | Hall at fit and close zoom on normal traffic at 5×; a quarter turn (E, Q); line-2 faulty, feeder-b2 and feeder-a2 stopped: red dashed rails, red top lamp blinking with the cross, blue rails, amber dashes and clocks on the backed-up belts, neutral unlit lamps; A1 at 1 bag/s: passengers in the lane with "+N"; click on a waiting bag on line-2 → white box and its Details; Map → same bag outlined; reload kept the hall. No console errors, no long tasks | Fixed by the run: slab touching the edges, back walls darker than the background, tinted unlit lamps, cylinder passengers, signs piling up as the view flattened. Not judged with the tab hidden: smoothness of the tilt and turns by eye, reduced motion, tag codes at close zoom. |
| 2026-10-11 (Phase 7: full run, checks 1–15) | Chrome (desktop, driven by Claude), single process on :8000, tab **visible** (map drawn every frame); a second WebSocket in the page checked the counter rules on every snapshot and sent time-critical commands from its `onmessage`; each long run compared with an engine replay of `/api/commands` | All checks passed. 1: texts, strip, groups, tooltips, empty Alarms/Events as listed. 2: bags at tick 134 (`00:06.70`), first delivery 21.6 s, 1.00 sim s per real s, top bar steady, paused exactly at tick 600, still for 10 s, resume without a jump, five quick toggles left page and server paused. 3: ticks 600 and 1200 equal to the table, 2401 equal to the 2400 row; 23 bags counted on the map = In transit 23; rules held on all 1,989 snapshots, no event. 4: 5.00 / 2.00 / 1.01 sim s per real s, speed changed while paused without moving time. 5: wheel zoom around the pointer, sharp after; drag without selecting; bag-34 followed island-b-4 → line-1 → line-2 → line-3 → branch-3, panel back to Plant at its exit; belt branch-1 panel with both buttons; desk A1; Esc. 6: stop at 604 / restart at 1805 → `01:00` In transit 43, Delivered 11; first congestion `00:51.95`; desks waiting from `01:26.70`; 48 warnings (10 + 38), no alarm from `04:04.50` — equal to the replay, and the reference (9 + 38 = 47, `04:04.35`) re-checked for exactly 600/1800; stopped look (blue square, solid blue edges) seen on branch-3 in check 8. 7: A1 at 1 bag/s from tick 203 → 21 waiting at `01:10` (lane: 1 + 6 + "+14"), Controls page equal, drained in ~51 s at 0. 8: Reset at 5× with branch-3 stopped, A1 at 0 and bag-153 selected → all cleared, 5× kept; Start right after Reset ran run 5 from bag-1; `/api/commands` = reset, start. 9: banner, amber Reconnecting…, every control disabled, Indicators note; reconnected to the new server with zoom and line-2 kept; reload while running showed the current tick at once; tab hidden 54.7 s → current tick at once, still Live. 10: fault at 606 → as listed, Stop/Restart and Pause/Resume left it faulty; Delivered 9, first congestion `00:46.45`, waits from 30 s after, desks from `01:13.35`; 2408: Waiting 26, In transit 73, 74 active warnings; repair at 3005 → Active errors 0, waits resolved by `02:39.20`, queues by `06:47.55`, all alarms `08:46.95`; Errors 1, Warnings 90 (16 + 74); equal to the replay. 11: forced error at `00:20.55` (bag-3, divert-1, gate open, panel row red), wrong exit `00:24.50` at BF 101 (chute flashed red, counter unchanged), Errors 1, no alarm; `01:00` Delivered 24 / Wrong exits 1; 10 % → 33 sorting errors and 33 wrong exits, one per bag, none after 0 %. 12: groups Faults / Congestion / Prolonged waits (1 / 14 / 72), collapse kept across snapshots, row click selected bag-100 keeping the page, acknowledge (one info event, still faulty, Active errors 1), Acknowledge all → `87 open · 0 to acknowledge`, ages frozen for 10 s paused, a new congestion raised active afterwards, repair removed the fault, Events filter (errors only = the fault after 289 events, note `Latest 287 of 289`), Reset emptied both. 13: hide/show by rail and corner arrow (map 1008 ↔ 1368 px), page and hidden panel remembered on reload, strip clicks, Controls tabs, belt glyphs = lights, Stop in the list and Stop belt in Details send the same command, Legend, 820 px window (floating panel, four values, one-line top bar, no scroll), 2 px focus ring on every control by Tab, reduced-motion rule present. 14: chip → Scenario view; Belt fault → run 6 paused, 5× kept, `/api/status` fault, record starting with the reset; fault at tick 1200; 2407: Delivered 32, Waiting 10, 54 active warnings; 3606: Waiting 57, Throughput 0, 87; repaired at 3606 from Controls → queues empty `07:40.55`, last alarm `09:31.25`, `10:00` Delivered 512, Errors 1, Warnings 87 (replay equal); Reset kept Belt fault; Peak: 12 rate events, 3602 Waiting 34 (none at A3/B3), Delivered 159, queues clear `05:40.95`, `10:00` Delivered 618, no alarm. 15: empty message before the first second, `03:10` In transit 72 / Waiting 32 / 74 per minute with "at 3:10", tooltip and arrow key at `2:00` = 71 / 3, reload while running restored the whole run, Reset emptied both. No console or server errors | **Fixed by the run:** the Details page highlighted an active fault's Alarms row in amber (the warning colour) under a red State: highlighted rows now carry a severity (`alert: 'warning' \| 'error'`) and an active fault's row is red, with a test. **Reference corrected:** check 14's queues for a repair at tick 3610 empty from `07:40.75`, not `07:30.55` (engine run; this run, repaired at 3606, `07:40.55`, equal to its replay). Not judged by eye: the short red flash at 5× and the reduced-motion switch (system setting; the CSS rule was checked). |
