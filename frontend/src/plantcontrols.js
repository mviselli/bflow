// Controls page of the side panel: every command of the plant in one place,
// without looking for the element on the map first. Three views:
// - Desks: the arrival rate of each check-in desk, and its queue;
// - Belts: each belt's light and state, Stop/Restart and Fault/Repair;
// - Sorting: the wrong sorting probability and a forced error.
//
// deskRows(), beltRows() and sortingState() are pure (tested with node
// --test): they read the layout and the newest snapshot, and the page only
// formats what they return. The commands are the same ones the Details page
// sends for a selected element.

import { rateAction, beltStateText, elementName, formatPercent } from './panel.js';
import { beltLights } from './signals.js';

const MISSORT_STEP = 0.01;

// Each check-in desk, in layout order, with its queue and rate (null
// before the first snapshot).
export function deskRows(layout, snapshot) {
  return layout.inputs.map((input) => ({
    id: input.id,
    name: elementName(input.id, layout),
    waiting: snapshot?.stats.inputs.find((node) => node.input_id === input.id)?.waiting ?? null,
    rate: snapshot?.inputs.find((node) => node.id === input.id)?.arrival_rate_bags_s ?? null,
  }));
}

// Each belt, in layout order: its light (as on the map), its state in
// words and what its two buttons do.
export function beltRows(layout, snapshot) {
  const lights = snapshot ? beltLights(snapshot) : new Map();
  return layout.belts.map((belt) => {
    const state = snapshot?.belts.find((item) => item.id === belt.id);
    const text = beltStateText(state);
    return {
      id: belt.id,
      light: lights.get(belt.id) ?? { state: 'running', blinking: false },
      text: state?.congested ? `${text} · congested` : text,
      stopped: Boolean(state?.stopped),
      faulty: Boolean(state?.faulty),
      known: Boolean(state),
    };
  });
}

// The wrong sorting settings, or null before the first snapshot.
export function sortingState(snapshot) {
  if (!snapshot) return null;
  return { probability: snapshot.missort_probability, forced: snapshot.missort_forced };
}

// The wrong sorting commands: a probability slider, sent when released,
// and a button forcing an error on the next bag sorted (disabled while one
// is pending, since repeating it does nothing).
function sortingControls(element, onCommand) {
  const label = document.createElement('label');
  label.className = 'rate';
  const caption = document.createElement('span');
  caption.textContent = 'Wrong sorting probability';
  const value = document.createElement('output');
  const slider = document.createElement('input');
  slider.type = 'range';
  slider.min = '0';
  slider.max = '1';
  slider.step = String(MISSORT_STEP);
  label.append(caption, value, slider);
  const force = document.createElement('button');
  force.type = 'button';
  force.className = 'danger';
  force.textContent = 'Force a wrong sorting';
  const pending = document.createElement('p');
  pending.className = 'forced';
  pending.textContent = 'The next bag sorted will go down a wrong branch.';
  element.append(label, force, pending);
  let dragging = false;
  slider.addEventListener('pointerdown', () => { dragging = true; });
  slider.addEventListener('pointerup', () => { dragging = false; });
  slider.addEventListener('input', () => { value.textContent = formatPercent(Number(slider.value)); });
  slider.addEventListener('change', () => {
    dragging = false;
    onCommand({ type: 'set_missort_probability', probability: Number(slider.value) });
  });
  force.addEventListener('click', () => onCommand({ type: 'force_missort' }));
  return function update(state, connected) {
    slider.disabled = !connected || !state;
    force.disabled = !connected || !state || state.forced;
    pending.hidden = !state?.forced;
    if (dragging || !state) return;
    slider.value = String(state.probability);
    value.textContent = formatPercent(state.probability);
  };
}

// Draws the page. Rows are built once per layout and updated in place, so
// a slider being dragged or a button being pressed is never replaced.
export function createPlantControls(element, { onCommand, onSelect }) {
  const tabs = [...element.querySelectorAll('.tabs button')];
  const views = [...element.querySelectorAll('.view')];
  const deskList = element.querySelector('#desk-list');
  const beltList = element.querySelector('#belt-list');
  const updateSorting = sortingControls(element.querySelector('#sorting-controls'), onCommand);
  let layout = null;
  let snapshot = null;
  let connected = false;
  let desks = new Map();   // input id → { waiting, rate control }
  let belts = new Map();   // belt id → { glyph, state, stop, fault, row }

  for (const tab of tabs) {
    tab.addEventListener('click', () => {
      for (const other of tabs) other.setAttribute('aria-pressed', String(other === tab));
      for (const view of views) view.hidden = view.dataset.view !== tab.dataset.view;
    });
  }

  function deskItem(row) {
    const item = document.createElement('li');
    const head = document.createElement('div');
    head.className = 'desk-head';
    const name = document.createElement('b');
    name.textContent = row.name;
    const waiting = document.createElement('span');
    waiting.className = 'waiting';
    head.append(name, waiting);
    const rate = rateAction(onCommand, `Arrival rate of ${row.name}`);
    item.append(head, rate.element);
    deskList.append(item);
    return { waiting, rate };
  }

  function beltItem(row) {
    const item = document.createElement('li');
    const glyph = document.createElement('i');
    glyph.className = 'glyph';
    const name = document.createElement('button');
    name.type = 'button';
    name.className = 'name';
    name.title = 'Show it on the map';
    const title = document.createElement('span');
    title.textContent = row.id;
    const state = document.createElement('small');
    name.append(title, state);
    const stop = document.createElement('button');
    stop.type = 'button';
    stop.className = 'small';
    const fault = document.createElement('button');
    fault.type = 'button';
    fault.className = 'small';
    item.append(glyph, name, stop, fault);
    beltList.append(item);
    const parts = { glyph, state, stop, fault, row };
    name.addEventListener('click', () => onSelect({ kind: 'belt', id: parts.row.id }));
    stop.addEventListener('click', () => onCommand({
      type: parts.row.stopped ? 'restart_belt' : 'stop_belt', belt_id: parts.row.id,
    }));
    fault.addEventListener('click', () => onCommand({
      type: parts.row.faulty ? 'repair_belt' : 'fault_belt', belt_id: parts.row.id,
    }));
    return parts;
  }

  function draw() {
    if (!layout) return;
    for (const row of deskRows(layout, snapshot)) {
      const desk = desks.get(row.id);
      desk.waiting.textContent = row.waiting === null ? '' : `${row.waiting} waiting`;
      if (row.waiting > 0) desk.waiting.dataset.alert = '';
      else delete desk.waiting.dataset.alert;
      if (row.rate !== null) desk.rate.update({ inputId: row.id, rate: row.rate }, connected);
    }
    for (const row of beltRows(layout, snapshot)) {
      const belt = belts.get(row.id);
      belt.row = row;
      belt.glyph.dataset.state = row.light.state;
      belt.glyph.classList.toggle('blinking', row.light.blinking);
      belt.state.textContent = row.text;
      belt.stop.textContent = row.stopped ? 'Restart' : 'Stop';
      belt.stop.className = row.stopped ? 'small primary' : 'small';
      belt.fault.textContent = row.faulty ? 'Repair' : 'Fault';
      // Not red: twenty red buttons would shout. Red is for faults themselves.
      belt.fault.className = row.faulty ? 'small primary' : 'small ghost';
      belt.stop.disabled = belt.fault.disabled = !connected || !row.known;
    }
    updateSorting(sortingState(snapshot), connected);
  }

  return {
    setLayout(message) {
      layout = message;
      snapshot = null;
      deskList.replaceChildren();
      beltList.replaceChildren();
      desks = new Map(deskRows(layout, null).map((row) => [row.id, deskItem(row)]));
      belts = new Map(beltRows(layout, null).map((row) => [row.id, beltItem(row)]));
      draw();
    },
    setSnapshot(message) {
      snapshot = message;
      draw();
    },
    setConnected(value) {
      connected = value;
      draw();
    },
  };
}
