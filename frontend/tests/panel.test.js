// Side panel content, with Node's built-in runner.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { destinationLooks } from '../src/looks.js';
import { panelContent } from '../src/panel.js';

const point = (x_m, y_m) => ({ x_m, y_m });

// input-a → feeder → merge → line → output-1, as the server describes it.
const LAYOUT = {
  inputs: [{ id: 'input-a', label: 'A1', position: point(0, 0) }],
  merges: [],
  sorters: [],
  outputs: [{ id: 'output-1', label: 'BF 101', position: point(10, 0) }],
  belts: [
    { id: 'line', source_id: 'input-a', target_id: 'output-1', start: point(0, 0), end: point(5, 0),
      length_m: 5, speed_m_s: 1 },
  ],
};

function snapshot({
  stopped = false, faulty = false, congested = false, bags = 3, missortedTo = null, waiting = false,
} = {}) {
  return {
    tick: 400,
    time_s: 20,
    running: true,
    speed: 1,
    inputs: [{ id: 'input-a', arrival_rate_bags_s: 0.15 }],
    belts: [{ id: 'line', stopped, faulty, congested }],
    baggage: [{
      id: 'bag-7', destination_id: 'output-1', conveyor_id: 'line', position_m: 3.25,
      length_m: 0.6, entered_at_s: 12.5, missorted_to_id: missortedTo,
      moved_at_s: waiting ? 13.75 : 20, prolonged_wait: waiting,
    }],
    stats: {
      belts: [{ belt_id: 'line', bags, capacity: 6, occupancy: bags / 6 }],
      inputs: [{ input_id: 'input-a', waiting: 4 }],
    },
  };
}

const values = (content) => Object.fromEntries(content.rows.map(({ label, value }) => [label, value]));

test('nothing selected shows nothing', () => {
  assert.equal(panelContent(null, LAYOUT, snapshot()), null);
  assert.equal(panelContent({ kind: 'belt', id: 'line' }, null, snapshot()), null);
});

test('a belt shows its state, occupancy and connections from the snapshot', () => {
  const content = panelContent({ kind: 'belt', id: 'line' }, LAYOUT, snapshot());
  assert.equal(content.title, 'Belt line');
  assert.deepEqual(values(content), {
    State: 'Running', Congestion: 'None', Bags: '3 of 6', Occupancy: '50 %', Length: '5.0 m', Speed: '1.0 m/s',
    From: 'Check-in A1', To: 'Output BF 101',
  });
  assert.equal(content.occupancy, 0.5);
  assert.equal(content.state, 'running');
  assert.deepEqual(content.action, { kind: 'belt', beltId: 'line', stopped: false });
});

test('a stopped belt says so', () => {
  const content = panelContent({ kind: 'belt', id: 'line' }, LAYOUT, snapshot({ stopped: true }));
  assert.equal(values(content).State, 'Stopped by the operator');
  assert.equal(content.state, 'stopped');
  assert.deepEqual(content.action, { kind: 'belt', beltId: 'line', stopped: true });
});

test('a congested belt shows the warning, highlighted', () => {
  const content = panelContent({ kind: 'belt', id: 'line' }, LAYOUT, snapshot({ congested: true, bags: 6 }));
  const row = content.rows.find((item) => item.label === 'Congestion');
  assert.deepEqual(row, { label: 'Congestion', value: 'Warning · was above 80 % for 10 s', alert: true });
  assert.equal(values(content).State, 'Running');
});

test('a faulty belt says so, and a fault wins over the operator\'s stop', () => {
  const faulty = panelContent({ kind: 'belt', id: 'line' }, LAYOUT, snapshot({ faulty: true }));
  assert.equal(values(faulty).State, 'Faulty · needs repair');
  assert.equal(faulty.state, 'faulty');
  const both = panelContent({ kind: 'belt', id: 'line' }, LAYOUT, snapshot({ stopped: true, faulty: true }));
  assert.equal(values(both).State, 'Faulty · also stopped by the operator');
  assert.equal(both.state, 'faulty');
});

test('before the first snapshot a belt shows its layout only', () => {
  const content = panelContent({ kind: 'belt', id: 'line' }, LAYOUT, null);
  assert.equal(values(content).State, '—');
  assert.equal(values(content).Length, '5.0 m');
  assert.equal(content.occupancy, null);
  // No command until the engine's state is known.
  assert.equal(content.action, null);
});

test('a bag shows its destination, place and travel time so far', () => {
  const destinations = destinationLooks(LAYOUT.outputs);
  const content = panelContent({ kind: 'bag', id: 'bag-7' }, LAYOUT, snapshot(), destinations);
  assert.equal(content.title, 'Bag bag-7');
  assert.deepEqual(content.destination, { code: '1', colour: destinations.get('output-1').colour, label: 'BF 101' });
  assert.deepEqual(values(content), {
    Destination: 'Output BF 101', 'On belt': 'line', Position: '3.3 m of 5.0 m',
    'Admitted at': '00:12.50', 'Travel time': '7.5 s',
  });
});

test('a missorted bag shows where the sorting error sent it', () => {
  const layout = { ...LAYOUT, outputs: [...LAYOUT.outputs, { id: 'output-2', label: 'BF 205', position: point(5, 3) }] };
  const content = panelContent({ kind: 'bag', id: 'bag-7' }, layout, snapshot({ missortedTo: 'output-2' }));
  assert.deepEqual(content.rows.slice(0, 2), [
    { label: 'Destination', value: 'Output BF 101' },
    { label: 'Sorting error', value: 'sent to Output BF 205' },
  ]);
  assert.equal(content.missorted, true);
});

test('a bag in a prolonged wait shows how long it has been still, highlighted', () => {
  const content = panelContent({ kind: 'bag', id: 'bag-7' }, LAYOUT, snapshot({ waiting: true }));
  assert.deepEqual(content.rows.at(-1), {
    label: 'Prolonged wait', value: 'Warning · not moved for 6.3 s', alert: true,
  });
  const moving = panelContent({ kind: 'bag', id: 'bag-7' }, LAYOUT, snapshot());
  assert.ok(!moving.rows.some((row) => row.label === 'Prolonged wait'));
});

test('a bag that has left the plant says so', () => {
  const content = panelContent({ kind: 'bag', id: 'bag-99' }, LAYOUT, snapshot());
  assert.deepEqual(values(content), { State: 'No longer in the plant' });
});

test('a check-in desk shows its queue and rate, and offers to change the rate', () => {
  const content = panelContent({ kind: 'input', id: 'input-a' }, LAYOUT, snapshot());
  assert.equal(content.title, 'Check-in A1');
  assert.deepEqual(values(content), {
    Waiting: '4', 'Arrival rate': '0.15 bags/s · 9 per min', 'Feeds belt': 'line',
  });
  assert.deepEqual(content.action, { kind: 'rate', inputId: 'input-a', rate: 0.15 });
});

test('a bag offers no command', () => {
  const content = panelContent({ kind: 'bag', id: 'bag-7' }, LAYOUT, snapshot());
  assert.equal(content.action, undefined);
});
