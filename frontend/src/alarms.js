// Open alarms page: each alarm the engine has raised and not yet resolved,
// grouped by kind (faults first), with an Acknowledge button while it is
// active. Clicking an alarm selects its belt or bag on the map, where the
// Details page offers what ends it (a repair, a restart).
//
// alarmRows() and alarmGroups() are pure (tested with node --test).
// Acknowledging only tells the engine the operator has seen the alarm: it
// stays open until its condition ends, so the list shrinks only as the
// plant recovers.

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
    kind: alarm.kind,
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

// The kinds in the order they are listed, the most serious first, with
// the group's name.
export const ALARM_GROUPS = [
  ['belt_fault', 'Faults'],
  ['congestion', 'Congestion'],
  ['prolonged_wait', 'Prolonged waits'],
];

// The rows (in alarmRows order) split by kind: one group per kind with at
// least one open alarm, in ALARM_GROUPS order, then any other kind.
export function alarmGroups(rows) {
  const known = ALARM_GROUPS.map(([kind]) => kind);
  const kinds = [...known, ...new Set(rows.map((row) => row.kind).filter((kind) => !known.includes(kind)))];
  return kinds.map((kind) => {
    const members = rows.filter((row) => row.kind === kind);
    return {
      kind,
      name: ALARM_GROUPS.find(([id]) => id === kind)?.[1] ?? kind,
      severity: members[0]?.severity ?? null,
      rows: members,
      toAcknowledge: members.filter((row) => row.acknowledgeable).length,
    };
  }).filter((group) => group.rows.length > 0);
}

// The note above the groups.
export function alarmsNote(rows) {
  if (rows.length === 0) return 'None open';
  const waiting = rows.filter((row) => row.acknowledgeable).length;
  return `${rows.length} open · ${waiting} to acknowledge`;
}

// The badge on the rail: how many alarms wait for an acknowledgement, and
// whether one of them is an error. Null when none do.
export function alarmBadge(rows) {
  const waiting = rows.filter((row) => row.acknowledgeable);
  if (waiting.length === 0) return null;
  return { count: waiting.length, severity: waiting.some((row) => row.severity === 'error') ? 'error' : 'warning' };
}

const CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6.5 9.5 5.5 5.5 5.5-5.5" /></svg>';

// Draws the groups into the page. Groups are kept by kind and rows by alarm
// id, and updated in place, so a button is not replaced between a press
// and its release. A collapsed group stays collapsed until opened again.
export function createAlarmList(element, { onCommand, onSelect, badge }) {
  const note = element.querySelector('#alarms-note');
  const container = element.querySelector('#alarm-groups');
  const all = element.querySelector('#acknowledge-all');
  const groups = new Map();  // kind → { section, parts }
  const items = new Map();   // alarm id → { item, parts }
  const collapsed = new Set();
  let rows = [];
  let connected = false;

  const empty = document.createElement('p');
  empty.className = 'empty-state';
  empty.textContent = 'No open alarms. Faults, congestion and bags stuck for 30 s show up here.';

  const acknowledge = (list) => {
    for (const row of list) if (row.acknowledgeable) onCommand({ type: 'acknowledge_alarm', alarm_id: row.id });
  };
  all.addEventListener('click', () => acknowledge(rows));

  function groupSection(kind) {
    const section = document.createElement('section');
    section.className = 'alarm-group';
    const head = document.createElement('div');
    head.className = 'alarm-group-head';
    const glyph = document.createElement('i');
    glyph.className = 'glyph';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'toggle';
    const title = document.createElement('span');
    toggle.insertAdjacentHTML('beforeend', CHEVRON);
    toggle.append(title);
    const count = document.createElement('span');
    count.className = 'count';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ghost small';
    head.append(glyph, toggle, count, button);
    const list = document.createElement('ol');
    section.append(head, list);
    const parts = { glyph, title, count, button, list, toggle, group: null };
    toggle.addEventListener('click', () => {
      if (collapsed.has(kind)) collapsed.delete(kind);
      else collapsed.add(kind);
      draw();
    });
    button.addEventListener('click', () => acknowledge(parts.group.rows));
    return { section, parts };
  }

  function rowItem(row) {
    const item = document.createElement('li');
    const subject = document.createElement('span');
    subject.className = 'subject';
    const age = document.createElement('span');
    age.className = 'age';
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Acknowledge';
    button.className = 'small';
    item.append(subject, age, button);
    const parts = { subject, age, button, row };
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

  // Puts `wanted` in `parent` in that order, moving only nodes out of place.
  function arrange(parent, wanted) {
    wanted.forEach((node, index) => {
      if (parent.children[index] !== node) parent.insertBefore(node, parent.children[index] ?? null);
    });
    while (parent.children.length > wanted.length) parent.lastChild.remove();
  }

  function draw() {
    note.textContent = alarmsNote(rows);
    all.disabled = !connected || !rows.some((row) => row.acknowledgeable);
    const shown = alarmGroups(rows);
    const seenRows = new Set();
    const sections = shown.map((group) => {
      if (!groups.has(group.kind)) groups.set(group.kind, groupSection(group.kind));
      const { section, parts } = groups.get(group.kind);
      parts.group = group;
      section.dataset.collapsed = String(collapsed.has(group.kind));
      parts.toggle.setAttribute('aria-expanded', String(!collapsed.has(group.kind)));
      parts.glyph.dataset.state = group.severity === 'error' ? 'fault' : 'warning';
      parts.glyph.classList.toggle('blinking', group.toAcknowledge > 0);
      parts.title.textContent = group.name;
      parts.count.textContent = String(group.rows.length);
      parts.button.textContent = `Acknowledge ${group.toAcknowledge}`;
      parts.button.hidden = group.toAcknowledge === 0;
      parts.button.disabled = !connected;
      const ordered = group.rows.map((row) => {
        seenRows.add(row.id);
        if (!items.has(row.id)) items.set(row.id, rowItem(row));
        const { item, parts: rowParts } = items.get(row.id);
        rowParts.row = row;
        item.dataset.state = row.state;
        rowParts.subject.textContent = row.subject;
        rowParts.age.textContent = row.acknowledgeable ? row.age : `${row.state} · ${row.age}`;
        rowParts.button.hidden = !row.acknowledgeable;
        rowParts.button.disabled = !connected;
        return item;
      });
      arrange(parts.list, ordered);
      return section;
    });
    for (const id of [...items.keys()]) if (!seenRows.has(id)) items.delete(id);
    for (const kind of [...groups.keys()]) if (!shown.some((group) => group.kind === kind)) groups.delete(kind);
    arrange(container, sections.length > 0 ? sections : [empty]);
    badge(alarmBadge(rows));
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
