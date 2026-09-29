// Turns the server's snapshots into smooth movement, without inventing any.
//
// Snapshots arrive about 12 times per real second, each one describing the
// simulation at one tick. Drawing them as they arrive makes the bags jump.
// Instead, the page keeps a display clock in simulated seconds that runs a
// little behind the newest snapshot (DISPLAY_DELAY_S): at any moment it falls
// between two snapshots already received, and every bag is drawn between the
// two positions the engine actually reported. The clock never goes past the
// newest snapshot, so nothing is ever extrapolated: when the simulation is
// paused the clock reaches the paused tick and stops there.
//
// This module is pure (no DOM, no PixiJS): the caller passes the real time in
// seconds, which keeps it testable with node --test.

// How far the display clock stays behind the newest snapshot: about two
// snapshot intervals, so a late snapshot does not stop the movement.
export const DISPLAY_DELAY_S = 0.15;
// Beyond this distance from its target the clock jumps instead of catching up
// (a hidden tab, a connection that stalled): no quick replay of old frames.
export const MAX_DRIFT_S = 0.5;
// Fraction of the remaining distance recovered per real second, so the clock
// follows the server gently when it runs slightly faster or slower.
const CATCH_UP_PER_S = 2;
// Snapshots older than this behind the newest are no longer needed.
const HISTORY_S = 1;
// A long pause between two frames (tab in the background) counts as this much.
const MAX_FRAME_S = 0.1;

export function createPlayback() {
  let snapshots = [];      // received snapshots, oldest first, strictly increasing ticks
  let displayTime = null;  // simulated seconds being drawn
  let lastFrame = null;    // real seconds of the previous frame
  let arrival = null;      // real seconds when the newest snapshot arrived

  function newest() {
    return snapshots[snapshots.length - 1];
  }

  // Simulated time the display clock is heading to. While running, the
  // server has simulated about as long as the real time since the newest
  // snapshot arrived; while paused no newer snapshot will come, so the clock
  // finishes at the paused tick.
  function target(nowS) {
    const latest = newest();
    if (!latest.running) return latest.time_s;
    return latest.time_s + (nowS - arrival) - DISPLAY_DELAY_S;
  }

  function reset() {
    snapshots = [];
    displayTime = null;
    lastFrame = null;
    arrival = null;
  }

  return {
    // Forgets everything, e.g. on a new connection.
    reset,

    // Stores a snapshot received at the real time nowS (seconds).
    add(snapshot, nowS) {
      // The server's time never goes back; if it does (a restarted server),
      // the old snapshots describe another run: start over.
      if (snapshots.length > 0 && snapshot.tick < newest().tick) reset();
      const latest = newest();
      if (latest && snapshot.tick === latest.tick) snapshots[snapshots.length - 1] = snapshot;
      else {
        snapshots.push(snapshot);
        arrival = nowS;
      }
      while (snapshots.length > 2 && snapshot.time_s - snapshots[1].time_s > HISTORY_S) {
        snapshots.shift();
      }
      if (arrival === null) arrival = nowS;
      if (displayTime === null) displayTime = snapshot.time_s;
    },

    // Advances the display clock to the real time nowS and returns the
    // simulated time to draw, or null before the first snapshot.
    advance(nowS) {
      if (displayTime === null) return null;
      const frameS = lastFrame === null ? 0 : Math.min(Math.max(nowS - lastFrame, 0), MAX_FRAME_S);
      lastFrame = nowS;

      // The simulation runs at 1×: one simulated second per real second,
      // plus a gentle correction towards the target.
      const goal = target(nowS);
      const next = displayTime + frameS;
      const error = goal - next;
      displayTime = Math.abs(error) > MAX_DRIFT_S
        ? goal
        : next + error * Math.min(1, CATCH_UP_PER_S * frameS);
      // Only draw times covered by the snapshots received.
      displayTime = Math.min(Math.max(displayTime, snapshots[0].time_s), newest().time_s);
      return displayTime;
    },

    // Bags to draw at simulated time timeS, each with its interpolated belt,
    // position_m and an opacity: a bag that changes belt slides across the
    // joint (see interpolateBaggage), one that enters or leaves the plant
    // between two snapshots fades in or out in place instead of popping.
    // `belts` maps belt ids to the layout's belts.
    baggageAt(timeS, belts) {
      if (snapshots.length === 0) return [];
      let after = snapshots.findIndex((snapshot) => snapshot.time_s >= timeS);
      if (after === -1) after = snapshots.length - 1;
      const next = snapshots[after];
      const previous = snapshots[Math.max(after - 1, 0)];
      const span = next.time_s - previous.time_s;
      const fraction = span > 0 ? Math.min(Math.max((timeS - previous.time_s) / span, 0), 1) : 1;
      return interpolateBaggage(previous.baggage, next.baggage, fraction, belts);
    },
  };
}

// True when a bag can pass from belt `from` straight onto belt `to`: `to`
// follows `from`, or `from` ends at the merge or sorter that `to` leaves.
export function isNextBelt(from, to, belts) {
  if (to.source_id === from.id) return true;
  return to.source_id === from.target_id && !belts.has(from.target_id);
}

// A bag that passed from one belt to the next between two snapshots. The
// engine moves it to the end of the old belt, then puts its rear edge at the
// start of the new one (a jump of about one bag length, an accepted
// approximation). On screen its centre slides at an even pace along the
// belts, from its old centre to the point where they meet and on to its new
// centre: the same two states, with no movement beyond them. The returned
// position_m keeps the engine's meaning (rear edge along the belt it is
// drawn on), even where it runs a little past the belt's ends.
function acrossBelts(old, baggage, from, fraction) {
  const half = baggage.length_m / 2;
  const toJoint = Math.max(from.length_m - (old.position_m + half), 0);
  const fromJoint = Math.max(baggage.position_m + half, 0);
  const travelled = (toJoint + fromJoint) * fraction;
  if (travelled < toJoint) {
    return { ...baggage, conveyor_id: from.id, position_m: old.position_m + travelled, alpha: 1 };
  }
  return { ...baggage, position_m: travelled - toJoint - half, alpha: 1 };
}

// Bags between two snapshots, fraction 0 → previous, 1 → next. `belts`
// (belt id → belt from the layout) lets a bag slide from one belt onto the
// next; without it, or when the two belts are not consecutive, the bag fades.
export function interpolateBaggage(previousBags, nextBags, fraction, belts = new Map()) {
  const before = new Map(previousBags.map((baggage) => [baggage.id, baggage]));
  const result = [];
  for (const baggage of nextBags) {
    const old = before.get(baggage.id);
    before.delete(baggage.id);
    const from = old && belts.get(old.conveyor_id);
    const to = belts.get(baggage.conveyor_id);
    if (old && old.conveyor_id === baggage.conveyor_id) {
      const position = old.position_m + (baggage.position_m - old.position_m) * fraction;
      result.push({ ...baggage, position_m: position, alpha: 1 });
    } else if (from && to && isNextBelt(from, to, belts)) {
      result.push(acrossBelts(old, baggage, from, fraction));
    } else {
      result.push({ ...baggage, alpha: fraction });  // admitted in between
    }
  }
  // Bags that left the plant in between (delivered).
  for (const baggage of before.values()) result.push({ ...baggage, alpha: 1 - fraction });
  return result.filter((baggage) => baggage.alpha > 0);
}

// Offset of the belt surface in metres, in [0, repeatM): the rubber moves
// with the belt speed and the simulated time, so it stops when time stops.
export function beltOffset(speedMS, timeS, repeatM) {
  return (speedMS * timeS) % repeatM;
}
