// Controls page: desks, belts and sorting settings read from the snapshot.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { beltRows, deskRows, sortingState } from '../src/plantcontrols.js';

const point = (x_m, y_m) => ({ x_m, y_m });

const LAYOUT = {
  inputs: [{ id: 'input-a', label: 'A1', position: point(0, 0) }, { id: 'input-b', label: 'B1', position: point(0, 4) }],
  outputs: [{ id: 'output-1', label: 'BF 101', position: point(10, 0) }],
  belts: [
    { id: 'feeder-a', source_id: 'input-a', target_id: 'line' },
    { id: 'feeder-b', source_id: 'input-b', target_id: 'line' },
    { id: 'line', source_id: 'feeder-a', target_id: 'output-1' },
  ],
};

function snapshot({ belts = {}, alarms = [], forced = false } = {}) {
  return {
    inputs: [{ id: 'input-a', arrival_rate_bags_s: 0.25 }, { id: 'input-b', arrival_rate_bags_s: 0 }],
    belts: LAYOUT.belts.map(({ id }) => ({ id, stopped: false, faulty: false, congested: false, ...belts[id] })),
    stats: { inputs: [{ input_id: 'input-a', waiting: 3 }, { input_id: 'input-b', waiting: 0 }] },
    missort_probability: 0.1,
    missort_forced: forced,
    alarms,
  };
}

test('each desk shows its queue and rate, in layout order', () => {
  assert.deepEqual(deskRows(LAYOUT, snapshot()), [
    { id: 'input-a', name: 'Check-in A1', waiting: 3, rate: 0.25 },
    { id: 'input-b', name: 'Check-in B1', waiting: 0, rate: 0 },
  ]);
  // Before the first snapshot: names only.
  assert.deepEqual(deskRows(LAYOUT, null).map((row) => [row.name, row.waiting, row.rate]),
    [['Check-in A1', null, null], ['Check-in B1', null, null]]);
});

test('each belt shows its light and state as on the map, and what its buttons do', () => {
  const rows = beltRows(LAYOUT, snapshot({
    belts: { 'feeder-a': { stopped: true }, 'feeder-b': { faulty: true }, line: { congested: true } },
    alarms: [{ id: 1, kind: 'belt_fault', severity: 'error', state: 'active', element_id: 'feeder-b', baggage_id: null }],
  }));
  assert.deepEqual(rows.map((row) => [row.id, row.light.state, row.light.blinking, row.text, row.stopped, row.faulty]), [
    ['feeder-a', 'stopped', false, 'Stopped by the operator', true, false],
    ['feeder-b', 'fault', true, 'Faulty · needs repair', false, true],
    ['line', 'warning', false, 'Running · congested', false, false],
  ]);
  assert.ok(rows.every((row) => row.known));
});

test('before the first snapshot belts are listed without state or commands', () => {
  const rows = beltRows(LAYOUT, null);
  assert.deepEqual(rows.map((row) => [row.id, row.light.state, row.text, row.known]), [
    ['feeder-a', 'running', '—', false], ['feeder-b', 'running', '—', false], ['line', 'running', '—', false],
  ]);
});

test('the sorting settings come from the snapshot', () => {
  assert.equal(sortingState(null), null);
  assert.deepEqual(sortingState(snapshot()), { probability: 0.1, forced: false });
  assert.deepEqual(sortingState(snapshot({ forced: true })), { probability: 0.1, forced: true });
});
