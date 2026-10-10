// Passengers queueing at the check-in desks.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  addQueueSnapshot, deskToMap, MAX_SHOWN, passengerLook, passengersAt, queuePoint, shownAdmitted,
  STEP_S,
} from '../src/passengers.js';

function snapshot(timeS, inputs) {
  return {
    time_s: timeS,
    stats: { inputs: Object.entries(inputs).map(([id, [generated, waiting]]) => ({ input_id: id, generated, waiting })) },
  };
}

// The queues after each snapshot in turn: [timeS, { id: [generated, waiting] }].
function feed(...steps) {
  return steps.reduce((queues, [timeS, inputs]) => addQueueSnapshot(queues, snapshot(timeS, inputs)), new Map());
}

function slots(queue, timeS) {
  return passengersAt(queue, timeS).passengers.map(({ number, slot }) => [number, slot]);
}

test('the line holds the bags still waiting: the oldest one at the desk', () => {
  // 10 generated, 3 waiting: bags 8, 9 and 10 wait, bag 8 at the desk.
  const queue = feed([5, { a: [10, 3] }]).get('a');
  assert.deepEqual(slots(queue, 5), [[8, 0], [9, 1], [10, 2]]);
  assert.deepEqual(passengersAt(queue, 5).passengers.map(({ alpha }) => alpha), [1, 1, 1]);
  assert.equal(passengersAt(queue, 5).extra, 0);
});

test('nobody queues while every bag is admitted at once', () => {
  const queue = feed([1, { a: [4, 0] }], [2, { a: [5, 0] }], [3, { a: [7, 0] }]).get('a');
  for (const timeS of [1, 2, 2.5, 3, 4]) assert.deepEqual(slots(queue, timeS), []);
});

test('when the first bag is admitted its passenger walks off and the line steps forward over STEP_S', () => {
  const queue = feed([0, { a: [10, 3] }], [1, { a: [10, 2] }]).get('a');
  // Nothing moves before the snapshot that reported the admission.
  assert.deepEqual(slots(queue, 0.9), [[8, 0], [9, 1], [10, 2]]);
  assert.deepEqual(slots(queue, 1), [[8, 0], [9, 1], [10, 2]]);
  const half = passengersAt(queue, 1 + STEP_S / 2).passengers;
  assert.deepEqual(half.map(({ number, slot }) => [number, slot]), [[8, -0.5], [9, 0.5], [10, 1.5]]);
  assert.equal(half[0].alpha, 0.5);  // fading as they leave
  // Done: passenger 8 has gone.
  assert.deepEqual(slots(queue, 1 + STEP_S), [[9, 0], [10, 1]]);
  assert.deepEqual(slots(queue, 30), [[9, 0], [10, 1]]);
});

test('a new passenger joins the back of the line, fading in', () => {
  const queue = feed([0, { a: [10, 2] }], [1, { a: [11, 3] }]).get('a');
  assert.deepEqual(slots(queue, 0.5), [[9, 0], [10, 1]]);
  const joining = passengersAt(queue, 1 + STEP_S / 2).passengers;
  assert.deepEqual(joining.map(({ number, slot }) => [number, slot]), [[9, 0], [10, 1], [11, 2]]);
  assert.deepEqual(joining.map(({ alpha }) => Math.round(alpha * 1e9) / 1e9), [1, 1, 0.5]);
  assert.equal(passengersAt(queue, 1 + STEP_S).passengers[2].alpha, 1);
});

test('changes closer together than STEP_S follow on without a jump', () => {
  const changes = [
    { timeS: 0, admitted: 5, generated: 9 },
    { timeS: 1, admitted: 6, generated: 9 },
    { timeS: 1 + STEP_S / 2, admitted: 7, generated: 9 },
  ];
  const before = shownAdmitted(changes, 1 + STEP_S / 2 - 1e-9);
  const after = shownAdmitted(changes, 1 + STEP_S / 2);
  assert.ok(Math.abs(after - before) < 1e-6);
  assert.equal(after, 5.5);
  assert.equal(shownAdmitted(changes, 1 + STEP_S / 2 + STEP_S), 7);
  // Always moving forward in between.
  let last = 5;
  for (let t = 0; t <= 3; t += 0.05) {
    const value = shownAdmitted(changes, t);
    assert.ok(value >= last - 1e-9);
    last = value;
  }
});

test('beyond MAX_SHOWN passengers the others are counted, and each comes into view as the line moves', () => {
  const queue = feed([0, { a: [20, 12] }], [1, { a: [20, 11] }]).get('a');
  const start = passengersAt(queue, 0);
  assert.deepEqual(start.passengers.map(({ number }) => number), [9, 10, 11, 12, 13, 14, 15]);
  assert.equal(start.extra, 12 - MAX_SHOWN);
  const moving = passengersAt(queue, 1 + STEP_S / 2).passengers;
  const last = moving[moving.length - 1];
  assert.deepEqual([last.number, last.slot, last.alpha], [16, MAX_SHOWN - 0.5, 0.5]);
  assert.equal(passengersAt(queue, 1 + STEP_S).extra, 11 - MAX_SHOWN);
});

test('every input has its own queue, and old changes are dropped', () => {
  const queues = feed([0, { a: [3, 1], b: [3, 0] }], [5, { a: [4, 1], b: [3, 0] }],
    [20, { a: [5, 2], b: [3, 0] }]);
  assert.deepEqual(slots(queues.get('a'), 20 + STEP_S), [[4, 0], [5, 1]]);
  assert.deepEqual(slots(queues.get('b'), 20), []);
  // The change at 0 s ended long before the picture: the one at 5 s is the base.
  assert.deepEqual(queues.get('a').changes.map(({ timeS }) => timeS), [5, 20]);
  assert.deepEqual([...queues.get('a').seen].sort(), [4, 5]);
});

test('the queue runs from beside the plate into the lane, everyone facing the way to the desk', () => {
  const front = queuePoint(0);
  assert.equal(front.facing, -Math.PI / 2);
  assert.ok(front.x < 0 && front.y > 0.5 && front.y < 1.05);
  const lane = [1, 2, 3, MAX_SHOWN - 1].map(queuePoint);
  assert.ok(lane.every((point) => point.y === lane[0].y && point.y > 1.05 + 0.3 && point.y < 4 - 1.05 - 0.3));
  assert.ok(lane.slice(1).every((point) => Math.abs(Math.abs(point.facing) - Math.PI) < 1e-9));
  // Halfway between two slots, halfway between their points.
  const half = queuePoint(1.5);
  assert.ok(Math.abs(half.x - (lane[0].x + lane[1].x) / 2) < 1e-9);
  // Walking off: away from the plate.
  assert.ok(queuePoint(-0.5).x < front.x);
});

test('desk frame points land on the map around the input, turned with its belt', () => {
  const near = (point, x, y) => Math.abs(point.x_m - x) < 1e-9 && Math.abs(point.y_m - y) < 1e-9;
  // A belt leaving downwards: its right is the map's -x.
  assert.ok(near(deskToMap({ x_m: 6, y_m: 0 }, Math.PI / 2, { x: 1, y: 2 }), 4, 1));
  assert.ok(near(deskToMap({ x_m: 6, y_m: 12 }, -Math.PI / 2, { x: 1, y: 2 }), 8, 11));
});

test('a passenger always looks the same', () => {
  assert.deepEqual(passengerLook('input-a1', 7), passengerLook('input-a1', 7));
  const looks = new Set(Array.from({ length: 40 }, (_, n) => JSON.stringify(passengerLook('input-a1', n))));
  assert.ok(looks.size > 10);
});
