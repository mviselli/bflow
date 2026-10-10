// Open alarm list: order, text and what each row selects.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { alarmBadge, alarmGroups, alarmRows, alarmsNote } from '../src/alarms.js';

const LAYOUT = {
  inputs: [], outputs: [], belts: [{ id: 'line-1' }, { id: 'line-2' }],
};

function alarm(id, kind, state, raised, { element = 'line-1', bag = null } = {}) {
  return {
    id, kind, severity: kind === 'belt_fault' ? 'error' : 'warning', state, message: '',
    element_id: element, baggage_id: bag, raised_at_s: raised,
    acknowledged_at_s: state === 'active' ? null : raised + 1, resolved_at_s: state === 'resolved' ? 30 : null,
  };
}

test('to acknowledge first, errors before warnings, newest first; resolved ones are left out', () => {
  const rows = alarmRows({
    time_s: 40,
    alarms: [
      alarm(1, 'belt_fault', 'acknowledged', 5, { element: 'line-2' }),
      alarm(2, 'congestion', 'active', 10),
      alarm(3, 'prolonged_wait', 'active', 20, { bag: 'bag-9' }),
      alarm(4, 'belt_fault', 'active', 15),
      alarm(5, 'congestion', 'acknowledged', 12),
      alarm(6, 'congestion', 'resolved', 1),
    ],
  }, LAYOUT);
  assert.deepEqual(rows.map((row) => row.id), [4, 3, 2, 1, 5]);
});

test('a row names the alarm, what it concerns, its state and age, and what to select', () => {
  const [fault, wait] = alarmRows({
    time_s: 40,
    alarms: [alarm(1, 'belt_fault', 'active', 12.5), alarm(2, 'prolonged_wait', 'acknowledged', 30, { bag: 'bag-9' })],
  }, LAYOUT);
  assert.deepEqual(fault, {
    id: 1, kind: 'belt_fault', severity: 'error', state: 'active', name: 'Fault', subject: 'Belt line-1',
    age: 'open for 27.5 s', selection: { kind: 'belt', id: 'line-1' }, acknowledgeable: true,
  });
  assert.equal(wait.subject, 'bag-9 · Belt line-1');
  assert.deepEqual(wait.selection, { kind: 'bag', id: 'bag-9' });
  assert.equal(wait.acknowledgeable, false);
});

test('the note says how many are open and how many wait for an acknowledgement', () => {
  const rows = alarmRows({
    time_s: 40, alarms: [alarm(1, 'belt_fault', 'active', 1), alarm(2, 'congestion', 'acknowledged', 2)],
  }, LAYOUT);
  assert.equal(alarmsNote(rows), '2 open · 1 to acknowledge');
  assert.equal(alarmsNote([]), 'None open');
});

test('alarms are grouped by kind, faults first, each group in the order of the rows', () => {
  const rows = alarmRows({
    time_s: 40,
    alarms: [
      alarm(1, 'prolonged_wait', 'active', 5, { bag: 'bag-1' }),
      alarm(2, 'congestion', 'acknowledged', 10),
      alarm(3, 'prolonged_wait', 'acknowledged', 20, { bag: 'bag-2' }),
      alarm(4, 'belt_fault', 'active', 15),
      alarm(5, 'prolonged_wait', 'active', 25, { bag: 'bag-3' }),
    ],
  }, LAYOUT);
  const groups = alarmGroups(rows);
  assert.deepEqual(groups.map((group) => [group.name, group.severity, group.rows.map((row) => row.id), group.toAcknowledge]), [
    ['Faults', 'error', [4], 1],
    ['Congestion', 'warning', [2], 0],
    ['Prolonged waits', 'warning', [5, 1, 3], 2],
  ]);
  // Kinds with no open alarm are left out.
  assert.deepEqual(alarmGroups(rows.filter((row) => row.kind !== 'congestion')).map((group) => group.kind),
    ['belt_fault', 'prolonged_wait']);
  assert.deepEqual(alarmGroups([]), []);
});

test('the rail badge counts the alarms to acknowledge, red when one is an error', () => {
  const rows = (alarms) => alarmRows({ time_s: 40, alarms }, LAYOUT);
  assert.equal(alarmBadge([]), null);
  assert.equal(alarmBadge(rows([alarm(1, 'belt_fault', 'acknowledged', 1)])), null);
  assert.deepEqual(alarmBadge(rows([alarm(1, 'congestion', 'active', 1), alarm(2, 'congestion', 'active', 2)])),
    { count: 2, severity: 'warning' });
  assert.deepEqual(alarmBadge(rows([alarm(1, 'congestion', 'active', 1), alarm(2, 'belt_fault', 'active', 2)])),
    { count: 2, severity: 'error' });
});
