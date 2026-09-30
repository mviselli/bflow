// Side panel: details of the selected belt or bag.
//
// panelContent() is pure (tested with node --test): from the selection, the
// layout and the newest snapshot it builds a title and a list of rows. Every
// value is the engine's, as the snapshot reports it; the page only formats
// it. The one subtraction is a bag's travel time so far, the snapshot's time
// minus the bag's admission time. Like the counters, the panel shows the
// newest snapshot, a fraction of a second ahead of the picture.

import { formatTime } from './controls.js';

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
  return bagContent(selection.id, layout, snapshot, destinations);
}

// Draws the content into the panel element.
export function createPanel(element) {
  const title = element.querySelector('#panel-title');
  const body = element.querySelector('#panel-body');

  return {
    show(content) {
      body.replaceChildren();
      if (!content) {
        title.textContent = 'Details';
        const hint = document.createElement('p');
        hint.textContent = 'Select a bag or a belt on the map to see its details here.';
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
