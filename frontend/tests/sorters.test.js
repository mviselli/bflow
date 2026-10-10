// Sorter pass lights and divert flaps.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  CLEAR_M, EYE_BEFORE_M, FLAP_SWING_S, LOOKAHEAD_M, eyeAlong, eyeBlocked, flapTargets, sorterBranches,
  stepFlap,
} from '../src/sorters.js';

function belt(id, source, target, [x1, y1], [x2, y2]) {
  return {
    id, source_id: source, target_id: target, start: { x_m: x1, y_m: y1 }, end: { x_m: x2, y_m: y2 },
    length_m: Math.hypot(x2 - x1, y2 - y1), speed_m_s: 1,
  };
}

// A sort line like the demo plant's: line-1 into sorter s1, a branch down
// to output-1, line-2 on to sorter s2 with a branch up to output-2 and
// line-3 straight on to output-3.
const layout = {
  inputs: [{ id: 'input-a', position: { x_m: 0, y_m: 0 } }],
  outputs: ['output-1', 'output-2', 'output-3'].map((id) => ({ id })),
  merges: [],
  sorters: [{ id: 's1', position: { x_m: 6, y_m: 0 } }, { id: 's2', position: { x_m: 11, y_m: 0 } }],
  belts: [
    belt('line-1', 'input-a', 's1', [0, 0], [6, 0]),
    belt('branch-1', 's1', 'output-1', [6, 0.5], [6, 5]),
    belt('line-2', 's1', 's2', [6, 0], [11, 0]),
    belt('branch-2', 's2', 'output-2', [11, -0.5], [11, -5]),
    belt('line-3', 's2', 'output-3', [11, 0], [16, 0]),
  ],
};

function bag(id, conveyor, position, destination, missorted = null) {
  return { id, conveyor_id: conveyor, position_m: position, length_m: 0.6, destination_id: destination, missorted_to_id: missorted };
}

test('each sorter knows its branches, the outputs past them and their side', () => {
  const sorters = sorterBranches(layout);
  const s1 = sorters.get('s1');
  assert.equal(s1.incoming.id, 'line-1');
  assert.deepEqual(s1.branches.map(({ belt: { id }, outputs, side }) => [id, [...outputs].sort(), side]), [
    ['branch-1', ['output-1'], 1],             // down, to the right of travel
    ['line-2', ['output-2', 'output-3'], 0],   // straight on, to both later outputs
  ]);
  assert.deepEqual(sorters.get('s2').branches.map(({ side }) => side), [-1, 0]);
});

test('the flap is set for the route of the bag coming within LOOKAHEAD_M', () => {
  const sorters = sorterBranches(layout);
  const end = 6 - 0.6;
  // Too far: no target, the flap stays where it is.
  assert.deepEqual(flapTargets(sorters, [bag('b1', 'line-1', end - LOOKAHEAD_M - 0.01, 'output-1')]), new Map());
  const near = flapTargets(sorters, [bag('b1', 'line-1', end - LOOKAHEAD_M + 0.01, 'output-1')]);
  assert.deepEqual(near, new Map([['s1', 'branch-1']]));
  // The frontmost bag wins; s2 is set for the bag coming to it.
  const two = flapTargets(sorters, [
    bag('b1', 'line-1', end, 'output-3'), bag('b2', 'line-1', end - 1, 'output-1'),
    bag('b3', 'line-2', 4.5, 'output-2'),
  ]);
  assert.deepEqual(two, new Map([['s1', 'line-2'], ['s2', 'branch-2']]));
});

test('a missorted bag turns the flap to the wrong branch the engine chose', () => {
  const sorters = sorterBranches(layout);
  const targets = flapTargets(sorters, [bag('b1', 'line-1', 5.4, 'output-1', 'output-3')]);
  assert.equal(targets.get('s1'), 'line-2');
});

test('a bag still leaving the plate holds the flap against the next one', () => {
  const sorters = sorterBranches(layout);
  const leaving = bag('b1', 'branch-1', CLEAR_M - 0.01, 'output-1');
  const next = bag('b2', 'line-1', 5, 'output-2');
  assert.equal(flapTargets(sorters, [next, leaving]).get('s1'), 'branch-1');
  assert.equal(flapTargets(sorters, [next, { ...leaving, position_m: CLEAR_M }]).get('s1'), 'line-2');
});

test('the flap swings at a steady pace, stops at its target and snaps on a reset', () => {
  assert.equal(stepFlap(0, 1, FLAP_SWING_S / 2), 0.5);
  assert.equal(stepFlap(0.5, 1, FLAP_SWING_S), 1);
  assert.equal(stepFlap(1, 0, FLAP_SWING_S / 4), 0.75);
  assert.equal(stepFlap(0.4, 0.4, 1), 0.4);
  assert.equal(stepFlap(0.3, 0, 0), 0.3);  // paused: no movement
  assert.equal(stepFlap(0.3, 1, -5), 1);
});

test('the photo-eye lights while a bag covers it, just before the plate', () => {
  const sorter = sorterBranches(layout).get('s1');
  const along = eyeAlong(sorter, 0.5);
  assert.equal(along, 6 - 0.5 - EYE_BEFORE_M);
  assert.ok(!eyeBlocked(sorter, 0.5, [bag('b1', 'line-1', along - 0.61, 'output-1')]));
  assert.ok(eyeBlocked(sorter, 0.5, [bag('b1', 'line-1', along - 0.6, 'output-1')]));
  assert.ok(eyeBlocked(sorter, 0.5, [bag('b1', 'line-1', along, 'output-1')]));
  assert.ok(!eyeBlocked(sorter, 0.5, [bag('b1', 'line-1', along + 0.01, 'output-1')]));
  // A bag on another belt does not count.
  assert.ok(!eyeBlocked(sorter, 0.5, [bag('b1', 'line-2', 0, 'output-2')]));
});
