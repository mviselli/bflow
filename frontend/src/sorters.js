// What each sorter shows on the map (pure, tested with node --test): a pass
// light (a photo-eye across the belt entering it), a divert gate on its
// plate and the path a diverted bag is drawn along. All of it only reads
// the bags as drawn, which come from the engine's states (playback.js) and
// carry the engine's route for each bag — its destination, or the wrong
// output when the engine missorted it. The engine has no label reader and
// no gate timings: the gate moves with the bag it diverts, so it shows the
// engine's decisions and stops when the simulation is paused.

// The photo-eye's distance before the plate, along the belt entering it.
export const EYE_BEFORE_M = 0.3;

// The outputs a bag on `belt` can reach.
function outputsAfter(belt, layout) {
  const outputs = new Set(layout.outputs.map((node) => node.id));
  if (outputs.has(belt.target_id)) return new Set([belt.target_id]);
  const next = layout.belts.filter((other) => other.id === belt.target_id
    || other.source_id === belt.target_id);
  return new Set(next.flatMap((other) => [...outputsAfter(other, layout)]));
}

// Each sorter's belts: the one entering it and its branches, each with the
// outputs it leads to and its side seen along the belt entering: 0 straight
// on, 1 to the right, -1 to the left. Sorter id → { id, position,
// incoming, branches: [{ belt, outputs, side, gapM }] }, where gapM is the
// distance from the sorter's centre to the branch's start (a side belt
// stops at the edge of the plate).
export function sorterBranches(layout) {
  return new Map(layout.sorters.map((sorter) => {
    const incoming = layout.belts.find((belt) => belt.target_id === sorter.id);
    const dIn = direction(incoming);
    const branches = layout.belts.filter((belt) => belt.source_id === sorter.id).map((belt) => {
      const d = direction(belt);
      const cross = dIn.x * d.y - dIn.y * d.x;
      const side = Math.abs(cross) < Math.SQRT1_2 ? 0 : Math.sign(cross);
      const gapM = Math.hypot(belt.start.x_m - sorter.position.x_m, belt.start.y_m - sorter.position.y_m);
      return { belt, outputs: outputsAfter(belt, layout), side, gapM };
    });
    return [sorter.id, { id: sorter.id, position: sorter.position, incoming, branches }];
  }));
}

function direction(belt) {
  const length = Math.hypot(belt.end.x_m - belt.start.x_m, belt.end.y_m - belt.start.y_m);
  return { x: (belt.end.x_m - belt.start.x_m) / length, y: (belt.end.y_m - belt.start.y_m) / length };
}

// Where the engine sends a bag: its destination, unless it was missorted.
function routeOutput(bag) {
  return bag.missorted_to_id ?? bag.destination_id;
}

// The photo-eye's place along the belt entering a sorter, `trimM` being the
// length of the belt its plate covers (beltEnds' endTrimM).
export function eyeAlong(sorter, trimM) {
  return sorter.incoming.length_m - trimM - EYE_BEFORE_M;
}

// Whether a bag covers a sorter's photo-eye.
export function eyeBlocked(sorter, trimM, bags) {
  const along = eyeAlong(sorter, trimM);
  return bags.some((bag) => bag.conveyor_id === sorter.incoming.id
    && bag.position_m <= along && bag.position_m + bag.length_m >= along);
}

// --- The gate and the path of a diverted bag ---------------------------------
//
// Positions in a sorter's frame (metres): origin at its centre, x along the
// belt entering it, y towards a side branch (mirrored for a branch on the
// left). Each side branch has a gate hinged at the plate's upstream corner
// on the far side: closed it lies along that rail, open it swings
// GATE.openRad across the plate, and the bag slides along its face into
// the branch.
export const GATE = { hinge: { x: -0.43, y: -0.36 }, lengthM: 0.93, openRad: Math.PI / 4 };

// The diverted bag's centre and heading at points along its slide: it meets
// the open gate at the first, turns along its face and leaves along the
// branch's axis at the last. In between it is drawn on straight segments
// with its heading turning evenly.
export const DIVERT_PATH = [
  { x: -0.62, y: 0, angle: 0 },
  { x: -0.3, y: 0.15, angle: (40 * Math.PI) / 180 },
  { x: 0, y: 0.5, angle: (62 * Math.PI) / 180 },
  { x: 0, y: 0.78, angle: Math.PI / 2 },
];

// The engine moves a bag from the end of the belt entering a sorter to the
// start of a branch in one tick, about 1.1 m along its route. On the divert
// route the bag is drawn catching up at most this fast (metres of route per
// simulated second), so it is seen sliding along the gate for a moment
// instead of crossing the plate at once; it is never drawn ahead of where
// the engine has it.
export const SLIDE_SPEED_M_S = 2.5;

// The route offset to draw a diverted bag at, after `dtS` more simulated
// seconds: the engine's offset `real`, or up to SLIDE_SPEED_M_S × dtS past
// the offset drawn before (`previous`) while behind it. Nothing moves while
// paused (dtS = 0); a bag seen for the first time, time going back (a
// reset) or the engine's offset going back is drawn where the engine has it.
export function followOffset(previous, real, dtS) {
  if (previous === undefined || previous === null || dtS < 0 || real < previous) return real;
  return Math.min(real, previous + SLIDE_SPEED_M_S * dtS);
}

// How the gate follows the bag it diverts, in route offsets (below): it
// opens over the bag's last GATE_TRAVEL_M before the slide, so it is fully
// open as the bag meets it, and closes over GATE_TRAVEL_M once the bag's
// rear is past it (GATE_CLEAR_M along the branch).
export const GATE_TRAVEL_M = 0.35;
export const GATE_CLEAR_M = 0.65;

// How far a bag's centre has gone along the straight route through a sorter,
// from its centre: negative on the belt entering it, positive on a branch.
// Playback moves bags at an even pace along this route; null for a bag on
// neither belt.
export function routeOffset(sorter, branch, bag) {
  const centre = bag.position_m + bag.length_m / 2;
  if (bag.conveyor_id === sorter.incoming.id) return centre - sorter.incoming.length_m;
  if (bag.conveyor_id === branch.belt.id) return branch.gapM + centre;
  return null;
}

// The side branch a bag takes at a sorter, if it takes one: the bag is on
// the belt entering it and routed to a side branch, or on a side branch.
export function sideBranchOf(sorter, bag) {
  if (bag.conveyor_id === sorter.incoming.id) {
    const branch = sorter.branches.find(({ outputs }) => outputs.has(routeOutput(bag)));
    return branch && branch.side !== 0 ? branch : null;
  }
  return sorter.branches.find(({ belt, side }) => side !== 0 && belt.id === bag.conveyor_id) ?? null;
}

// How open a side branch's gate is (0 closed along its rail, 1 fully
// across), from the bags it diverts: the most any of them needs. A bag's
// `slideOffset`, when the renderer gives one, is the offset it is drawn at.
export function gateOpening(sorter, branch, bags) {
  const meet = DIVERT_PATH[0].x;
  let opening = 0;
  for (const bag of bags) {
    if (sideBranchOf(sorter, bag) !== branch) continue;
    const offset = bag.slideOffset ?? routeOffset(sorter, branch, bag);
    const rising = (offset - (meet - GATE_TRAVEL_M)) / GATE_TRAVEL_M;
    const falling = 1 - (offset - GATE_CLEAR_M) / GATE_TRAVEL_M;
    opening = Math.max(opening, Math.min(Math.max(Math.min(rising, falling), 0), 1));
  }
  return opening;
}

// Where a bag diverted into a side branch is drawn, from its route offset:
// along DIVERT_PATH between its first and last points (in proportion to the
// straight route between them, so the pace stays even), then along the
// branch's axis, as { x, y, angle } in the sorter's frame for a branch on
// the right (side 1), mirrored for side -1; null before the slide, where
// the bag is drawn on its belt.
export function divertPose(offsetM, side) {
  const first = DIVERT_PATH[0];
  const last = DIVERT_PATH[DIVERT_PATH.length - 1];
  const straight = -first.x + last.y;  // the route's length from the first point to the last
  const progress = (offsetM - first.x) / straight;
  if (progress <= 0) return null;
  if (progress >= 1) return { x: 0, y: side * offsetM, angle: side * Math.PI / 2 };
  const lengths = DIVERT_PATH.slice(1).map((point, i) =>
    Math.hypot(point.x - DIVERT_PATH[i].x, point.y - DIVERT_PATH[i].y));
  let remaining = progress * lengths.reduce((sum, length) => sum + length, 0);
  let i = 0;
  while (i < lengths.length - 1 && remaining > lengths[i]) {
    remaining -= lengths[i];
    i += 1;
  }
  const a = DIVERT_PATH[i];
  const b = DIVERT_PATH[i + 1];
  const t = remaining / lengths[i];
  return {
    x: a.x + (b.x - a.x) * t,
    y: side * (a.y + (b.y - a.y) * t),
    angle: side * (a.angle + (b.angle - a.angle) * t),
  };
}
