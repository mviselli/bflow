// Side panel: details of the selected belt, check-in desk or bag, and the
// operator's commands for it (stop or restart a belt, fault or repair it, a
// desk's arrival rate). With nothing selected it shows the plant and its
// wrong-sorting commands, which apply to every sorter.
//
// panelContent() is pure (tested with node --test): from the selection, the
// layout and the newest snapshot it builds a title, a list of rows and the
// action available. Every value is the engine's, as the snapshot reports it;
// the page only formats it. The only subtractions are a bag's travel time so
// far (the snapshot's time minus its admission time), during a prolonged
// wait how long it has been still (the snapshot's time minus its last move),
// and how long an alarm has been open (minus its raise time). Like the
// counters, the panel shows the newest snapshot, a fraction of a second ahead
// of the picture.

import { count, formatTime } from './controls.js';

// Highest rate the slider offers, as the server accepts (MAX_RATE_BAGS_S).
export const MAX_RATE_BAGS_S = 1;
const RATE_STEP_BAGS_S = 0.05;
const MISSORT_STEP = 0.01;

export function formatRate(rate) {
  return `${rate.toFixed(2)} bags/s · ${Math.round(rate * 60)} per min`;
}

function metres(value) {
  return `${value.toFixed(1)} m`;
}

// A short name for any element a belt connects to.
export function elementName(id, layout) {
  const input = layout.inputs.find((node) => node.id === id);
  if (input) return `Check-in ${input.label}`;
  const output = layout.outputs.find((node) => node.id === id);
  if (output) return `Output ${output.label}`;
  return id;
}

// The engine's alarm kinds, as the operator reads them.
export const ALARM_NAMES = { belt_fault: 'Fault', congestion: 'Congestion', prolonged_wait: 'Prolonged wait' };

// An open alarm in words: what, its state, and how long it has been open in
// simulated time (so it stands still while paused).
export function alarmText(alarm, timeS) {
  const name = ALARM_NAMES[alarm.kind] ?? alarm.kind;
  return `${name} · ${alarm.state} · open for ${(timeS - alarm.raised_at_s).toFixed(1)} s`;
}

// The open alarms (active or acknowledged) of a belt itself, or of a bag.
function openAlarms(snapshot, { beltId = null, bagId = null }) {
  return (snapshot?.alarms ?? []).filter((alarm) => alarm.state !== 'resolved'
    && (bagId ? alarm.baggage_id === bagId : alarm.baggage_id === null && alarm.element_id === beltId));
}

// A belt's condition in words. A fault and the operator's stop are
// independent: the belt moves only when neither is set.
export function beltStateText(state) {
  if (!state) return '—';
  if (state.faulty) return state.stopped ? 'Faulty · also stopped by the operator' : 'Faulty · needs repair';
  return state.stopped ? 'Stopped by the operator' : 'Running';
}

function beltContent(id, layout, snapshot) {
  const belt = layout.belts.find((item) => item.id === id);
  if (!belt) return null;
  const state = snapshot?.belts.find((item) => item.id === id);
  const stats = snapshot?.stats.belts.find((item) => item.belt_id === id);
  const alarms = openAlarms(snapshot, { beltId: id });
  const rows = [
    { label: 'State', value: beltStateText(state) },
    {
      label: 'Congestion',
      value: !state ? '—' : state.congested ? 'Warning · was above 80 % for 10 s' : 'None',
      alert: Boolean(state?.congested),
    },
    {
      label: 'Alarms',
      value: !snapshot ? '—' : alarms.map((alarm) => alarmText(alarm, snapshot.time_s)).join('; ') || 'None',
      // Highlighted while one has not been acknowledged.
      alert: alarms.some((alarm) => alarm.state === 'active'),
    },
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
    // 'running', 'stopped' or 'faulty' (a fault wins), for the state's colour.
    state: !state ? null : state.faulty ? 'faulty' : state.stopped ? 'stopped' : 'running',
    action: state ? { kind: 'belt', beltId: id, stopped: state.stopped, faulty: state.faulty } : null,
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
  // A sorting error sends the bag to another output: said right after its destination.
  const wrong = baggage.missorted_to_id
    ? [{ label: 'Sorting error', value: `sent to ${elementName(baggage.missorted_to_id, layout)}` }]
    : [];
  // The engine's warning for a bag that has not advanced for 30 s, and
  // whether the operator has acknowledged its alarm.
  const acknowledged = openAlarms(snapshot, { bagId: id }).some((alarm) => alarm.state === 'acknowledged');
  const still = baggage.prolonged_wait
    ? [{
      label: 'Prolonged wait',
      value: `Warning · not moved for ${(snapshot.time_s - baggage.moved_at_s).toFixed(1)} s`
        + (acknowledged ? ' · acknowledged' : ''),
      alert: true,
    }]
    : [];
  return {
    title: `Bag ${id}`,
    destination: look && output ? { code: look.code, colour: look.colour, label: output.label } : null,
    missorted: Boolean(baggage.missorted_to_id),
    rows: [
      { label: 'Destination', value: output ? `Output ${output.label}` : baggage.destination_id },
      ...wrong,
      { label: 'On belt', value: baggage.conveyor_id },
      {
        label: 'Position',
        value: belt ? `${metres(baggage.position_m)} of ${metres(belt.length_m)}` : metres(baggage.position_m),
      },
      { label: 'Admitted at', value: formatTime(baggage.entered_at_s) },
      { label: 'Travel time', value: `${(snapshot.time_s - baggage.entered_at_s).toFixed(1)} s` },
      ...still,
    ],
  };
}

// The plant as a whole: the wrong-sorting probability and forced error,
// set for every sorter, and how many alarms are open.
function plantContent(layout, snapshot) {
  const stats = snapshot?.stats;
  return {
    title: 'Plant',
    hint: 'Select a bag, a belt or a check-in desk on the map to see its details here.',
    rows: [
      {
        label: 'Wrong sorting',
        value: snapshot ? `${formatPercent(snapshot.missort_probability)} of sorter passages` : '—',
      },
      {
        label: 'Forced error',
        value: !snapshot ? '—' : snapshot.missort_forced ? 'On the next bag sorted' : 'None',
        alert: Boolean(snapshot?.missort_forced),
      },
      {
        label: 'Open alarms',
        value: stats ? `${count(stats.active_errors, 'error')} · ${count(stats.active_warnings, 'warning')}` : '—',
      },
      { label: 'Sorters', value: String(layout.sorters.length) },
    ],
    action: snapshot
      ? { kind: 'missort', probability: snapshot.missort_probability, forced: snapshot.missort_forced }
      : null,
  };
}

export function formatPercent(probability) {
  return `${Math.round(probability * 100)} %`;
}

// What the panel shows: the plant when nothing is selected, null without a
// layout or for an element that is not in it.
export function panelContent(selection, layout, snapshot, destinations = new Map()) {
  if (!layout) return null;
  if (!selection) return plantContent(layout, snapshot);
  if (selection.kind === 'belt') return beltContent(selection.id, layout, snapshot);
  if (selection.kind === 'input') return inputContent(selection.id, layout, snapshot);
  return bagContent(selection.id, layout, snapshot, destinations);
}

// The commands of a belt: the operator's Stop/Restart, and a fault to
// simulate or repair. The two are independent, as in the engine.
function beltAction(onCommand) {
  const element = document.createElement('div');
  element.className = 'buttons';
  const stop = document.createElement('button');
  const fault = document.createElement('button');
  stop.type = 'button';
  fault.type = 'button';
  element.append(stop, fault);
  let current = null;
  stop.addEventListener('click', () => onCommand({
    type: current.stopped ? 'restart_belt' : 'stop_belt', belt_id: current.beltId,
  }));
  fault.addEventListener('click', () => onCommand({
    type: current.faulty ? 'repair_belt' : 'fault_belt', belt_id: current.beltId,
  }));
  return {
    element,
    update(action, connected) {
      current = action;
      stop.textContent = action.stopped ? 'Restart belt' : 'Stop belt';
      stop.className = action.stopped ? '' : 'warning';
      fault.textContent = action.faulty ? 'Repair belt' : 'Simulate a fault';
      fault.className = action.faulty ? '' : 'danger';
      stop.disabled = fault.disabled = !connected;
    },
  };
}

// The plant's wrong-sorting commands: a probability slider, sent when
// released, and a button forcing an error on the next bag sorted (disabled
// while one is pending, since repeating it does nothing).
function missortAction(onCommand) {
  const element = document.createElement('div');
  element.className = 'buttons';
  const label = document.createElement('label');
  label.className = 'rate';
  const caption = document.createElement('span');
  caption.textContent = 'Wrong sorting probability';
  const slider = document.createElement('input');
  slider.type = 'range';
  slider.min = '0';
  slider.max = '1';
  slider.step = String(MISSORT_STEP);
  const value = document.createElement('output');
  label.append(caption, slider, value);
  const force = document.createElement('button');
  force.type = 'button';
  force.className = 'danger';
  force.textContent = 'Force a wrong sorting';
  element.append(label, force);
  let dragging = false;
  slider.addEventListener('pointerdown', () => { dragging = true; });
  slider.addEventListener('pointerup', () => { dragging = false; });
  slider.addEventListener('input', () => { value.textContent = formatPercent(Number(slider.value)); });
  slider.addEventListener('change', () => {
    dragging = false;
    onCommand({ type: 'set_missort_probability', probability: Number(slider.value) });
  });
  force.addEventListener('click', () => onCommand({ type: 'force_missort' }));
  return {
    element,
    update(action, connected) {
      slider.disabled = !connected;
      force.disabled = !connected || action.forced;
      if (dragging) return;
      slider.value = String(action.probability);
      value.textContent = formatPercent(action.probability);
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
    update(action, connected) {
      current = action;
      slider.disabled = !connected;
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
  const controls = { belt: beltAction, rate: rateAction, missort: missortAction };
  let action = null;      // { key, control, current }
  let connected = false;

  function showAction(content) {
    const next = content?.action;
    const key = next && `${next.kind}:${next.beltId ?? next.inputId ?? ''}`;
    if (action?.key !== key) {
      actions.replaceChildren();
      action = null;
      if (next) {
        const control = controls[next.kind](onCommand);
        actions.append(control.element);
        action = { key, control };
      }
    }
    if (action) {
      action.current = next;
      action.control.update(next, connected);
    }
  }

  return {
    setConnected(value) {
      connected = value;
      if (action) action.control.update(action.current, connected);
    },
    show(content) {
      showAction(content);
      body.replaceChildren();
      if (!content) {
        element.dataset.state = '';
        title.textContent = 'Details';
        return;
      }
      title.textContent = content.title;
      if (content.hint) {
        const hint = document.createElement('p');
        hint.className = 'panel-hint';
        hint.textContent = content.hint;
        body.append(hint);
      }
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
      for (const { label, value, alert } of content.rows) {
        const term = document.createElement('dt');
        const detail = document.createElement('dd');
        term.textContent = label;
        detail.textContent = value;
        if (alert) detail.className = 'alert';
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
      element.dataset.state = content.state ?? (content.missorted ? 'missorted' : '');
    },
  };
}
