// Open alarms, under the indicators: each one the engine has raised and not
// yet resolved, with an Acknowledge button while it is active. Clicking an
// alarm selects its belt or bag on the map, where the panel offers what
// ends it (a repair, a restart).
//
// alarmRows() is pure (tested with node --test). Acknowledging only tells
// the engine the operator has seen the alarm: it stays open until its
// condition ends, so the list shrinks only as the plant recovers.

import { eventSubject } from './eventlog.js';
import { ALARM_NAMES } from './panel.js';

// Open alarms in the order an operator handles them: not yet acknowledged
// first, errors before warnings, then the newest first. Each row is text,
// plus what to select and whether it can be acknowledged.
export function alarmRows(snapshot, layout) {
  const open = snapshot.alarms.filter((alarm) => alarm.state !== 'resolved');
  const rank = (alarm) => (alarm.state === 'active' ? 0 : 2) + (alarm.severity === 'error' ? 0 : 1);
  open.sort((a, b) => rank(a) - rank(b) || b.raised_at_s - a.raised_at_s || b.id - a.id);
  return open.map((alarm) => ({
    id: alarm.id,
    severity: alarm.severity,
    state: alarm.state,
    name: ALARM_NAMES[alarm.kind] ?? alarm.kind,
    subject: eventSubject(alarm, layout),
    age: `open for ${(snapshot.time_s - alarm.raised_at_s).toFixed(1)} s`,
    selection: alarm.baggage_id !== null ? { kind: 'bag', id: alarm.baggage_id }
      : alarm.element_id !== null ? { kind: 'belt', id: alarm.element_id } : null,
    acknowledgeable: alarm.state === 'active',
  }));
}

// The note beside the title.
export function alarmsNote(rows) {
  if (rows.length === 0) return 'None open';
  const waiting = rows.filter((row) => row.acknowledgeable).length;
  return `${rows.length} open · ${waiting} to acknowledge`;
}

// Draws the list into its element. Rows are kept by alarm id and updated
// in place, so a button is not replaced between a press and its release.
export function createAlarmList(element, { onCommand, onSelect }) {
  const note = element.querySelector('#alarms-note');
  const list = element.querySelector('#alarm-list');
  const all = element.querySelector('#acknowledge-all');
  const items = new Map();   // alarm id → { item, parts }
  let rows = [];
  let connected = false;

  const empty = document.createElement('li');
  empty.className = 'empty';
  empty.textContent = 'No open alarms.';

  all.addEventListener('click', () => {
    for (const row of rows) if (row.acknowledgeable) onCommand({ type: 'acknowledge_alarm', alarm_id: row.id });
  });

  function rowItem(row) {
    const item = document.createElement('li');
    const name = document.createElement('span');
    name.className = 'name';
    const subject = document.createElement('span');
    subject.className = 'subject';
    const state = document.createElement('span');
    state.className = 'state';
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Acknowledge';
    button.className = 'secondary';
    item.append(name, subject, state, button);
    const parts = { name, subject, state, button, row };
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      onCommand({ type: 'acknowledge_alarm', alarm_id: parts.row.id });
    });
    item.addEventListener('click', () => {
      if (parts.row.selection) onSelect(parts.row.selection);
    });
    item.title = 'Show it on the map';
    return { item, parts };
  }

  function draw() {
    note.textContent = alarmsNote(rows);
    all.disabled = !connected || !rows.some((row) => row.acknowledgeable);
    const seen = new Set();
    const ordered = rows.map((row) => {
      seen.add(row.id);
      if (!items.has(row.id)) items.set(row.id, rowItem(row));
      const { item, parts } = items.get(row.id);
      parts.row = row;
      item.dataset.severity = row.severity;
      item.dataset.state = row.state;
      parts.name.textContent = `${row.severity === 'error' ? '✖' : '▲'} ${row.name}`;
      parts.subject.textContent = row.subject;
      parts.state.textContent = `${row.state} · ${row.age}`;
      parts.button.hidden = !row.acknowledgeable;
      parts.button.disabled = !connected;
      return item;
    });
    for (const id of [...items.keys()]) if (!seen.has(id)) items.delete(id);
    // Moves only the rows out of place: appending a node moves it.
    const wanted = ordered.length > 0 ? ordered : [empty];
    wanted.forEach((item, index) => {
      if (list.children[index] !== item) list.insertBefore(item, list.children[index] ?? null);
    });
    while (list.children.length > wanted.length) list.lastChild.remove();
  }
  draw();

  return {
    setConnected(value) {
      connected = value;
      draw();
    },
    setSnapshot(snapshot, layout) {
      rows = alarmRows(snapshot, layout);
      draw();
    },
  };
}
