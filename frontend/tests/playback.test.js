// Display clock and interpolation between snapshots, with Node's built-in runner.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  DISPLAY_DELAY_S, MAX_DRIFT_S, advanceSurface, createPlayback, interpolateBaggage, isNewRun, isNextBelt,
} from '../src/playback.js';

const STEP_S = 0.05;

function bag(id, position) {
  return { id, destination_id: 'OUT-1', conveyor_id: 'C1', position_m: position, length_m: 0.8 };
}

function snapshot(tick, baggage = [], running = true) {
  return { tick, time_s: tick * STEP_S, running, baggage };
}

// Feeds snapshots every `interval` real seconds and frames every 1/60 s;
// returns the display time of each frame.
function play(playback, { fromTick, snapshots, interval = 0.1, ticksPerSnapshot = 2, running = true }) {
  const times = [];
  let now = 0;
  for (let i = 0; i < snapshots; i += 1) {
    playback.add(snapshot(fromTick + i * ticksPerSnapshot, [], running), now);
    for (let frame = 0; frame < 6; frame += 1) {
      times.push(playback.advance(now));
      now += interval / 6;
    }
  }
  return times;
}

test('before the first snapshot there is nothing to draw', () => {
  const playback = createPlayback();
  assert.equal(playback.advance(0), null);
  assert.deepEqual(playback.baggageAt(0), []);
});

test('while running the clock settles one delay behind the server and moves at 1×', () => {
  const playback = createPlayback();
  const times = play(playback, { fromTick: 0, snapshots: 60 });
  const last = times.length - 1;
  // After 6 s the clock follows the server's time minus the delay.
  const serverNow = (59 * 2) * STEP_S + 5 * (0.1 / 6);
  assert.ok(Math.abs(serverNow - DISPLAY_DELAY_S - times[last]) < 0.02);
  // Over the last second it advanced by about one second, never backwards.
  const speed = (times[last] - times[last - 60]) / 1.0;
  assert.ok(Math.abs(speed - 1) < 0.03, `speed ${speed}`);
  for (let i = 1; i < times.length; i += 1) assert.ok(times[i] >= times[i - 1]);
});

test('the clock never goes past the newest snapshot', () => {
  const playback = createPlayback();
  playback.add(snapshot(100), 0);
  for (let now = 0; now < 3; now += 1 / 60) {
    assert.ok(playback.advance(now) <= 100 * STEP_S);
  }
});

test('when paused the clock reaches the paused tick and stops there', () => {
  const playback = createPlayback();
  play(playback, { fromTick: 0, snapshots: 20 });
  playback.add(snapshot(40, [], false), 2);
  let time = null;
  for (let now = 2; now < 3; now += 1 / 60) time = playback.advance(now);
  assert.equal(time, 40 * STEP_S);
  assert.equal(playback.advance(10), 40 * STEP_S);
});

test('a far target makes the clock jump instead of replaying', () => {
  const playback = createPlayback();
  playback.add(snapshot(0), 0);
  playback.advance(0);
  // A hidden tab: the next frame comes 30 s later, with a much newer snapshot.
  playback.add(snapshot(600), 30);
  const time = playback.advance(30);
  assert.ok(600 * STEP_S - time <= DISPLAY_DELAY_S + 1e-9);
  assert.ok(600 * STEP_S - time < MAX_DRIFT_S);
});

test('an older tick (a restarted server) starts over', () => {
  const playback = createPlayback();
  playback.add(snapshot(500, [bag('B1', 5)]), 0);
  playback.advance(0);
  playback.add(snapshot(3, [bag('B9', 0.1)]), 1);
  assert.equal(playback.advance(1), 3 * STEP_S);
  assert.deepEqual(playback.baggageAt(3 * STEP_S).map((baggage) => baggage.id), ['B9']);
});

test('a new run (a reset) starts over even when the tick does not go back', () => {
  const playback = createPlayback();
  // Run 1 at tick 4; the reset and a quick start reach tick 10 by the next snapshot.
  playback.add({ ...snapshot(2, [bag('B1', 0.1)]), run: 1 }, 0);
  playback.add({ ...snapshot(4, [bag('B1', 0.2)]), run: 1 }, 0.1);
  playback.advance(0.1);
  playback.add({ ...snapshot(10, [bag('B1', 0.4)]), run: 2 }, 0.2);
  // Nothing of run 1 is left: no slide of bag B1 from its old position.
  assert.equal(playback.advance(0.2), 10 * STEP_S);
  assert.deepEqual(playback.baggageAt(10 * STEP_S).map((b) => [b.id, b.position_m, b.alpha]),
    [['B1', 0.4, 1]]);
  assert.deepEqual(playback.baggageAt(3 * STEP_S).map((b) => b.position_m), [0.4]);
});

test('a snapshot belongs to a new run when its run number changes or its tick goes back', () => {
  assert.equal(isNewRun({ run: 1, tick: 40 }, { run: 1, tick: 42 }), false);
  assert.equal(isNewRun({ run: 1, tick: 40 }, { run: 1, tick: 40 }), false);
  assert.equal(isNewRun({ run: 1, tick: 0 }, { run: 2, tick: 0 }), true);
  assert.equal(isNewRun({ run: 1, tick: 40 }, { run: 2, tick: 60 }), true);
  assert.equal(isNewRun({ run: 3, tick: 40 }, { run: 3, tick: 2 }), true);
});

test('bags are drawn between the positions of the two snapshots around the time', () => {
  const playback = createPlayback();
  playback.add(snapshot(10, [bag('B1', 1.0)]), 0);
  playback.add(snapshot(12, [bag('B1', 1.1)]), 0.1);
  const [middle] = playback.baggageAt(11 * STEP_S);
  assert.ok(Math.abs(middle.position_m - 1.05) < 1e-9);
  assert.equal(middle.alpha, 1);
  assert.equal(playback.baggageAt(10 * STEP_S)[0].position_m, 1.0);
  assert.equal(playback.baggageAt(12 * STEP_S)[0].position_m, 1.1);
});

test('bags that enter or leave between two snapshots fade in place', () => {
  const bags = interpolateBaggage([bag('OLD', 9.2)], [bag('NEW', 0.05)], 0.25);
  const byId = Object.fromEntries(bags.map((baggage) => [baggage.id, baggage]));
  assert.equal(byId.NEW.position_m, 0.05);
  assert.equal(byId.NEW.alpha, 0.25);
  assert.equal(byId.OLD.position_m, 9.2);
  assert.equal(byId.OLD.alpha, 0.75);
  // Fully faded bags are not returned.
  assert.deepEqual(interpolateBaggage([bag('OLD', 9.2)], [], 1), []);
  assert.deepEqual(interpolateBaggage([], [bag('NEW', 0.05)], 0), []);
});

test('the belt surface offset follows speed × time and repeats every slat', () => {
  assert.equal(advanceSurface(0, 1, 0, 0.125), 0);
  assert.ok(Math.abs(advanceSurface(0, 1, 0.1, 0.125) - 0.1) < 1e-12);
  assert.ok(Math.abs(advanceSurface(0.1, 1, 0.1, 0.125) - 0.075) < 1e-12);
  assert.ok(Math.abs(advanceSurface(0, 0.5, 1000.05, 0.125) - 0.025) < 1e-9);
  // A stopped belt passes speed 0: its surface stays where it is.
  assert.equal(advanceSurface(0.05, 0, 3, 0.125), 0.05);
});

// A corner and a sorter, as in the plant: across → (corner) → down → sorter
// at (10, 4) → left or right. A side belt joins a merge at (20, 4) from
// above, stopping at the edge of its plate. Map coordinates in metres.
const point = (x_m, y_m) => ({ x_m, y_m });
function belt(id, source_id, target_id, start, end) {
  const length_m = Math.hypot(end.x_m - start.x_m, end.y_m - start.y_m);
  return { id, source_id, target_id, start, end, length_m };
}
const BELTS = new Map([
  belt('across', 'input-a', 'down', point(0, 0), point(10, 0)),
  belt('down', 'across', 'sorter', point(10, 0), point(10, 4)),
  belt('left', 'sorter', 'output-1', point(10, 4), point(2, 4)),
  belt('right', 'sorter', 'merge', point(10, 4), point(20, 4)),
  belt('side', 'input-b', 'merge', point(20, 0), point(20, 3.5)),
  belt('line', 'merge', 'output-2', point(20, 4), point(30, 4)),
].map((b) => [b.id, b]));

function on(conveyor, id, position) {
  return { id, destination_id: 'output-1', conveyor_id: conveyor, position_m: position, length_m: 0.6 };
}

test('consecutive belts are those after a belt or after the same node', () => {
  const [across, down, left] = ['across', 'down', 'left'].map((id) => BELTS.get(id));
  assert.ok(isNextBelt(across, down, BELTS));
  assert.ok(isNextBelt(down, left, BELTS));
  assert.ok(!isNextBelt(down, across, BELTS));
  assert.ok(!isNextBelt(across, left, BELTS), 'two belts ahead is not the next one');
  assert.ok(!isNextBelt(left, BELTS.get('right'), BELTS), 'two branches of a sorter');
});

test('a bag that changes belt slides across the joint at an even pace', () => {
  // Centre 0.35 m before the corner, then 0.35 m after it: 0.7 m in all.
  const previous = [on('across', 'B1', 9.35)];
  const next = [on('down', 'B1', 0.05)];
  const at = (fraction) => interpolateBaggage(previous, next, fraction, BELTS)[0];
  assert.deepEqual([at(0).conveyor_id, at(0).position_m], ['across', 9.35]);
  // A quarter of the way: 0.175 m further along the first belt.
  assert.equal(at(0.25).conveyor_id, 'across');
  assert.ok(Math.abs(at(0.25).position_m - 9.525) < 1e-9);
  // Half way: its centre is on the corner, drawn on the new belt.
  assert.equal(at(0.5).conveyor_id, 'down');
  assert.ok(Math.abs(at(0.5).position_m - -0.3) < 1e-9);
  assert.equal(at(1).conveyor_id, 'down');
  assert.ok(Math.abs(at(1).position_m - 0.05) < 1e-9);
  for (const fraction of [0, 0.25, 0.5, 0.75, 1]) assert.equal(at(fraction).alpha, 1);
});

test('a bag leaving a sorter slides onto its branch', () => {
  // Waiting with its front edge at the sorter, then at the start of its branch.
  const bags = interpolateBaggage([on('down', 'B1', 3.4)], [on('left', 'B1', 0)], 0.75, BELTS);
  assert.equal(bags.length, 1);
  assert.equal(bags[0].conveyor_id, 'left');
  // 0.6 m in all, 0.45 m done: centre 0.15 m past the sorter, rear edge 0.15 m before it.
  assert.ok(Math.abs(bags[0].position_m - -0.15) < 1e-9);
});

test('without the layout, or between belts that do not meet, the bag fades', () => {
  const previous = [on('across', 'B1', 9.4)];
  assert.equal(interpolateBaggage(previous, [on('down', 'B1', 0)], 0.25)[0].alpha, 0.25);
  const skipped = interpolateBaggage(previous, [on('left', 'B1', 0)], 0.25, BELTS);
  assert.deepEqual(skipped.map((b) => [b.conveyor_id, b.alpha]), [['left', 0.25]]);
});

test('the playback slides bags between snapshots on different belts', () => {
  const playback = createPlayback();
  playback.add({ tick: 10, time_s: 0.5, running: true, baggage: [on('across', 'B1', 9.4)] }, 0);
  playback.add({ tick: 12, time_s: 0.6, running: true, baggage: [on('down', 'B1', 0)] }, 0.1);
  const [middle] = playback.baggageAt(0.55, BELTS);
  assert.equal(middle.conveyor_id, 'down');
  assert.ok(Math.abs(middle.position_m - -0.3) < 1e-9);
  assert.equal(middle.alpha, 1);
});

test('a bag joining from the side slides past the belt end to the centre of the plate', () => {
  // Front edge at the end of the side belt, 0.5 m before the merge's centre;
  // then rear edge at the start of the line, on the centre. Its centre moves
  // 0.3 + 0.5 m down to the plate's centre, then 0.3 m along the line.
  const previous = [on('side', 'B1', 2.9)];
  const next = [on('line', 'B1', 0)];
  const at = (fraction) => interpolateBaggage(previous, next, fraction, BELTS)[0];
  // Half way (0.55 m): still coming down, 0.05 m before the centre.
  assert.equal(at(0.5).conveyor_id, 'side');
  assert.ok(Math.abs(at(0.5).position_m - 3.45) < 1e-9);
  // Three quarters (0.825 m): turned onto the line, centre 0.025 m past the centre.
  assert.equal(at(0.75).conveyor_id, 'line');
  assert.ok(Math.abs(at(0.75).position_m - -0.275) < 1e-9);
  assert.ok(Math.abs(at(1).position_m) < 1e-9);
});

test('at 5× the clock runs five simulated seconds per real second, a delay behind', () => {
  const playback = createPlayback();
  // A snapshot every 1/12 real second, 5/12 simulated seconds apart.
  const times = [];
  let now = 0;
  for (let i = 0; i < 72; i += 1) {
    const time_s = i * 5 / 12;
    playback.add({ tick: Math.round(time_s / STEP_S), time_s, running: true, speed: 5, baggage: [] }, now);
    for (let frame = 0; frame < 5; frame += 1) {
      times.push(playback.advance(now));
      now += 1 / 60;
    }
  }
  const last = times.length - 1;
  const speed = (times[last] - times[last - 60]) / 1.0;
  assert.ok(Math.abs(speed - 5) < 0.1, `speed ${speed}`);
  // It settles about DISPLAY_DELAY_S real seconds (0.75 simulated) behind the server.
  const serverNow = 71 * 5 / 12 + 4 * 5 / 60;
  assert.ok(Math.abs(serverNow - DISPLAY_DELAY_S * 5 - times[last]) < 0.1);
});
