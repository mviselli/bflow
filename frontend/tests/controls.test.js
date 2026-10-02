// Start/pause button and time format of the top bar.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { formatTime, toggleState } from '../src/controls.js';

function snapshot(run, tick, running) {
  return { run, tick, running };
}

test('the button follows the snapshot: Start at tick 0, Pause while running, Resume when paused', () => {
  assert.deepEqual(toggleState(snapshot(1, 0, false)), { running: false, label: 'Start' });
  assert.deepEqual(toggleState(snapshot(1, 40, true)), { running: true, label: 'Pause' });
  assert.deepEqual(toggleState(snapshot(1, 40, false)), { running: false, label: 'Resume' });
});

test('after a reset, snapshots of the old run still running leave the button on Start', () => {
  assert.deepEqual(toggleState(snapshot(1, 900, true), 1), { running: false, label: 'Start' });
  // The new run is followed as usual, even once it is started.
  assert.deepEqual(toggleState(snapshot(2, 0, false), 1), { running: false, label: 'Start' });
  assert.deepEqual(toggleState(snapshot(2, 10, true), 1), { running: true, label: 'Pause' });
});

test('simulated time is shown as minutes and seconds with hundredths', () => {
  assert.equal(formatTime(0), '00:00.00');
  assert.equal(formatTime(130.1), '02:10.10');
});
