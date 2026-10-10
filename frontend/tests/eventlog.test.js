// Event log: history kept per run without duplicates, severity filter and
// the text of each line.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  addSnapshot, emptyLog, eventRow, eventSubject, logNote, MAX_LOG_EVENTS, severityCounts, visibleEvents,
} from '../src/eventlog.js';

function event(id, severity = 'info', overrides = {}) {
  return {
    id, tick: id * 10, time_s: id / 2, severity, kind: 'belt_stopped', message: `event ${id}`,
    element_id: null, baggage_id: null, alarm_id: null, ...overrides,
  };
}

function snapshot(run, tick, ids, severity = 'info') {
  return { run, tick, events: ids.map((id) => event(id, severity)) };
}

const ids = (log) => log.events.map((item) => item.id);

test('events are appended in order, and those received again are ignored', () => {
  let log = addSnapshot(emptyLog(), snapshot(1, 10, [1, 2, 3]));
  log = addSnapshot(log, snapshot(1, 20, []));
  // A new connection resends the retained events, already in the log.
  log = addSnapshot(log, snapshot(1, 30, [2, 3, 4]));
  assert.deepEqual(ids(log), [1, 2, 3, 4]);
  assert.equal(log.lastId, 4);
});

test('a snapshot without new events keeps the same list, so nothing is redrawn', () => {
  const log = addSnapshot(emptyLog(), snapshot(1, 10, [1]));
  assert.equal(addSnapshot(log, snapshot(1, 11, [])).events, log.events);
  assert.equal(addSnapshot(log, snapshot(1, 12, [1])).events, log.events);
});

test('only the latest events are kept, while the note gives the whole run', () => {
  const all = Array.from({ length: MAX_LOG_EVENTS + 50 }, (_, index) => index + 1);
  const log = addSnapshot(emptyLog(), snapshot(1, 10, all));
  assert.equal(log.events.length, MAX_LOG_EVENTS);
  assert.equal(log.events[0].id, 51);
  assert.equal(logNote(log), `Latest ${MAX_LOG_EVENTS} of ${MAX_LOG_EVENTS + 50} events in this run`);
  assert.equal(logNote(addSnapshot(emptyLog(), snapshot(1, 1, [1]))), '1 event in this run');
  assert.equal(logNote(emptyLog()), 'No events yet');
});

test('the limit is per severity, so a burst of information never pushes out a fault', () => {
  let log = addSnapshot(emptyLog(), { run: 1, tick: 1, events: [event(1, 'error')] });
  const burst = Array.from({ length: MAX_LOG_EVENTS + 100 }, (_, index) => index + 2);
  log = addSnapshot(log, snapshot(1, 2, burst, 'info'));
  assert.equal(log.events.length, MAX_LOG_EVENTS + 1);
  assert.deepEqual(log.events[0], event(1, 'error'));
  // Still in order: the fault, then the latest information.
  assert.deepEqual(ids(log).slice(0, 3), [1, 102, 103]);
  assert.equal(ids(log).at(-1), MAX_LOG_EVENTS + 101);
  assert.deepEqual(visibleEvents(log, new Set(['error'])).map((item) => item.id), [1]);
});

test('a new run starts from an empty log, whether reset or a restarted server', () => {
  const log = addSnapshot(emptyLog(), snapshot(1, 900, [1, 2, 3]));
  // Reset: the run number changes and the new engine numbers events from 1.
  assert.deepEqual(ids(addSnapshot(log, snapshot(2, 0, []))), []);
  assert.deepEqual(ids(addSnapshot(log, snapshot(2, 40, [1]))), [1]);
  // A restarted server is run 1 again, with the tick back.
  const restarted = addSnapshot(log, snapshot(1, 5, [1]));
  assert.deepEqual(ids(restarted), [1]);
  assert.equal(restarted.lastId, 1);
});

test('the filter shows the chosen severities, newest first, and counts each one', () => {
  let log = addSnapshot(emptyLog(), snapshot(1, 10, [1, 2], 'info'));
  log = addSnapshot(log, snapshot(1, 20, [3], 'error'));
  log = addSnapshot(log, snapshot(1, 30, [4, 5], 'warning'));
  assert.deepEqual(visibleEvents(log, new Set(['error', 'warning', 'info'])).map((item) => item.id), [5, 4, 3, 2, 1]);
  assert.deepEqual(visibleEvents(log, new Set(['error', 'warning'])).map((item) => item.id), [5, 4, 3]);
  assert.deepEqual(visibleEvents(log, new Set()), []);
  assert.deepEqual(severityCounts(log), { error: 1, warning: 2, info: 2 });
  // Filtering never changes what is kept.
  assert.deepEqual(ids(log), [1, 2, 3, 4, 5]);
});

const layout = {
  inputs: [{ id: 'input-a1', label: 'A1' }],
  outputs: [{ id: 'output-1', label: 'BF 101' }],
  belts: [{ id: 'line-2' }],
};

test('the subject names the bag and where it is, the element, or the plant', () => {
  assert.equal(eventSubject(event(1, 'warning', { element_id: 'line-2', baggage_id: 'bag-7' }), layout),
    'bag-7 · Belt line-2');
  assert.equal(eventSubject(event(1, 'error', { element_id: 'line-2' }), layout), 'Belt line-2');
  assert.equal(eventSubject(event(1, 'info', { element_id: 'input-a1' }), layout), 'Check-in A1');
  assert.equal(eventSubject(event(1, 'info', { element_id: 'output-1', baggage_id: 'bag-3' }), layout),
    'bag-3 · Output BF 101');
  assert.equal(eventSubject(event(1, 'error', { element_id: 'divert-1', baggage_id: 'bag-3' }), layout),
    'bag-3 · divert-1');
  assert.equal(eventSubject(event(1), layout), 'Plant');
  // Before the layout arrives, the ids are shown as they are.
  assert.equal(eventSubject(event(1, 'info', { element_id: 'line-2' }), null), 'line-2');
});

test('a line shows the simulated time, severity, subject and message of the engine', () => {
  assert.deepEqual(eventRow(event(4, 'error', { time_s: 130.1, element_id: 'line-2', message: 'Belt fault' }), layout), {
    id: 4, time: '02:10.10', severity: 'error', subject: 'Belt line-2', message: 'Belt fault',
  });
});
