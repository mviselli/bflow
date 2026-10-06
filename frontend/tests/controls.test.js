// Start/pause button and time format of the top bar.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { formatTime, indicators, toggleState } from '../src/controls.js';

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

function stats(overrides = {}) {
  return {
    generated: 40, waiting: 3, admitted: 37, in_transit: 12, correctly_delivered: 24,
    misdelivered: 1, mean_travel_time_s: 21.6, throughput: 18, errors: 3, warnings: 7,
    faults: 1, wrong_sortings: 2, congestions: 2, prolonged_waits: 5, active_errors: 1, active_warnings: 4,
    ...overrides,
  };
}

test('every engine indicator is shown in its group, copied from the stats without computing', () => {
  assert.deepEqual(indicators(stats()).map(({ group, name, value }) => [group, name, value]), [
    ['flow', 'Generated', '40'], ['flow', 'Waiting', '3'], ['flow', 'Admitted', '37'],
    ['flow', 'In transit', '12'],
    ['deliveries', 'Delivered', '24'], ['deliveries', 'Wrong exits', '1'],
    ['deliveries', 'Throughput', '18'], ['deliveries', 'Mean travel time', '21.6 s'],
    ['alarms', 'Active errors', '1'], ['alarms', 'Active warnings', '4'],
    ['alarms', 'Errors', '3'], ['alarms', 'Warnings', '7'],
  ]);
});

test('errors and warnings since the start show the engine\'s breakdown as their caption', () => {
  const captions = Object.fromEntries(indicators(stats()).map((item) => [item.key, item.caption]));
  assert.equal(captions.errors, '1 fault · 2 wrong sortings');
  assert.equal(captions.warnings, '2 congestions · 5 prolonged waits');
  assert.equal(captions.active_errors, 'open now');
});

test('without exited bags the mean time is a dash, and every indicator has a caption and help', () => {
  const shown = indicators(stats({ mean_travel_time_s: null }));
  assert.equal(shown.find((item) => item.key === 'mean_travel_time_s').value, '—');
  assert.ok(shown.every((item) => item.caption.length > 0 && item.help.length > 0));
});

test('wrong exits and active alarms call for attention only above zero, past occurrences never', () => {
  const alerts = (values) => Object.fromEntries(indicators(stats(values))
    .filter((item) => item.alert).map((item) => [item.key, item.alert]));
  assert.deepEqual(alerts({}), { misdelivered: 'warning', active_errors: 'error', active_warnings: 'warning' });
  // Everything repaired and cleared: the occurrences stay, highlighted no more.
  assert.deepEqual(alerts({ misdelivered: 0, active_errors: 0, active_warnings: 0, waiting: 9 }), {});
});
