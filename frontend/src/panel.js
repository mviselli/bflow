// Side panel: details of the selected belt, check-in desk or bag, and the
// operator's commands for it (stop or restart a belt, a desk's arrival rate).
//
// panelContent() is pure (tested with node --test): from the selection, the
// layout and the newest snapshot it builds a title, a list of rows and the
// action available. Every value is the engine's, as the snapshot reports it;
// the page only formats it. The one subtraction is a bag's travel time so
// far, the snapshot's time minus the bag's admission time. Like the
// counters, the panel shows the newest snapshot, a fraction of a second ahead
// of the picture.

import { formatTime } from './controls.js';

// Highest rate the slider offers, as the server accepts (MAX_RATE_BAGS_S).
export const MAX_RATE_BAGS_S = 1;
const RATE_STEP_BAGS_S = 0.05;

export function formatRate(rate) {
  return `${rate.toFixed(2)} bags/s · ${Math.round(rate * 60)} per min`;
}

function metres(value) {
  return `${value.toFixed(1)} m`;
}

// A short name for any element a belt connects to.
function elementName(id, layout) {
  const input = layout.inputs.find((node) => node.id === id);
  if (input) return `Check-in ${input.label}`;
  const output = layout.outputs.find((node) => node.id === id);
  if (output) return `Output ${output.label}`;
  return id;
}

function beltContent(id, layout, snapshot) {
  const belt = layout.belts.find((item) => item.id === id);
  if (!belt) return null;
  const state = snapshot?.belts.find((item) => item.id === id);
  const stats = snapshot?.stats.belts.find((item) => item.belt_id === id);
  const rows = [
    { label: 'State', value: state ? (state.stopped ? 'Stopped by the operator' : 'Running') : '—' },
    { label: 'Bags', value: stats ? `${stats.bags} of ${stats.capacity}` : '—' },
    { label: 'Occupancy', value: stats ? `${Math.round(stats.occupancy * 100)} %` : '—' },
    { label: 'Length', value: metres(belt.length_m) },
    { label: 'Speed', value: `${belt.speed_m_s.toFixed(1)} m/s` },
    { label: 'From', value: elementName(belt.source_id, layout) },
    { label: 'To', value: elementName(belt.target_id, layout) },
  ];
  return {
    title: `Belt ${id}`,
    rows,
    occupancy: stats ? stats.occupancy : null,
    stopped: state?.stopped ?? false,
    action: state ? { kind: 'belt', beltId: id, stopped: state.stopped } : null,
  };
}

function inputContent(id, layout, snapshot) {
  const input = layout.inputs.find((node) => node.id === id);
  if (!input) return null;
  const rate = snapshot?.inputs.find((node) => node.id === id)?.arrival_rate_bags_s;
  const waiting = snapshot?.stats.inputs.find((node) => node.input_id === id)?.waiting;
  const belt = layout.belts.find((item) => item.source_id === id);
  return {
    title: `Check-in ${input.label}`,
    rows: [
      { label: 'Waiting', value: waiting === undefined ? '—' : String(waiting) },
      { label: 'Arrival rate', value: rate === undefined ? '—' : formatRate(rate) },
      { label: 'Feeds belt', value: belt ? belt.id : '—' },
    ],
    action: rate === undefined ? null : { kind: 'rate', inputId: id, rate },
  };
}

function bagContent(id, layout, snapshot, destinations) {
  const baggage = snapshot?.baggage.find((bag) => bag.id === id);
  if (!baggage) {
    return { title: `Bag ${id}`, rows: [{ label: 'State', value: 'No longer in the plant' }] };
  }
  const output = layout.outputs.find((node) => node.id === baggage.destination_id);
  const belt = layout.belts.find((item) => item.id === baggage.conveyor_id);
  const look = destinations.get(baggage.destination_id);
  return {
    title: `Bag ${id}`,
    destination: look && output ? { code: look.code, colour: look.colour, label: output.label } : null,
    rows: [
      { label: 'Destination', value: output ? `Output ${output.label}` : baggage.destination_id },
      { label: 'On belt', value: baggage.conveyor_id },
      {
        label: 'Position',
        value: belt ? `${metres(baggage.position_m)} of ${metres(belt.length_m)}` : metres(baggage.position_m),
      },
      { label: 'Admitted at', value: formatTime(baggage.entered_at_s) },
      { label: 'Travel time', value: `${(snapshot.time_s - baggage.entered_at_s).toFixed(1)} s` },
    ],
  };
}

// What the panel shows: null when nothing (valid) is selected.
export function panelContent(selection, layout, snapshot, destinations = new Map()) {
  if (!selection || !layout) return null;
  if (selection.kind === 'belt') return beltContent(selection.id, layout, snapshot);
  if (selection.kind === 'input') return inputContent(selection.id, layout, snapshot);
  return bagContent(selection.id, layout, snapshot, destinations);
}

// The Stop/Restart button of a belt.
function beltAction(onCommand) {
  const button = document.createElement('button');
  button.type = 'button';
  let current = null;
  button.addEventListener('click', () => onCommand({
    type: current.stopped ? 'restart_belt' : 'stop_belt', belt_id: current.beltId,
  }));
  return {
    element: button,
    update(action) {
      current = action;
      button.textContent = action.stopped ? 'Restart belt' : 'Stop belt';
      button.className = action.stopped ? '' : 'warning';
    },
  };
}

// The arrival-rate slider of a desk: sends the new rate when released, and
// follows the engine's rate otherwise.
function rateAction(onCommand) {
  const label = document.createElement('label');
  label.className = 'rate';
  const caption = document.createElement('span');
  caption.textContent = 'Set the arrival rate';
  const slider = document.createElement('input');
  slider.type = 'range';
  slider.min = '0';
  slider.max = String(MAX_RATE_BAGS_S);
  slider.step = String(RATE_STEP_BAGS_S);
  const value = document.createElement('output');
  label.append(caption, slider, value);
  let current = null;
  let dragging = false;
  slider.addEventListener('pointerdown', () => { dragging = true; });
  slider.addEventListener('pointerup', () => { dragging = false; });
  slider.addEventListener('input', () => { value.textContent = formatRate(Number(slider.value)); });
  slider.addEventListener('change', () => {
    dragging = false;
    onCommand({ type: 'set_rate', input_id: current.inputId, rate_bags_s: Number(slider.value) });
  });
  return {
    element: label,
    update(action) {
      current = action;
      if (dragging) return;
      slider.value = String(action.rate);
      value.textContent = formatRate(action.rate);
    },
  };
}

// Draws the content into the panel element. The action control is kept
// while the same element stays selected, so a slider being dragged or a
// focused button is not rebuilt at every snapshot.
export function createPanel(element, { onCommand = () => {} } = {}) {
  const title = element.querySelector('#panel-title');
  const body = element.querySelector('#panel-body');
  const actions = element.querySelector('#panel-actions');
  let action = null;      // { key, control }
  let connected = false;

  function showAction(content) {
    const next = content?.action;
    const key = next && `${next.kind}:${next.beltId ?? next.inputId}`;
    if (action?.key !== key) {
      actions.replaceChildren();
      action = null;
      if (next) {
        const control = next.kind === 'belt' ? beltAction(onCommand) : rateAction(onCommand);
        actions.append(control.element);
        action = { key, control };
      }
    }
    if (action) {
      action.control.update(next);
      for (const input of actions.querySelectorAll('button, input')) input.disabled = !connected;
    }
  }

  return {
    setConnected(value) {
      connected = value;
      for (const input of actions.querySelectorAll('button, input')) input.disabled = !connected;
    },
    show(content) {
      showAction(content);
      body.replaceChildren();
      if (!content) {
        title.textContent = 'Details';
        const hint = document.createElement('p');
        hint.textContent = 'Select a bag, a belt or a check-in desk on the map to see its details here.';
        body.append(hint);
        return;
      }
      title.textContent = content.title;
      if (content.destination) {
        const tag = document.createElement('p');
        tag.className = 'panel-tag';
        const code = document.createElement('span');
        code.textContent = content.destination.code;
        code.style.background = content.destination.colour;
        tag.append(code, ` ${content.destination.label}`);
        body.append(tag);
      }
      const list = document.createElement('dl');
      for (const { label, value } of content.rows) {
        const term = document.createElement('dt');
        const detail = document.createElement('dd');
        term.textContent = label;
        detail.textContent = value;
        list.append(term, detail);
      }
      body.append(list);
      if (content.occupancy !== null && content.occupancy !== undefined) {
        // A bar filled up to the occupancy (the browser's <meter> looks full when empty).
        const bar = document.createElement('div');
        bar.className = 'occupancy';
        bar.setAttribute('role', 'meter');
        bar.setAttribute('aria-label', 'Occupancy');
        bar.setAttribute('aria-valuemin', '0');
        bar.setAttribute('aria-valuemax', '100');
        bar.setAttribute('aria-valuenow', String(Math.round(content.occupancy * 100)));
        const fill = document.createElement('span');
        fill.style.width = `${Math.min(content.occupancy, 1) * 100}%`;
        bar.append(fill);
        body.append(bar);
      }
      element.dataset.stopped = content.stopped ? 'true' : 'false';
    },
  };
}
