// Display clock and interpolation between snapshots, with Node's built-in runner.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  DISPLAY_DELAY_S, MAX_DRIFT_S, beltOffset, createPlayback, interpolateBaggage,
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
  assert.equal(beltOffset(1, 0, 0.125), 0);
  assert.ok(Math.abs(beltOffset(1, 0.1, 0.125) - 0.1) < 1e-12);
  assert.ok(Math.abs(beltOffset(1, 0.2, 0.125) - 0.075) < 1e-12);
  assert.ok(Math.abs(beltOffset(0.5, 1000.05, 0.125) - 0.025) < 1e-9);
});
