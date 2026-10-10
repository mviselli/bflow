// Event log under the open alarms: the engine's events, newest first, with
// simulated time, severity, the element or bag involved and the message,
// and a filter by severity.
//
// The events arrive with the snapshots: each connection sends every event
// once, by id, and a new connection resends the ones the engine retained.
// addSnapshot() (pure, tested with node --test) keeps them in order without
// duplicates, only the latest MAX_LOG_EVENTS of each severity, and starts
// over at a new run.
// The page never makes up events: it only filters and formats them.

import { count, formatTime } from './controls.js';
import { elementName } from './panel.js';
import { isNewRun } from './playback.js';

// Events kept on the page, for each severity. The history is limited so the
// page does not grow without end; the engine counts every event anyway (the
// indicators). Per severity, so that a burst of information (many bags
// moving again after a repair) never pushes the fault itself out.
export const MAX_LOG_EVENTS = 200;

// Severities from the most to the least serious, as the filter lists them.
export const SEVERITIES = [
  { id: 'error', name: 'Errors', symbol: '✖' },
  { id: 'warning', name: 'Warnings', symbol: '▲' },
  { id: 'info', name: 'Info', symbol: '●' },
];

// A log with no events, before the first snapshot. `lastId` is the id of
// the newest event received in the run, which is also how many events the
// run has recorded (ids are consecutive from 1).
export function emptyLog() {
  return { run: null, tick: 0, lastId: 0, events: [] };
}

// The log after a snapshot: its new events appended (oldest first), without
// those already received, keeping only the latest `max` of each severity. A
// new run (reset, or a restarted server) starts from an empty log. `events` is a new array
// only when it changed, so the caller can redraw only then.
export function addSnapshot(log, snapshot, max = MAX_LOG_EVENTS) {
  const newRun = log.run !== null && isNewRun(log, snapshot);
  const previous = newRun ? emptyLog() : log;
  const added = snapshot.events.filter((event) => event.id > previous.lastId);
  let events = previous.events;
  if (added.length > 0 || newRun) events = keepLatest([...events, ...added], max);
  return {
    run: snapshot.run,
    tick: snapshot.tick,
    lastId: added.length > 0 ? added[added.length - 1].id : previous.lastId,
    events,
  };
}

// The latest `max` events of each severity, still in order.
function keepLatest(events, max) {
  const kept = {};
  const latest = [];
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const { severity } = events[index];
    kept[severity] = (kept[severity] ?? 0) + 1;
    if (kept[severity] <= max) latest.push(events[index]);
  }
  return latest.reverse();
}

// The events of the chosen severities (a Set of ids), newest first.
export function visibleEvents(log, severities) {
  return log.events.filter((event) => severities.has(event.severity)).reverse();
}

// How many events of each severity the log holds, for the filter buttons.
export function severityCounts(log) {
  const counts = Object.fromEntries(SEVERITIES.map(({ id }) => [id, 0]));
  for (const event of log.events) counts[event.severity] += 1;
  return counts;
}

// What an event concerns: the bag and where it is, the element, or the
// whole plant (e.g. the wrong sorting probability).
export function eventSubject(event, layout) {
  const belt = layout?.belts.some((item) => item.id === event.element_id);
  const element = event.element_id === null ? null
    : belt ? `Belt ${event.element_id}`
      : layout ? elementName(event.element_id, layout) : event.element_id;
  if (event.baggage_id !== null) return element ? `${event.baggage_id} · ${element}` : event.baggage_id;
  return element ?? 'Plant';
}

// One line of the log, as text.
export function eventRow(event, layout) {
  return {
    id: event.id,
    time: formatTime(event.time_s),
    severity: event.severity,
    subject: eventSubject(event, layout),
    message: event.message,
  };
}

// The note above the list: how much of the run's history is shown.
export function logNote(log) {
  if (log.lastId === 0) return 'No events yet';
  if (log.events.length === log.lastId) return `${count(log.lastId, 'event')} in this run`;
  return `Latest ${log.events.length} of ${count(log.lastId, 'event')} in this run`;
}

// Draws the log into its element: a filter button per severity (all shown
// at first) and the list, redrawn only when the events or the filter change.
export function createEventLog(element) {
  const note = element.querySelector('#events-note');
  const filter = element.querySelector('.severity-filter');
  const list = element.querySelector('#event-list');
  const shown = new Set(SEVERITIES.map(({ id }) => id));
  let log = emptyLog();
  let layout = null;

  const buttons = SEVERITIES.map(({ id, name, symbol }) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.severity = id;
    button.setAttribute('aria-pressed', 'true');
    button.title = `Show or hide ${name.toLowerCase()}`;
    button.addEventListener('click', () => {
      if (shown.has(id)) shown.delete(id);
      else shown.add(id);
      button.setAttribute('aria-pressed', String(shown.has(id)));
      draw();
    });
    filter.append(button);
    return { id, name, symbol, button };
  });

  function draw() {
    const counts = severityCounts(log);
    for (const { id, name, symbol, button } of buttons) button.textContent = `${symbol} ${name} ${counts[id]}`;
    note.textContent = logNote(log);
    const rows = visibleEvents(log, shown).map((event) => eventRow(event, layout));
    list.replaceChildren(...rows.map((row) => {
      const item = document.createElement('li');
      item.dataset.severity = row.severity;
      const time = document.createElement('time');
      time.textContent = row.time;
      const severity = document.createElement('span');
      severity.className = 'severity';
      const { symbol, name } = SEVERITIES.find(({ id }) => id === row.severity);
      severity.textContent = `${symbol} ${row.severity}`;
      severity.title = name;
      const subject = document.createElement('span');
      subject.className = 'subject';
      subject.textContent = row.subject;
      const message = document.createElement('span');
      message.className = 'message';
      message.textContent = row.message;
      item.append(time, severity, subject, message);
      return item;
    }));
    if (rows.length === 0) {
      const empty = document.createElement('li');
      empty.className = 'empty';
      empty.textContent = log.events.length === 0 ? 'No events yet.' : 'No events of the chosen severities.';
      list.append(empty);
    }
  }
  draw();

  return {
    setLayout(message) {
      layout = message;
      draw();
    },
    setSnapshot(snapshot) {
      const next = addSnapshot(log, snapshot);
      const changed = next.events !== log.events || next.lastId !== log.lastId;
      log = next;
      if (changed) draw();
    },
  };
}
