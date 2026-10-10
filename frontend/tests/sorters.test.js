// Sorter pass lights and divert flaps.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  DIVERT_PATH, EYE_BEFORE_M, GATE, GATE_CLEAR_M, GATE_TRAVEL_M, SLIDE_SPEED_M_S, divertPose, eyeAlong,
  eyeBlocked, followOffset, gateOpening, routeOffset, sideBranchOf, sorterBranches,
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
  assert.deepEqual(s1.branches.map(({ belt: { id }, outputs, side, gapM }) => [id, [...outputs].sort(), side, gapM]), [
    ['branch-1', ['output-1'], 1, 0.5],          // down, to the right of travel, from the plate's edge
    ['line-2', ['output-2', 'output-3'], 0, 0],  // straight on, to both later outputs
  ]);
  assert.deepEqual(sorters.get('s2').branches.map(({ side }) => side), [-1, 0]);
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

test('a bag goes along one route through the sorter: negative before its centre, positive on the branch', () => {
  const sorter = sorterBranches(layout).get('s1');
  const branch = sorter.branches[0];
  assert.ok(Math.abs(routeOffset(sorter, branch, bag('b', 'line-1', 5.4, 'output-1')) + 0.3) < 1e-9);
  assert.ok(Math.abs(routeOffset(sorter, branch, bag('b', 'branch-1', 0, 'output-1')) - 0.8) < 1e-9);
  assert.equal(routeOffset(sorter, branch, bag('b', 'line-2', 0, 'output-2')), null);
});

test('only bags taking a side branch slide along the gate', () => {
  const s1 = sorterBranches(layout).get('s1');
  assert.equal(sideBranchOf(s1, bag('b', 'line-1', 5, 'output-1')).belt.id, 'branch-1');
  assert.equal(sideBranchOf(s1, bag('b', 'line-1', 5, 'output-3')), null);           // straight on
  assert.equal(sideBranchOf(s1, bag('b', 'line-1', 5, 'output-3', 'output-1')).belt.id, 'branch-1');  // missorted
  assert.equal(sideBranchOf(s1, bag('b', 'branch-1', 0.1, 'output-1')).belt.id, 'branch-1');
  assert.equal(sideBranchOf(s1, bag('b', 'line-2', 0.1, 'output-2')), null);
});

test('the slide joins the straight route at both ends, without a jump', () => {
  const first = DIVERT_PATH[0];
  const last = DIVERT_PATH[DIVERT_PATH.length - 1];
  assert.equal(divertPose(first.x, 1), null);
  // Past the slide: on the branch's axis.
  assert.deepEqual(divertPose(1.5, 1), { x: 0, y: 1.5, angle: Math.PI / 2 });
  const start = divertPose(first.x + 1e-6, 1);
  assert.ok(Math.hypot(start.x - first.x, start.y) < 1e-4 && Math.abs(start.angle) < 1e-4);
  const end = divertPose(last.y - 1e-6, 1);
  assert.ok(Math.hypot(end.x, end.y - last.y) < 1e-4 && Math.abs(end.angle - Math.PI / 2) < 1e-4);
  // Small steps of the route give small steps of the picture, the heading always turning one way.
  let previous = start;
  for (let offset = first.x + 0.01; offset < last.y; offset += 0.01) {
    const pose = divertPose(offset, 1);
    assert.ok(Math.hypot(pose.x - previous.x, pose.y - previous.y) < 0.025);
    assert.ok(pose.angle >= previous.angle - 1e-9);
    previous = pose;
  }
  // A branch on the left is the mirror image.
  const right = divertPose(0, 1);
  const left = divertPose(0, -1);
  assert.deepEqual([left.x, left.y, left.angle], [right.x, -right.y, -right.angle]);
});

test('a sliding bag stays clear of the open gate', () => {
  const half = { length: 0.3, width: 0.225 };
  const gate = Array.from({ length: 41 }, (_, i) => ({
    x: GATE.hinge.x + (GATE.lengthM * i / 40) * Math.cos(GATE.openRad),
    y: GATE.hinge.y + (GATE.lengthM * i / 40) * Math.sin(GATE.openRad),
  }));
  for (let offset = -0.61; offset < 0.78; offset += 0.01) {
    const pose = divertPose(offset, 1);
    for (const point of gate) {
      // The gate point in the bag's own frame.
      const dx = point.x - pose.x;
      const dy = point.y - pose.y;
      const along = dx * Math.cos(pose.angle) + dy * Math.sin(pose.angle);
      const across = -dx * Math.sin(pose.angle) + dy * Math.cos(pose.angle);
      const inside = Math.abs(along) < half.length - 0.01 && Math.abs(across) < half.width - 0.01;
      assert.ok(!inside, `gate point (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) inside the bag at offset ${offset.toFixed(2)}`);
    }
  }
  // Before the slide the bag runs straight past the closed gate's line.
  assert.ok(Math.abs(GATE.hinge.y) - 0.04 > half.width);
  // While the gate opens the bag is still running straight: clear of the
  // gate at the angle it has reached.
  const sorter = sorterBranches(layout).get('s1');
  const meet = DIVERT_PATH[0].x;
  for (let offset = meet - GATE_TRAVEL_M; offset <= meet; offset += 0.01) {
    const angle = gateOpening(sorter, sorter.branches[0], [bag('b', 'line-1', 6 + offset - 0.3, 'output-1')]) * GATE.openRad;
    for (let i = 0; i <= 40; i += 1) {
      const x = GATE.hinge.x + (GATE.lengthM * i / 40) * Math.cos(angle);
      const y = GATE.hinge.y + (GATE.lengthM * i / 40) * Math.sin(angle);
      const inside = Math.abs(x - offset) < half.length - 0.01 && Math.abs(y) < half.width - 0.01;
      assert.ok(!inside, `gate inside the bag while opening, offset ${offset.toFixed(2)}`);
    }
  }
});

test('the gate opens with the bag it diverts and closes once that bag is past it', () => {
  const sorter = sorterBranches(layout).get('s1');
  const branch = sorter.branches[0];
  const meet = DIVERT_PATH[0].x;
  // A bag on line-1 whose centre is `offset` from the sorter's centre.
  const at = (offset, destination = 'output-1', missorted = null) =>
    bag('b', 'line-1', 6 + offset - 0.3, destination, missorted);
  const opening = (bags) => gateOpening(sorter, branch, bags);
  const close = (a, b) => Math.abs(a - b) < 1e-9;
  assert.equal(opening([at(meet - GATE_TRAVEL_M - 0.1)]), 0);
  assert.ok(close(opening([at(meet - GATE_TRAVEL_M / 2)]), 0.5));
  assert.ok(close(opening([at(meet)]), 1));        // fully open as the bag meets it
  assert.ok(close(opening([at(-0.3)]), 1));
  // On the branch: still open until the bag's rear is past, then closing.
  const onBranch = (offset) => bag('b', 'branch-1', offset - 0.5 - 0.3, 'output-1');
  assert.ok(close(opening([onBranch(GATE_CLEAR_M)]), 1));
  assert.ok(close(opening([onBranch(GATE_CLEAR_M + GATE_TRAVEL_M / 2)]), 0.5));
  assert.equal(opening([onBranch(GATE_CLEAR_M + GATE_TRAVEL_M)]), 0);
  // Bags going straight on leave it closed; a bag the engine missorted into
  // the branch opens it, one missorted away from it does not.
  assert.equal(opening([at(-0.3, 'output-3')]), 0);
  assert.ok(close(opening([at(-0.3, 'output-3', 'output-1')]), 1));
  assert.equal(opening([at(-0.3, 'output-1', 'output-3')]), 0);
  // Two bags in a row: it stays open for the second.
  assert.ok(close(opening([onBranch(GATE_CLEAR_M + GATE_TRAVEL_M), at(meet)]), 1));
});

test('a diverted bag catches up the one-tick transfer at SLIDE_SPEED_M_S, never ahead of the engine', () => {
  // The engine moves the bag from -0.3 to 0.8 in one tick: it is drawn
  // sliding there instead.
  assert.equal(followOffset(-0.3, 0.8, 0.1), -0.3 + SLIDE_SPEED_M_S * 0.1);
  assert.equal(followOffset(0.7, 0.85, 0.1), 0.85);   // caught up: on the engine's offset
  assert.equal(followOffset(0.2, 0.9, 0), 0.2);       // paused: stays where it is
  assert.equal(followOffset(undefined, 0.8, 0.1), 0.8);  // first seen
  assert.equal(followOffset(0.2, 0.9, -3), 0.9);      // time went back: a reset
  assert.equal(followOffset(0.5, 0.1, 0.1), 0.1);     // the engine's offset went back
  // Moving with its belt (1 m/s), a bag is followed exactly.
  let drawn = -2;
  for (let t = 0.05; t < 1; t += 0.05) {
    drawn = followOffset(drawn, -2 + t, 0.05);
    assert.ok(Math.abs(drawn - (-2 + t)) < 1e-9);
  }
});
