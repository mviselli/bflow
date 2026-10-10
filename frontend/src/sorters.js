// What each sorter shows on the map (pure, tested with node --test): a pass
// light (a photo-eye across the belt entering it) and a divert flap on its
// plate. Both only read the bags as drawn, which come from the engine's
// states (playback.js): the flap turns towards the branch of the bag about
// to pass, following the engine's route for it — its destination, or the
// wrong output when the engine missorted it — and the eye lights while a
// bag covers it. The engine has no label reader and no flap timings; these
// only show its decisions.

// A bag this close to the end of the belt entering a sorter sets the flap.
export const LOOKAHEAD_M = 2.5;
// A bag this far onto a belt leaving the sorter still holds the flap.
export const CLEAR_M = 0.6;
// Simulated seconds the flap takes to swing fully open or closed.
export const FLAP_SWING_S = 0.35;
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
// incoming, branches: [{ belt, outputs, side }] }.
export function sorterBranches(layout) {
  return new Map(layout.sorters.map((sorter) => {
    const incoming = layout.belts.find((belt) => belt.target_id === sorter.id);
    const dIn = direction(incoming);
    const branches = layout.belts.filter((belt) => belt.source_id === sorter.id).map((belt) => {
      const d = direction(belt);
      const cross = dIn.x * d.y - dIn.y * d.x;
      const side = Math.abs(cross) < Math.SQRT1_2 ? 0 : Math.sign(cross);
      return { belt, outputs: outputsAfter(belt, layout), side };
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

// The branch each sorter's flap should be set for, from the bags as drawn:
// a bag still leaving the plate holds it, otherwise the frontmost bag
// coming within LOOKAHEAD_M sets it. Sorter id → branch belt id; a sorter
// with no bag near is left out (its flap stays where it is).
export function flapTargets(sorters, bags) {
  const targets = new Map();
  for (const sorter of sorters.values()) {
    const leaving = bags.find((bag) => bag.position_m < CLEAR_M
      && sorter.branches.some(({ belt }) => belt.id === bag.conveyor_id));
    if (leaving) {
      targets.set(sorter.id, leaving.conveyor_id);
      continue;
    }
    const end = sorter.incoming.length_m;
    const coming = bags.filter((bag) => bag.conveyor_id === sorter.incoming.id
      && bag.position_m + bag.length_m >= end - LOOKAHEAD_M)
      .sort((a, b) => b.position_m - a.position_m)[0];
    const branch = coming && sorter.branches.find(({ outputs }) => outputs.has(routeOutput(coming)));
    if (branch) targets.set(sorter.id, branch.belt.id);
  }
  return targets;
}

// How open a flap is (0 straight on, 1 fully across) after dtS more
// simulated seconds, moving at a steady pace towards `target`. Time going
// back (a reset) puts it straight at its target.
export function stepFlap(amount, target, dtS) {
  if (dtS < 0) return target;
  const step = dtS / FLAP_SWING_S;
  return amount < target ? Math.min(amount + step, target) : Math.max(amount - step, target);
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
