// Metres → pixels conversion and time formatting, with Node's built-in runner.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  PLANT_MARGIN_M, baggagePlacement, beltAngle, beltEnds, jointPoint, plantBounds, plantGeometry,
  plantJoints, pointAlong,
} from '../src/geometry.js';
import { formatTime } from '../src/controls.js';

const point = (x_m, y_m) => ({ x_m, y_m });

function belt(id, source_id, target_id, start, end) {
  const length_m = Math.hypot(end.x_m - start.x_m, end.y_m - start.y_m);
  return { id, source_id, target_id, start, end, length_m, speed_m_s: 1 };
}

// One belt that turns a corner: input-a (0, 0) → (10, 0) → (10, 4) → output-1.
const CORNER = {
  inputs: [{ id: 'input-a', label: 'A', position: point(0, 0) }],
  merges: [],
  sorters: [],
  outputs: [{ id: 'output-1', label: 'BF 101', position: point(10, 4) }],
  belts: [
    belt('across', 'input-a', 'down', point(0, 0), point(10, 0)),
    belt('down', 'across', 'output-1', point(10, 0), point(10, 4)),
  ],
};

// The compact test plant as the server sends it: rows at y = 0, 4, 8, x from 0 to 28.
const PLANT = {
  inputs: ['a', 'b', 'c'].map((letter, i) => ({
    id: `input-${letter}`, label: letter.toUpperCase(), position: point(0, 4 * i),
  })),
  merges: [{ id: 'merge', position: point(8, 4) }],
  sorters: [{ id: 'sorter', position: point(20, 4) }],
  outputs: [1, 2, 3].map((n, i) => ({ id: `output-${n}`, label: `BF ${n}`, position: point(28, 4 * i) })),
  belts: [
    belt('feeder-a-1', 'input-a', 'feeder-a-2', point(0, 0), point(8, 0)),
    belt('feeder-a-2', 'feeder-a-1', 'merge', point(8, 0), point(8, 4)),
    belt('feeder-b', 'input-b', 'merge', point(0, 4), point(8, 4)),
    belt('feeder-c-1', 'input-c', 'feeder-c-2', point(0, 8), point(8, 8)),
    belt('feeder-c-2', 'feeder-c-1', 'merge', point(8, 8), point(8, 4)),
    belt('collector', 'merge', 'sorter', point(8, 4), point(20, 4)),
    belt('branch-1-1', 'sorter', 'branch-1-2', point(20, 4), point(20, 0)),
    belt('branch-1-2', 'branch-1-1', 'output-1', point(20, 0), point(28, 0)),
    belt('branch-2', 'sorter', 'output-2', point(20, 4), point(28, 4)),
    belt('branch-3-1', 'sorter', 'branch-3-2', point(20, 4), point(20, 8)),
    belt('branch-3-2', 'branch-3-1', 'output-3', point(20, 8), point(28, 8)),
  ],
};

const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} ≠ ${expected}`);

test('the bounds hold every node and belt end', () => {
  assert.deepEqual(plantBounds(PLANT), { left: 0, top: 0, right: 28, bottom: 8 });
  assert.deepEqual(plantBounds(CORNER), { left: 0, top: 0, right: 10, bottom: 4 });
});

test('the plant and its margins fit the width, centred', () => {
  // 28 m + margins across 1000 px; the height leaves room to spare.
  const widthM = 28 + 2 * PLANT_MARGIN_M;
  const geometry = plantGeometry(PLANT, 1000, 800);
  close(geometry.pixelsPerMetre, 1000 / widthM);
  close(geometry.toScreen(point(0, 0)).x, PLANT_MARGIN_M * geometry.pixelsPerMetre);
  close(geometry.toScreen(point(28, 0)).x, 1000 - PLANT_MARGIN_M * geometry.pixelsPerMetre);
  close(geometry.toScreen(point(14, 4)).y, 400);
});

test('a short screen limits the scale and keeps the plant centred', () => {
  const heightM = 8 + 2 * PLANT_MARGIN_M;
  const geometry = plantGeometry(PLANT, 2000, heightM * 20);
  close(geometry.pixelsPerMetre, 20);
  close(geometry.toScreen(point(14, 4)).x, 1000);
  close(geometry.toScreen(point(0, 0)).y, PLANT_MARGIN_M * 20);
});

test('map lengths keep their proportion on screen', () => {
  const geometry = plantGeometry(PLANT, 1000, 800);
  const a = geometry.toScreen(point(8, 4));
  const b = geometry.toScreen(point(20, 4));
  close(b.x - a.x, geometry.toPixels(12));
});

test('belt directions follow the map, with y downwards', () => {
  const [feederA1, feederA2, , , feederC2, , branch11] = PLANT.belts;
  close(beltAngle(feederA1), 0);
  close(beltAngle(feederA2), Math.PI / 2);
  close(beltAngle(feederC2), -Math.PI / 2);
  close(beltAngle(branch11), -Math.PI / 2);
});

test('positions along a belt go from its start to its end', () => {
  const down = CORNER.belts[1];
  assert.deepEqual(pointAlong(down, 0), point(10, 0));
  assert.deepEqual(pointAlong(down, 1), point(10, 1));
  assert.deepEqual(pointAlong(down, 4), point(10, 4));
});

test('a bag is drawn centred on the middle of its length', () => {
  const geometry = plantGeometry(CORNER, 1000, 800);
  const across = CORNER.belts[0];
  const down = CORNER.belts[1];
  // Front edge at the end of the first belt: centre 0.3 m before the corner.
  const atCorner = baggagePlacement(geometry, across, { position_m: 9.4, length_m: 0.6 });
  const corner = geometry.toScreen(point(9.7, 0));
  close(atCorner.x, corner.x);
  close(atCorner.y, corner.y);
  close(atCorner.angle, 0);
  // Rear edge at the start of the next belt: centre 0.3 m below the corner.
  const turned = baggagePlacement(geometry, down, { position_m: 0, length_m: 0.6 });
  const below = geometry.toScreen(point(10, 0.3));
  close(turned.x, below.x);
  close(turned.y, below.y);
  close(turned.angle, Math.PI / 2);
});

test('the minimum gap between bags keeps its proportion on screen', () => {
  const geometry = plantGeometry(CORNER, 1000, 800);
  const down = CORNER.belts[1];
  const ahead = baggagePlacement(geometry, down, { position_m: 2.0, length_m: 0.6 });
  const behind = baggagePlacement(geometry, down, { position_m: 1.2, length_m: 0.6 });
  // Centres 0.8 m apart: 0.6 m of bag plus the 0.2 m gap.
  close(ahead.y - behind.y, geometry.toPixels(0.8));
});

test('belt ends at inputs and outputs are free, the others are joints', () => {
  const ends = beltEnds(PLANT);
  const half = { startTrimM: 0, endTrimM: 0.5 };
  assert.deepEqual(ends.get('feeder-a-1'), { startJoint: false, endJoint: true, ...half });
  assert.deepEqual(ends.get('feeder-b'), { startJoint: false, endJoint: true, ...half });
  assert.deepEqual(ends.get('collector'),
    { startJoint: true, endJoint: true, startTrimM: 0.5, endTrimM: 0.5 });
  assert.deepEqual(ends.get('branch-2'),
    { startJoint: true, endJoint: false, startTrimM: 0.5, endTrimM: 0 });
});

// A side join as in the demo plant: a desk's feeder comes down and stops at
// the edge of the merge's plate; the collector passes through its centre.
const SIDE_JOIN = {
  inputs: [
    { id: 'input-a1', label: 'A1', position: point(2, 0) },
    { id: 'input-a2', label: 'A2', position: point(6, 0) },
  ],
  merges: [{ id: 'merge-a2', position: point(6, 4) }],
  sorters: [],
  outputs: [{ id: 'output-1', label: 'BF 101', position: point(10, 4) }],
  belts: [
    belt('feeder-a1', 'input-a1', 'island-a-1', point(2, 0), point(2, 4)),
    belt('island-a-1', 'feeder-a1', 'merge-a2', point(2, 4), point(6, 4)),
    belt('feeder-a2', 'input-a2', 'merge-a2', point(6, 0), point(6, 3.5)),
    belt('island-a-2', 'merge-a2', 'output-1', point(6, 4), point(10, 4)),
  ],
};

test('a belt stopping at the edge of a plate is not covered by it', () => {
  const ends = beltEnds(SIDE_JOIN);
  assert.equal(ends.get('feeder-a2').endTrimM, 0);
  assert.equal(ends.get('island-a-1').endTrimM, 0.5);
  assert.equal(ends.get('island-a-2').startTrimM, 0.5);
});

test('a plate is open on the sides its belts come from, even from the edge', () => {
  const merge = plantJoints(SIDE_JOIN).find((joint) => joint.id === 'merge-a2');
  const sides = merge.directions
    .map((angle) => (((Math.round(angle / (Math.PI / 2)) % 4) + 4) % 4)).sort();
  assert.deepEqual(sides, [0, 2, 3]);  // out right, in from the left, in from above
});

test('the joint between two belts is where their lines cross', () => {
  const [, islandA1, feederA2, islandA2] = SIDE_JOIN.belts;
  assert.deepEqual(jointPoint(feederA2, islandA2), point(6, 4));
  assert.deepEqual(jointPoint(islandA1, islandA2), point(6, 4));
  assert.deepEqual(jointPoint(...CORNER.belts), point(10, 0));
});

test('joints are the merges, the sorters and the corners, with their open sides', () => {
  const joints = plantJoints(PLANT);
  assert.deepEqual(joints.map((joint) => joint.id),
    ['merge', 'sorter', 'feeder-a-1>feeder-a-2', 'feeder-c-1>feeder-c-2',
      'branch-1-1>branch-1-2', 'branch-3-1>branch-3-2']);
  // Directions in which belts leave each joint, as multiples of a right angle.
  const sides = (joint) => joint.directions
    .map((angle) => (((Math.round(angle / (Math.PI / 2)) % 4) + 4) % 4)).sort();
  assert.deepEqual(sides(joints[0]), [0, 1, 2, 3]);     // merge: from three sides, out right
  assert.deepEqual(sides(joints[1]), [0, 1, 2, 3]);     // sorter: in from the left, out three ways
  assert.deepEqual(sides(joints[2]), [1, 2]);           // corner: from the left, then down
  assert.deepEqual(sides(joints[4]), [0, 1]);           // corner: from below, then right
});

test('an empty layout is rejected', () => {
  assert.throws(() => plantBounds({ inputs: [], merges: [], sorters: [], outputs: [], belts: [] }));
});

test('simulated time is shown as minutes and seconds', () => {
  assert.equal(formatTime(0), '00:00.00');
  assert.equal(formatTime(1.05), '00:01.05');
  assert.equal(formatTime(61.5), '01:01.50');
  assert.equal(formatTime(600), '10:00.00');
});
