// Passengers queueing at the check-in desks (pure, tested with node --test).
//
// They illustrate one engine statistic and nothing more: an input's queue
// holds its last `waiting` generated bags, first in, first out, so with the
// input's `generated` count from the snapshot the passengers in line are
// numbers generated − waiting + 1 … generated, the first one at the desk.
// Passenger n is the owner of the input's n-th bag: they join the back of
// the line when it is generated and leave the desk when it is admitted.
// A bag admitted the moment it was generated never waited, so its passenger
// is never drawn.
//
// Each change of the counts eases over STEP_S of displayed simulated time
// from the snapshot that reported it: the line steps forward and the first
// passenger walks off, with no movement the engine did not report, and
// everything stands still while the simulation is paused.

import { hashString } from './looks.js';

// Simulated seconds a step forward (or walking off, or joining) takes.
export const STEP_S = 0.8;
// Passengers drawn per desk; the others are counted on a "+N" badge.
export const MAX_SHOWN = 7;
// Changes kept behind the newest snapshot, in simulated seconds: more than
// the picture ever runs behind it (up to a few seconds at 5×) plus a step.
const KEPT_S = 10;

// Where passengers stand, in the desk's frame (metres): x along its belt
// from the input, y to the belt's right. Slot 0 is beside the weighing plate
// (assets.js draws the desk at x −1.55 … −0.16, |y| ≤ 1.05); slots 1 … the
// lane run alongside the belt in the gap to the next desk, 4 m away. A
// passenger walking off goes from slot 0 to slot −1, past the counter.
export const LANE = { y: 2.0, fromM: -0.3, pitchM: 0.55, halfWidthM: 0.38 };
const FRONT = { x: -0.47, y: 0.78 };
const AWAY = { x: -1.15, y: 1.5 };

// The queues after a snapshot: input id → { changes, seen }. `changes` are
// the counts as they changed, { timeS, admitted, generated }, oldest first;
// `seen` the passengers whose bag was waiting in a snapshot, as far as they
// can be drawn. The first snapshot of a connection gives the queue as it
// is, with nothing to ease.
export function addQueueSnapshot(queues, snapshot) {
  const next = new Map();
  for (const { input_id: id, generated, waiting } of snapshot.stats.inputs) {
    const old = queues.get(id) ?? { changes: [], seen: new Set() };
    const admitted = generated - waiting;
    let changes = old.changes;
    const last = changes[changes.length - 1];
    if (!last || last.admitted !== admitted || last.generated !== generated) {
      changes = [...changes, { timeS: snapshot.time_s, admitted, generated }];
    }
    while (changes.length > 1 && changes[1].timeS < snapshot.time_s - KEPT_S) changes = changes.slice(1);
    // Passengers admitted before the oldest change kept have long gone.
    const seen = new Set([...old.seen].filter((number) => number > changes[0].admitted));
    for (let number = admitted + 1; number <= Math.min(generated, admitted + MAX_SHOWN + 1); number += 1) {
      seen.add(number);
    }
    next.set(id, { changes, seen });
  }
  return next;
}

// Starts slowly and ends slowly, from 0 to 1.
function ease(progress) {
  const p = Math.min(Math.max(progress, 0), 1);
  return p * p * (3 - 2 * p);
}

// The admitted count as shown at timeS: each change eases from the value
// shown when it came to its own count, so changes closer together than
// STEP_S follow on smoothly.
export function shownAdmitted(changes, timeS) {
  let ramp = { from: changes[0].admitted, to: changes[0].admitted, timeS: changes[0].timeS };
  const valueAt = (t) => ramp.from + (ramp.to - ramp.from) * ease((t - ramp.timeS) / STEP_S);
  for (const change of changes.slice(1)) {
    if (change.timeS > timeS) break;
    ramp = { from: valueAt(change.timeS), to: change.admitted, timeS: change.timeS };
  }
  return valueAt(timeS);
}

// The passengers of one queue at the displayed time timeS, as { number,
// slot, alpha } (slot as in queuePoint, fractional while walking), and how
// many more wait than are drawn.
export function passengersAt(queue, timeS) {
  const { changes, seen } = queue;
  const current = changes.findLast((change) => change.timeS <= timeS) ?? changes[0];
  const advance = shownAdmitted(changes, timeS);
  const passengers = [];
  for (const number of [...seen].sort((a, b) => a - b)) {
    if (number > current.generated) continue;  // their bag is not generated yet at timeS
    const slot = number - 1 - advance;
    if (slot <= -1 || slot >= MAX_SHOWN) continue;
    // Joining: fades in from the change that generated the bag, unless the
    // passenger was already in line in the first snapshot received.
    const joined = changes.find((change) => change.generated >= number);
    const joining = joined === changes[0] ? 1 : ease((timeS - joined.timeS) / STEP_S);
    // Walking off below slot 0; coming into view from beyond the last slot.
    const shown = slot < 0 ? 1 + slot : Math.min(1, MAX_SHOWN - slot);
    passengers.push({ number, slot, alpha: shown * joining });
  }
  const waiting = current.generated - current.admitted;
  return { passengers, extra: Math.max(waiting - MAX_SHOWN, 0) };
}

// A slot's point in the desk's frame.
function slotPoint(index) {
  if (index < 0) return AWAY;
  if (index === 0) return FRONT;
  return { x: LANE.fromM + LANE.pitchM * (index - 1), y: LANE.y };
}

// Where a passenger at a (fractional) slot stands in the desk's frame, and
// the way they face: towards the plate at the desk, otherwise the way they
// walk (forward along the line, or off).
export function queuePoint(slot) {
  const below = Math.floor(slot);
  const from = slotPoint(below);
  const to = slotPoint(below + 1);
  const fraction = slot - below;
  const point = { x: from.x + (to.x - from.x) * fraction, y: from.y + (to.y - from.y) * fraction };
  let facing = -Math.PI / 2;  // towards the plate, at -y
  if (slot < 0) facing = Math.atan2(AWAY.y - FRONT.y, AWAY.x - FRONT.x);
  else if (slot > 0) {
    const ahead = slotPoint(Math.ceil(slot) - 1);
    const behind = slotPoint(Math.ceil(slot));
    facing = Math.atan2(ahead.y - behind.y, ahead.x - behind.x);
  }
  return { ...point, facing };
}

// A point of a desk's frame on the map: the desk's input at `position`, its
// belt leaving at `angle`.
export function deskToMap(position, angle, point) {
  return {
    x_m: position.x_m + point.x * Math.cos(angle) - point.y * Math.sin(angle),
    y_m: position.y_m + point.x * Math.sin(angle) + point.y * Math.cos(angle),
  };
}

// Muted colours, none of them the console's state colours (blue, amber,
// red), so a passenger never reads as an alarm.
export const COAT_COLOURS = ['#4d5866', '#6b5048', '#4e6658', '#776a55', '#5d5669', '#3f454d', '#857b6e', '#5a6a72'];
export const HAIR_COLOURS = ['#2a211c', '#4b3426', '#86683f', '#1c1c1e', '#b7b0a3'];
export const SKIN_COLOURS = ['#e3bb99', '#c68e69', '#8f5c3d', '#f0cfb4', '#a8724f'];

// A passenger's look, fixed by their desk and number.
export function passengerLook(inputId, number) {
  const hash = hashString(`${inputId}#${number}`);
  return {
    coat: COAT_COLOURS[hash % COAT_COLOURS.length],
    hair: HAIR_COLOURS[(hash >>> 4) % HAIR_COLOURS.length],
    skin: SKIN_COLOURS[(hash >>> 8) % SKIN_COLOURS.length],
  };
}
