// Draws the plant as a hall seen from one of its corners (2.5D), with
// PixiJS, from the same layout and snapshots as the top-down map.
//
// The hall is a scale model: a floor slab cut at its edges, walls on its two
// far sides, belts raised on legs, check-in desks with their queues, chutes
// dropping through openings in the floor and a light tower beside every
// belt. Everything is built from flat-shaded prisms (hallshapes.js) and
// placed with geometry.js's hall projection; the view can be turned by
// quarter turns to see behind tall things.
//
// What moves is exactly what the map shows, from the same modules:
// playback.js gives the displayed time and the bags between two snapshots,
// sorters.js the divert gates and the diverted bags' slide, passengers.js
// the queues, signals.js the belts' lights and conditions. Nothing here
// decides anything about the simulation.
//
// Drawing order: the scene is one PixiJS container sorted by depth (how
// near each object stands to the viewer). Long things are cut into short
// pieces so the order holds: belts into one-metre pieces, queue barriers
// into the stretches between posts. A belt piece is sorted a little behind
// its centre, so the bags on it are drawn after it; its rail on the
// viewer's side is sorted a little in front, so it hides their bottom edge.
// Signs, symbols, clocks and the selection are drawn over the scene in
// screen pixels, so they stay sharp and readable at every zoom.
//
// The static scene (floor, walls, belts, desks, chutes) is drawn once in
// projected units and the camera only scales and moves its container; it is
// redrawn when the direction of the view changes (turning, or the tilt from
// the map into the hall) and when a belt's condition changes (its rails).

import { Container, Graphics, Text } from 'pixi.js';
import { CANVAS_FONT, surfaceSpan } from './assets.js';
import {
  BAGGAGE_WIDTH_M, BELT_WIDTH_M, DESK_SPAN, HALL_CAMERA, HALL_SLAB_M, HALL_WALL_M, beltAngle, beltEnds,
  frameToMap, hallFloor, hallView, panHallBy, pickAt, plantJoints, pointAlong, samePlant,
  zoomHallAround,
} from './geometry.js';
import { faceVisible, flat, outwardEdges, panel, prism, rect, ring, shadeColour } from './hallshapes.js';
import { destinationLooks, hashString, shortCode, suitcaseLook } from './looks.js';
import {
  LANE, MAX_SHOWN, addQueueSnapshot, deskToMap, passengerLook, passengersAt, queuePoint,
} from './passengers.js';
import { advanceSurface, createPlayback, isNewRun } from './playback.js';
import { EDGE_PATTERNS, LIGHT_COLOURS, STATE_OF_EDGE, drawLight } from './renderer.js';
import { addWrongExits, beltLights, beltStates, dashes, wrongExitSignals } from './signals.js';
import { GATE, divertedBaggage, eyeAlong, eyeBlocked, gateOpening, sorterBranches } from './sorters.js';

function nowSeconds() {
  return performance.now() / 1000;
}

// Drawing units per projected metre inside the scene container: shapes are
// drawn at this scale and the container is scaled to the zoom.
const BASE = 32;
// Heights above the floor, in metres: the belts' frame, their rubber
// surface (where bags sit) and the top of their rails.
const FRAME_BOTTOM_M = 0.52;
const BELT_TOP_M = 0.7;
const RAIL_TOP_M = 0.8;
const RAIL_M = 0.1;
const PIECE_M = 1;          // belts are drawn in pieces this long
const LEG_EVERY_M = 1.6;
const DRUM_M = 0.12;        // past a belt's free end
// Depth offsets (metres): a belt piece behind its centre, under its bags;
// the rail on the viewer's side in front of them.
const UNDER_BAGS = -0.75;
const NEAR_RAIL = 0.3;
const FLOOR_Z = -1e6;
const WALL_Z = -1e5;
// Where a belt's light tower stands (as the map's light) and its lamps,
// bottom to top: stopped, warning, fault — the lit lamp's height tells the
// state as well as its colour.
const TOWER_ALONG_M = 1.2;
const TOWER_ASIDE_M = BELT_WIDTH_M / 2 + 0.3;
const LAMPS = ['stopped', 'warning', 'fault'];
const BLINK_PERIOD_S = 0.8;
const BLINK_ON = 0.6;
// Shadows fall down-right on the map, like the map's (metres per metre of height).
const SHADOW = { x: 0.35, y: 0.55 };
const SIGN_POLE_M = 2.3;
// Bag heights by style.
const BAG_HEIGHT_M = { hardshell: 0.26, cabin: 0.22, duffel: 0.24 };
// A tag's code is written over each bag once bags are this large on screen.
const TAG_TEXT_PPM = 70;
// Passengers' trousers (muted, never a state colour) and the steps they turn in.
const PASSENGER_LEGS = '#2b3036';
const FACING_STEP = Math.PI / 8;
const CLICK_SLOP_PX = 4;
const PICK_TOLERANCE_PX = 6;
// Seconds a quarter turn and the tilt between the map and the hall take.
const TURN_S = 0.55;
const TILT_S = 0.9;
const COUNTER_FONT = '"B612 Mono", ui-monospace, monospace';

const C = {
  slabTop: '#272c30',      // the joints between floor panels
  section: '#1b1e21',      // the slab's cut edge
  hatch: 0x2a2f33,
  wall: '#535b62',
  wallCap: '#6a737a',
  frame: '#5a636b',
  rubber: '#262b31',
  steel: '#9aa4ac',
  plate: '#475058',
  ball: 0x8d979f,
  leg: '#3c444b',
  counter: '#3d4750',
  counterTop: '#5a6773',
  screen: '#10151a',
  scale: '#8d979f',
  chute: '#6f7a83',
  curtain: '#1b1f23',
  hole: 0x06080a,
  seam: 0x7f8a93,
  slat: 0x15191d,
  post: '#9aa4ac',
  tape: '#6c757d',
  gate: '#c3ccd3',
  dark: '#22272c',
  board: 0x0b0f13,
  ink: 0xf4f6f8,
};

const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

// `a` mixed with `b` (numbers), `amount` of the way towards `b`.
function mixColour(a, b, amount) {
  const channel = (shift) => Math.round(((a >> shift) & 255) * (1 - amount) + ((b >> shift) & 255) * amount);
  return (channel(16) << 16) | (channel(8) << 8) | channel(0);
}

function reducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}

// The yaw equal to `target` (modulo a full turn) nearest to `from`.
function nearestTurn(from, target) {
  const turn = 2 * Math.PI;
  return target + Math.round((from - target) / turn) * turn;
}

export function createHall(app, { onSelect = () => {} } = {}) {
  const root = new Container();
  const world = new Container();
  const scene = new Container();
  scene.sortableChildren = true;
  world.addChild(scene);
  const boards = new Graphics();
  const labels = new Container();
  const marks = new Graphics();
  root.addChild(world, boards, labels, marks);
  root.visible = false;
  app.stage.addChild(root);

  let active = false;
  let layout = null;
  let belts = new Map();
  let destinations = new Map();
  let sorters = new Map();
  let ends = new Map();
  let desks = [];                 // { id, input, belt } per check-in desk
  const playback = createPlayback();
  let camera = HALL_CAMERA;
  let restYaw = HALL_CAMERA.yaw;  // the direction the hall is seen from when entered
  let animation = null;           // { from, to, startS, durationS, done } while the camera moves
  let projection = null;          // the view the static scene was drawn for
  let staticDirty = true;
  let items = [];                 // static scene objects: { g, draw, z }
  let pieces = [];                // belt pieces: { g (its moving slats), belt, a, b, z }
  let towers = [];                // { g, belt, at }
  let gates = [];                 // { g, sorter, branch }
  let selection = null;
  let newest = null;
  let lights = new Map();
  let edges = new Map();
  let edgesKey = '';
  let haltedBelts = new Set();
  let wrongExits = [];
  let queues = new Map();
  let slides = new Map();
  let slideTime = null;
  const surfaceOffsets = new Map();
  let surfaceTime = null;
  let drawnBags = [];
  const bagShapes = new Map();        // bag id → Graphics
  const passengerShapes = new Map();  // "input#number" → Graphics
  let signs = [];                     // { at, z, code, caption, colour, texts, outputId }
  const tagTexts = new Map();         // bag id → Text of its tag's code
  const queueTexts = new Map();       // input id → its "+N" Text
  let queueExtras = new Map();        // input id → passengers waiting beyond the lane

  // A map point at height z in the scene's drawing units. The projection
  // is linear, so the same function draws a bag or a passenger around the
  // origin, to be moved to its place as a whole.
  const pt = (x, y, z = 0) => {
    const { u, v } = projection.units(x, y, z);
    return { x: u * BASE, y: v * BASE };
  };
  const view = { pt, get toward() { return projection.toward; } };
  const depth = (point) => projection.depth(point.x_m ?? point.x, point.y_m ?? point.y);

  function addItem(anchor, bias, draw) {
    const g = new Graphics();
    scene.addChild(g);
    const item = { g, draw, z: typeof bias === 'function' ? bias : () => depth(anchor) + bias };
    items.push(item);
    return item;
  }

  // --- Static scene --------------------------------------------------------

  function drawFloor(g) {
    const floor = hallFloor(layout);
    prism(g, view, floor, -HALL_SLAB_M, 0, C.section, { top: C.slabTop });
    // The cut edges hatched, as in an architect's section.
    for (const { a, b, nx, ny } of outwardEdges(floor)) {
      if (!faceVisible(nx, ny, projection.toward)) continue;
      const length = Math.hypot(b.x - a.x, b.y - a.y);
      const ux = (b.x - a.x) / length;
      const uy = (b.y - a.y) / length;
      for (let t = 0.3; t + HALL_SLAB_M < length; t += 0.45) {
        const p = pt(a.x + ux * t, a.y + uy * t, -HALL_SLAB_M + 0.04);
        const q = pt(a.x + ux * (t + HALL_SLAB_M - 0.08), a.y + uy * (t + HALL_SLAB_M - 0.08), -0.04);
        g.moveTo(p.x, p.y).lineTo(q.x, q.y);
      }
    }
    g.stroke({ width: 1, color: C.hatch, pixelLine: true });
    // Terrazzo panels, each a slightly different shade, seeded by its place.
    const [corner, , opposite] = floor;
    const tile = 2;
    for (let x = corner.x; x < opposite.x - 0.01; x += tile) {
      for (let y = corner.y; y < opposite.y - 0.01; y += tile) {
        const shade = 0.92 + (hashString(`${Math.round(x)}:${Math.round(y)}`) % 100) / 100 * 0.12;
        flat(g, view, rect({ x_m: x, y_m: y }, 0, 0.03, Math.min(tile, opposite.x - x) - 0.03,
          0.03, Math.min(tile, opposite.y - y) - 0.03), 0, shadeColour('#353b40', shade));
      }
    }
    // Shadows of the belts, plates and desks.
    const shadow = (footprint, heightM, alpha) => flat(g, view, footprint.map((p) => ({
      x: p.x + SHADOW.x * heightM, y: p.y + SHADOW.y * heightM,
    })), 0, 0x000000, alpha);
    for (const belt of layout.belts) {
      const { from, to } = railSpan(belt);
      shadow(rect(belt.start, beltAngle(belt), from, to, -BELT_WIDTH_M / 2, BELT_WIDTH_M / 2), 0.45, 0.28);
    }
    for (const joint of plantJoints(layout)) {
      shadow(rect(joint.position, 0, -0.5, 0.5, -0.5, 0.5), 0.45, 0.28);
    }
    for (const { input, belt } of desks) {
      shadow(rect(input.position, beltAngle(belt), -1.55, -0.8, -1.05, 1.05), 0.5, 0.3);
    }
    // The openings the chutes drop through, to the loading area below.
    for (const output of layout.outputs) {
      const angle = beltAngle(lastBelt(output.id));
      flat(g, view, rect(output.position, angle, 1.08, 1.98, -0.82, 0.82), 0.001, shadeColour(C.steel, 0.55));
      flat(g, view, rect(output.position, angle, 1.12, 1.94, -0.76, 0.76), 0.002, C.hole);
    }
  }

  // Walls on the two sides of the slab away from the viewer, with pilasters.
  function drawWalls(g) {
    for (const { a, b, nx, ny } of outwardEdges(hallFloor(layout))) {
      if (faceVisible(nx, ny, projection.toward)) continue;
      const inset = (p, d) => ({ x: p.x - nx * d, y: p.y - ny * d });
      prism(g, view, [a, b, inset(b, 0.25), inset(a, 0.25)], 0, HALL_WALL_M, C.wall, { top: C.wallCap });
      const length = Math.hypot(b.x - a.x, b.y - a.y);
      const ux = (b.x - a.x) / length;
      const uy = (b.y - a.y) / length;
      for (let t = 3; t < length - 1; t += 6) {
        const p = { x: a.x + ux * t, y: a.y + uy * t };
        const footprint = [
          inset({ x: p.x - ux * 0.2, y: p.y - uy * 0.2 }, 0.25), inset({ x: p.x + ux * 0.2, y: p.y + uy * 0.2 }, 0.25),
          inset({ x: p.x + ux * 0.2, y: p.y + uy * 0.2 }, 0.45), inset({ x: p.x - ux * 0.2, y: p.y - uy * 0.2 }, 0.45),
        ];
        prism(g, view, footprint, 0, HALL_WALL_M, C.wall, { top: C.wallCap });
      }
    }
  }

  // The stretch of a belt its frame covers: past a free end by the drum,
  // up to a joint's plate otherwise.
  function railSpan(belt) {
    const end = ends.get(belt.id);
    return {
      from: end.startJoint ? end.startTrimM : -DRUM_M,
      to: end.endJoint ? belt.length_m - end.endTrimM : belt.length_m + DRUM_M,
    };
  }

  function lastBelt(outputId) {
    return layout.belts.find((belt) => belt.target_id === outputId);
  }

  // The side of a belt running at `angle` nearer the viewer: 1 its right,
  // -1 its left (the side whose outward normal faces the viewer).
  function nearSideOf(angle) {
    const normal = { x: -Math.sin(angle), y: Math.cos(angle) };  // the right side's
    return normal.x * projection.toward.x + normal.y * projection.toward.y >= 0 ? 1 : -1;
  }

  // The rails of a belt piece on one side (-1 left, 1 right), with the
  // belt's condition dashed along their tops.
  function drawRail(g, belt, a, b, side) {
    const angle = beltAngle(belt);
    const outer = side * BELT_WIDTH_M / 2;
    const inner = side * (BELT_WIDTH_M / 2 - RAIL_M);
    const [y0, y1] = side < 0 ? [outer, inner] : [inner, outer];
    prism(g, view, rect(belt.start, angle, a, b, y0, y1), FRAME_BOTTOM_M, RAIL_TOP_M, C.steel,
      { top: shadeColour(C.steel, 1.08) });
    const state = edges.get(belt.id);
    if (!state) return;
    const pattern = EDGE_PATTERNS[state];  // the map's dashes, along the rails
    const { from, to } = railSpan(belt);
    for (const [d0, d1] of dashes(from, to, pattern.onM, pattern.offM)) {
      const s = Math.max(d0, a);
      const e = Math.min(d1, b);
      if (e <= s) continue;
      flat(g, view, rect(belt.start, angle, s, e, y0, y1), RAIL_TOP_M + 0.002,
        LIGHT_COLOURS[STATE_OF_EDGE[state]]);
    }
  }

  function buildBelt(belt) {
    const angle = beltAngle(belt);
    const { from, to } = railSpan(belt);
    const count = Math.max(1, Math.ceil((to - from) / PIECE_M - 1e-6));
    const legs = [];
    for (let t = from + 0.25; t < to - 0.1; t += LEG_EVERY_M) legs.push(t);
    legs.push(to - 0.25);
    const nearSide = () => nearSideOf(angle);
    for (let i = 0; i < count; i += 1) {
      const a = from + ((to - from) * i) / count;
      const b = from + ((to - from) * (i + 1)) / count;
      const centre = frameToMap(belt.start, angle, (a + b) / 2, 0);
      const body = addItem(centre, UNDER_BAGS, (g) => {
        for (const t of legs.filter((leg) => leg >= a && leg < b)) {
          for (const across of [-0.4, 0.4]) {
            prism(g, view, rect(belt.start, angle, t - 0.04, t + 0.04, across - 0.04, across + 0.04),
              0, FRAME_BOTTOM_M, C.leg);
          }
        }
        prism(g, view, rect(belt.start, angle, a, b, -BELT_WIDTH_M / 2 + RAIL_M, BELT_WIDTH_M / 2 - RAIL_M),
          FRAME_BOTTOM_M, BELT_TOP_M, C.frame, { top: C.rubber });
      });
      // The moving slats, just over the rubber.
      const slats = new Graphics();
      scene.addChild(slats);
      pieces.push({ g: slats, belt, a, b, z: () => body.z() + 0.001 });
      for (const side of [-1, 1]) {
        const railCentre = frameToMap(belt.start, angle, (a + b) / 2, side * (BELT_WIDTH_M / 2 - RAIL_M / 2));
        addItem(railCentre, () => (side === nearSide() ? depth(railCentre) + NEAR_RAIL : body.z() + 0.002),
          (g) => drawRail(g, belt, a, b, side));
      }
    }
    // Light tower beside the belt, near its start.
    const along = Math.min(TOWER_ALONG_M, belt.length_m / 2);
    const at = frameToMap(belt.start, angle, along, -TOWER_ASIDE_M);
    const g = new Graphics();
    scene.addChild(g);
    towers.push({ g, belt, at, key: '' });
  }

  // A square plate where belts meet (merge, sorter, corner), with its ball
  // transfer units and a rail along every side no belt leaves from.
  function buildJoint(joint) {
    const angle = joint.directions[0] ?? 0;
    const half = BELT_WIDTH_M / 2;
    addItem(joint.position, UNDER_BAGS, (g) => {
      for (const [x, y] of [[-0.4, -0.4], [0.4, -0.4], [0.4, 0.4], [-0.4, 0.4]]) {
        prism(g, view, rect(frameToMap(joint.position, angle, x, y), angle, -0.04, 0.04, -0.04, 0.04),
          0, FRAME_BOTTOM_M, C.leg);
      }
      prism(g, view, rect(joint.position, angle, -half, half, -half, half), FRAME_BOTTOM_M, BELT_TOP_M,
        C.frame, { top: C.plate });
      for (let i = -2; i <= 2; i += 1) {
        for (let j = -2; j <= 2; j += 1) {
          const p = frameToMap(joint.position, angle, i * 0.18, j * 0.18);
          flat(g, view, ring(p.x_m, p.y_m, 0.035, 6), BELT_TOP_M + 0.001, C.ball);
        }
      }
      for (let k = 0; k < 4; k += 1) {
        const normal = angle + (k * Math.PI) / 2;
        const open = joint.directions.some((d) => Math.abs(Math.atan2(Math.sin(d - normal), Math.cos(d - normal))) < 0.3);
        if (open) continue;
        const footprint = rect(joint.position, normal, half - RAIL_M, half, -half, half);
        prism(g, view, footprint, FRAME_BOTTOM_M, RAIL_TOP_M, C.steel, { top: shadeColour(C.steel, 1.08) });
      }
    });
  }

  function buildDesk({ input, belt }) {
    const angle = beltAngle(belt);
    const p = (x, y) => deskToMap(input.position, angle, { x, y });
    addItem(p(-1.18, 0), 0, (g) => {
      prism(g, view, rect(input.position, angle, -1.55, -0.8, -1.05, 1.05), 0, 1.0, C.counter, { top: C.counterTop });
      // The agent's screen, turned towards the counter.
      panel(g, view, { x: p(-1.3, -0.62).x_m, y: p(-1.3, -0.62).y_m }, { x: p(-1.3, -0.2).x_m, y: p(-1.3, -0.2).y_m },
        1.04, 1.34, 0.04, C.screen);
      prism(g, view, rect(input.position, angle, -1.34, -1.26, -0.45, -0.37), 1.0, 1.06, C.dark);
    });
    addItem(p(-0.47, 0), 0, (g) => {
      prism(g, view, rect(input.position, angle, -0.78, -0.16, -0.42, 0.42), 0, 0.32, C.scale,
        { top: shadeColour(C.scale, 1.2) });
    });
    // The queue lane: posts and the barrier tape between them.
    const from = LANE.fromM - 0.35;
    const to = LANE.fromM + LANE.pitchM * (MAX_SHOWN - 2) + 0.35;
    const posts = Math.max(2, Math.round((to - from) / 1.6) + 1);
    const sides = [LANE.y - LANE.halfWidthM, LANE.y + LANE.halfWidthM];
    const post = (x, y) => {
      const at = p(x, y);
      addItem(at, 0, (g) => {
        flat(g, view, ring(at.x_m, at.y_m, 0.13, 10), 0.002, shadeColour(C.post, 0.6));
        prism(g, view, ring(at.x_m, at.y_m, 0.04, 8), 0, 0.95, C.post, { top: shadeColour(C.post, 1.2) });
      });
    };
    const tape = (x0, y0, x1, y1) => {
      const a = p(x0, y0);
      const b = p(x1, y1);
      addItem({ x_m: (a.x_m + b.x_m) / 2, y_m: (a.y_m + b.y_m) / 2 }, 0, (g) => {
        panel(g, view, { x: a.x_m, y: a.y_m }, { x: b.x_m, y: b.y_m }, 0.84, 0.91, 0.02, C.tape);
      });
    };
    for (const y of sides) {
      const xs = Array.from({ length: posts }, (_, i) => from + ((to - from) * i) / (posts - 1));
      xs.forEach((x, i) => {
        post(x, y);
        if (i > 0) tape(xs[i - 1], y, x, y);
      });
    }
    tape(to, sides[0], to, sides[1]);
    // The sign's pole, behind the counter.
    const pole = p(-1.85, 0);
    addItem(pole, 0, (g) => {
      prism(g, view, ring(pole.x_m, pole.y_m, 0.035, 6), 0, SIGN_POLE_M, C.dark);
    });
    signs.push({ at: pole, z: SIGN_POLE_M, code: shortCode(input.id), caption: `Check-in ${input.label}`, colour: 0xe8eef3 });
  }

  function buildChute(output) {
    const belt = lastBelt(output.id);
    const angle = beltAngle(belt);
    const q = (x, y, z) => {
      const m = frameToMap(output.position, angle, x, y);
      return pt(m.x_m, m.y_m, z);
    };
    const x0 = DRUM_M + 0.04;
    const x1 = 1.5;
    const zTop = BELT_TOP_M - 0.05;
    const zEnd = 0.02;
    addItem(frameToMap(output.position, angle, 0.8, 0), UNDER_BAGS, (g) => {
      for (const y of [-0.38, 0.38]) {
        const leg = frameToMap(output.position, angle, x0 + 0.1, y);
        prism(g, view, ring(leg.x_m, leg.y_m, 0.035, 6), 0, zTop, C.leg);
      }
      // The sloping bed, then a lip along each side.
      const bed = [q(x0, -0.42, zTop), q(x1, -0.62, zEnd), q(x1, 0.62, zEnd), q(x0, 0.42, zTop)];
      g.poly(bed.flatMap((p) => [p.x, p.y])).fill(shadeColour(C.chute, 0.9));
      for (let i = 1; i <= 3; i += 1) {
        const y = -0.42 + (0.84 * i) / 4;
        const a = q(x0 + 0.05, y, zTop - 0.01);
        const b = q(x1 - 0.05, y * 1.45, zEnd + 0.03);
        g.moveTo(a.x, a.y).lineTo(b.x, b.y);
      }
      g.stroke({ width: 1, color: 0x000000, alpha: 0.25, pixelLine: true });
      for (const side of [-1, 1]) {
        const lip = [q(x0, side * 0.42, zTop), q(x1, side * 0.62, zEnd), q(x1, side * 0.62, zEnd + 0.1),
          q(x0, side * 0.42, zTop + 0.1)];
        g.poly(lip.flatMap((p) => [p.x, p.y])).fill(shadeColour(C.steel, side < 0 ? 0.95 : 0.7));
      }
      // Rubber curtain strips hanging across the top of the chute.
      const cx = x0 + 0.25;
      for (let y = -0.44; y < 0.44; y += 0.11) {
        const strip = [q(cx, y + 0.005, zTop + 0.42), q(cx, y + 0.1, zTop + 0.42), q(cx, y + 0.1, zTop),
          q(cx, y + 0.005, zTop)];
        g.poly(strip.flatMap((p) => [p.x, p.y])).fill({ color: shadeColour(C.curtain, 1), alpha: 0.92 });
      }
      const bar = [q(cx, -0.5, zTop + 0.42), q(cx, 0.5, zTop + 0.42), q(cx, 0.5, zTop + 0.47), q(cx, -0.5, zTop + 0.47)];
      g.poly(bar.flatMap((p) => [p.x, p.y])).fill(shadeColour(C.dark, 1.2));
    });
    const pole = frameToMap(output.position, angle, 0.6, -1.15);
    addItem(pole, 0, (g) => {
      prism(g, view, ring(pole.x_m, pole.y_m, 0.035, 6), 0, SIGN_POLE_M + 0.2, C.dark);
    });
    const look = destinations.get(output.id);
    signs.push({
      at: pole, z: SIGN_POLE_M + 0.2, code: look.code, caption: output.label,
      colour: parseInt(look.colour.slice(1), 16), outputId: output.id,
    });
  }

  // The photo-eye's two posts on the rails before each sorter.
  function buildEyes(sorter) {
    const { incoming } = sorter;
    const along = eyeAlong(sorter, ends.get(incoming.id).endTrimM);
    for (const side of [-1, 1]) {
      const at = frameToMap(incoming.start, beltAngle(incoming), along, side * (BELT_WIDTH_M / 2 - RAIL_M / 2));
      addItem(at, () => depth(at) + (side === nearSideOf(beltAngle(incoming)) ? NEAR_RAIL : 0), (g) => {
        prism(g, view, rect(at, beltAngle(incoming), -0.04, 0.04, -0.04, 0.04), RAIL_TOP_M, RAIL_TOP_M + 0.22, C.dark);
      });
    }
  }

  function buildScene() {
    clearMoving();
    for (const child of scene.removeChildren()) child.destroy();
    items = [];
    pieces = [];
    towers = [];
    gates = [];
    signs = [];
    addItem({ x_m: 0, y_m: 0 }, () => FLOOR_Z, drawFloor);
    addItem({ x_m: 0, y_m: 0 }, () => WALL_Z, drawWalls);
    for (const belt of layout.belts) buildBelt(belt);
    for (const joint of plantJoints(layout)) buildJoint(joint);
    for (const desk of desks) buildDesk(desk);
    for (const output of layout.outputs) buildChute(output);
    for (const sorter of sorters.values()) {
      buildEyes(sorter);
      for (const branch of sorter.branches) {
        if (branch.side === 0) continue;
        const g = new Graphics();
        scene.addChild(g);
        gates.push({ g, sorter, branch, key: '' });
      }
    }
    buildLabels();
    staticDirty = true;
  }

  function redrawStatic() {
    for (const item of items) {
      item.g.clear();
      item.draw(item.g);
      item.g.zIndex = item.z();
    }
    for (const piece of pieces) piece.g.zIndex = piece.z();
    staticDirty = false;
  }

  // --- Signs ---------------------------------------------------------------

  function buildLabels() {
    for (const child of labels.removeChildren()) child.destroy();
    tagTexts.clear();
    queueTexts.clear();
    for (const sign of signs) {
      const code = new Text({ text: sign.code, style: { fontFamily: CANVAS_FONT, fontWeight: '700', fontSize: 11, fill: C.board } });
      const caption = new Text({ text: sign.caption, style: { fontFamily: CANVAS_FONT, fontWeight: '600', fontSize: 12, fill: C.ink } });
      code.anchor.set(0.5);
      caption.anchor.set(0, 0.5);
      labels.addChild(code, caption);
      sign.texts = { code, caption };
      if (sign.outputId) {
        const counter = new Text({ text: '0', style: { fontFamily: COUNTER_FONT, fontWeight: '700', fontSize: 12, fill: 0xe8eef3 } });
        counter.anchor.set(0.5);
        labels.addChild(counter);
        sign.texts.counter = counter;
      }
    }
    updateCounters();
  }

  function updateCounters() {
    if (!newest) return;
    const delivered = new Map(newest.stats.outputs.map((node) => [node.output_id, node.correctly_delivered]));
    for (const sign of signs) {
      if (!sign.texts?.counter) continue;
      const text = String(delivered.get(sign.outputId) ?? 0);
      if (sign.texts.counter.text !== text) sign.texts.counter.text = text;
    }
  }

  // Each sign as a board hanging at the top of its pole, facing the screen.
  function drawSigns(screenView) {
    boards.clear();
    for (const sign of signs) {
      const top = screenView.toScreen(sign.at, sign.z);
      const { code, caption, counter } = sign.texts;
      const height = 22;
      const tile = 16;
      const counterWidth = counter ? Math.max(26, counter.width + 12) : 0;
      const width = 3 + tile + 6 + caption.width + 8 + counterWidth;
      const x = Math.round(top.x - width / 2);
      const y = Math.round(top.y - height);
      boards.roundRect(x, y, width, height, 5).fill({ color: C.board, alpha: 0.94 })
        .stroke({ width: 1, color: 0xffffff, alpha: 0.12 });
      boards.roundRect(x + 3, y + 3, tile, tile, 3).fill(sign.colour);
      code.position.set(x + 3 + tile / 2, y + height / 2 + 0.5);
      caption.position.set(x + 3 + tile + 6, y + height / 2 + 0.5);
      if (counter) {
        boards.roundRect(x + width - counterWidth - 3, y + 3, counterWidth, tile, 3).fill(0x05080a);
        counter.position.set(x + width - 3 - counterWidth / 2, y + height / 2 + 0.5);
      }
    }
  }

  // --- Moving things ---------------------------------------------------------

  function clearMoving() {
    for (const g of bagShapes.values()) g.destroy();
    bagShapes.clear();
    for (const g of passengerShapes.values()) g.destroy();
    passengerShapes.clear();
  }

  // Scrolls each belt's slats by the distance it has run: nothing while
  // simulated time stands still or the belt is halted.
  function moveSurfaces(timeS) {
    let dtS = surfaceTime === null ? 0 : timeS - surfaceTime;
    if (dtS < 0) {
      surfaceOffsets.clear();
      dtS = 0;
    }
    surfaceTime = timeS;
    for (const belt of layout.belts) {
      const speed = haltedBelts.has(belt.id) ? 0 : belt.speed_m_s;
      surfaceOffsets.set(belt.id, advanceSurface(surfaceOffsets.get(belt.id) ?? 0, speed, dtS, 1));
    }
  }

  // The belt's laced joint once a metre and faint slats between, over the
  // rubber of each piece, at the belts' current offsets.
  function drawSlats() {
    for (const piece of pieces) {
      const { g, belt, a, b } = piece;
      g.clear();
      const span = surfaceSpan(belt, ends.get(belt.id));
      const from = Math.max(a, span.from);
      const to = Math.min(b, span.to);
      const angle = beltAngle(belt);
      const shift = surfaceOffsets.get(belt.id) ?? 0;
      const half = BELT_WIDTH_M / 2 - RAIL_M;
      for (let k = Math.floor(from - span.from - shift) - 1; span.from + shift + k < to; k += 0.25) {
        const s = span.from + shift + k;
        if (s < from || s > to - 0.02) continue;
        const seam = Math.abs(k - Math.round(k)) < 1e-6;
        flat(g, view, rect(belt.start, angle, s, Math.min(s + (seam ? 0.035 : 0.015), to), -half, half),
          BELT_TOP_M + 0.001, seam ? C.seam : C.slat, seam ? 1 : 0.7);
      }
      g.zIndex = piece.z();
    }
  }

  function bagShape(g, baggage, look, heading) {
    const length = baggage.length_m;
    const width = BAGGAGE_WIDTH_M;
    const height = BAG_HEIGHT_M[look.style];
    const origin = { x_m: 0, y_m: 0 };
    const box = (x0, x1, y0, y1) => rect(origin, heading, x0, x1, y0, y1);
    const body = box(-length / 2, length / 2, -width / 2, width / 2);
    prism(g, view, body, 0, height, look.colour, { top: shadeColour(look.colour, 1.1) });
    if (look.style === 'hardshell') {
      for (const y of [-0.1, 0.1]) {
        flat(g, view, box(-length / 2 + 0.05, length / 2 - 0.05, y - 0.012, y + 0.012), height + 0.001,
          shadeColour(look.colour, 0.78));
      }
    } else if (look.style === 'cabin') {
      flat(g, view, box(0, length / 2 - 0.06, -width / 2 + 0.05, width / 2 - 0.05), height + 0.001,
        shadeColour(look.colour, 0.84));
    } else {
      flat(g, view, box(-length / 2 + 0.06, length / 2 - 0.06, -width / 2 + 0.06, width / 2 - 0.06),
        height + 0.001, shadeColour(look.colour, 1.22));
      for (const x of [-length / 4, length / 4]) {
        prism(g, view, box(x - 0.02, x + 0.02, -width / 2 - 0.004, width / 2 + 0.004), 0, height + 0.003, '#1d2126');
      }
    }
    if (look.style !== 'duffel') {
      prism(g, view, box(-length / 2 + 0.04, -length / 2 + 0.1, -0.08, 0.08), height, height + 0.035, '#1d2126');
    }
    // The destination tag: a band in the destination's colour round the bag.
    prism(g, view, box(length / 2 - 0.17, length / 2 - 0.08, -width / 2 - 0.006, width / 2 + 0.006),
      0, height + 0.004, look.tagColour);
  }

  function placeBaggage(timeS) {
    const dtS = slideTime === null ? 0 : timeS - slideTime;
    slideTime = timeS;
    const next = new Map();
    drawnBags = playback.baggageAt(timeS, belts)
      .map((baggage) => divertedBaggage(sorters, slides, baggage, dtS, next))
      .filter((baggage) => belts.has(baggage.conveyor_id))
      .map((baggage) => {
        const belt = belts.get(baggage.conveyor_id);
        const centre = baggage.place ?? pointAlong(belt, baggage.position_m + baggage.length_m / 2);
        const heading = baggage.place ? baggage.placeAngle : beltAngle(belt);
        return { ...baggage, centre, heading, look: suitcaseLook(baggage, destinations) };
      });
    slides = next;
    const present = new Set();
    for (const baggage of drawnBags) {
      const { centre, heading, look } = baggage;
      const key = `${look.style}|${look.colour}|${look.tagColour}|${baggage.length_m}|${heading.toFixed(3)}|${projection.yaw}|${projection.elevation}`;
      let g = bagShapes.get(baggage.id);
      if (!g) {
        g = new Graphics();
        bagShapes.set(baggage.id, g);
        scene.addChild(g);
      }
      if (g.label !== key) {
        g.clear();
        bagShape(g, baggage, look, heading);
        g.label = key;
      }
      const at = pt(centre.x_m, centre.y_m, BELT_TOP_M);
      g.position.set(at.x, at.y);
      g.alpha = baggage.alpha;
      g.zIndex = depth(centre);
      present.add(baggage.id);
    }
    for (const [id, g] of bagShapes) {
      if (!present.has(id)) {
        g.destroy();
        bagShapes.delete(id);
      }
    }
  }

  // A passenger facing `facing` (map radians): legs, an oval coat with its
  // shoulders across the way they face, and a head with their hair on top.
  function passengerShape(g, look, facing) {
    const across = { x: -Math.sin(facing), y: Math.cos(facing) };
    const oval = (rx, ry, sides = 10) => Array.from({ length: sides }, (_, i) => {
      const t = ((i + 0.5) / sides) * 2 * Math.PI;
      const a = rx * Math.cos(t);
      const b = ry * Math.sin(t);
      return { x: a * Math.cos(facing) - b * Math.sin(facing), y: a * Math.sin(facing) + b * Math.cos(facing) };
    });
    flat(g, view, ring(SHADOW.x * 0.3, SHADOW.y * 0.3, 0.24, 10), 0.003, 0x000000, 0.3);
    for (const side of [-1, 1]) {
      prism(g, view, ring(across.x * side * 0.08, across.y * side * 0.08, 0.075, 8), 0, 0.8, PASSENGER_LEGS);
    }
    prism(g, view, oval(0.13, 0.21), 0.78, 1.38, look.coat, { top: shadeColour(look.coat, 1.12) });
    prism(g, view, ring(0, 0, 0.055, 8), 1.38, 1.43, look.skin);
    prism(g, view, ring(0, 0, 0.11, 10), 1.43, 1.65, look.skin, { top: look.hair });
  }

  function placePassengers(timeS) {
    const present = new Set();
    for (const { id, input, belt } of desks) {
      const queue = queues.get(id);
      if (!queue) continue;
      const angle = beltAngle(belt);
      const { passengers, extra } = passengersAt(queue, timeS);
      for (const { number, slot, alpha } of passengers) {
        const key = `${id}#${number}`;
        const point = queuePoint(slot);
        const at = deskToMap(input.position, angle, point);
        // Facings in steps, so a passenger is redrawn only when they turn.
        const facing = Math.round((angle + point.facing) / FACING_STEP) * FACING_STEP;
        let g = passengerShapes.get(key);
        if (!g) {
          g = new Graphics();
          passengerShapes.set(key, g);
          scene.addChild(g);
        }
        const shapeKey = `${facing}|${projection.yaw}|${projection.elevation}`;
        if (g.label !== shapeKey) {
          g.clear();
          passengerShape(g, passengerLook(id, number), facing);
          g.label = shapeKey;
        }
        const screen = pt(at.x_m, at.y_m, 0);
        g.position.set(screen.x, screen.y);
        g.alpha = alpha;
        g.zIndex = depth(at);
        present.add(key);
      }
      queueExtras.set(id, extra);
    }
    for (const [key, g] of passengerShapes) {
      if (!present.has(key)) {
        g.destroy();
        passengerShapes.delete(key);
      }
    }
  }

  // Each side branch's gate: a steel panel hinged on the plate, opened by
  // the bags it diverts (as drawn).
  function drawGates() {
    for (const gate of gates) {
      const { g, sorter, branch } = gate;
      const amount = gateOpening(sorter, branch, drawnBags);
      const angle = beltAngle(sorter.incoming);
      const swing = branch.side * amount * GATE.openRad;
      const hingeY = branch.side * GATE.hinge.y;
      const hinge = frameToMap(sorter.position, angle, GATE.hinge.x, hingeY);
      const tip = frameToMap(sorter.position, angle, GATE.hinge.x + GATE.lengthM * Math.cos(swing),
        hingeY + GATE.lengthM * Math.sin(swing));
      const key = `${amount.toFixed(3)}|${projection.yaw}|${projection.elevation}`;
      if (gate.key !== key) {
        g.clear();
        panel(g, view, { x: hinge.x_m, y: hinge.y_m }, { x: tip.x_m, y: tip.y_m }, BELT_TOP_M + 0.02,
          BELT_TOP_M + 0.34, 0.05, C.gate, { top: shadeColour(C.gate, 1.1) });
        prism(g, view, ring(hinge.x_m, hinge.y_m, 0.05, 8), BELT_TOP_M, BELT_TOP_M + 0.4, C.dark);
        gate.key = key;
      }
      g.zIndex = depth({ x_m: (hinge.x_m + tip.x_m) / 2, y_m: (hinge.y_m + tip.y_m) / 2 });
    }
  }

  // Light towers: one lamp lit for the belt's state (none while running),
  // blinking while an alarm on the belt is not acknowledged.
  function drawTowers() {
    const lit = (nowSeconds() % BLINK_PERIOD_S) < BLINK_PERIOD_S * BLINK_ON;
    for (const tower of towers) {
      const light = lights.get(tower.belt.id) ?? { state: 'running', blinking: false };
      const on = light.state !== 'running' && (!light.blinking || lit);
      const key = `${light.state}|${on}|${projection.yaw}|${projection.elevation}`;
      if (tower.key !== key) {
        const { g, at } = tower;
        g.clear();
        flat(g, view, ring(at.x_m, at.y_m, 0.1, 8), 0.002, shadeColour(C.dark, 1.1));
        prism(g, view, ring(at.x_m, at.y_m, 0.03, 6), 0, 1.0, C.steel);
        LAMPS.forEach((state, i) => {
          const colour = LIGHT_COLOURS[state];
          const glowing = on && light.state === state;
          // An unlit lamp is smoked glass, barely tinted: colour only for a state.
          const lamp = glowing ? colour : mixColour(colour, 0x30363b, 0.82);
          prism(g, view, ring(at.x_m, at.y_m, 0.075, 8), 1.0 + i * 0.12, 1.11 + i * 0.12,
            lamp, { top: shadeColour(lamp, glowing ? 1.25 : 1.1) });
        });
        prism(g, view, ring(at.x_m, at.y_m, 0.06, 8), 1.36, 1.4, C.dark);
        tower.key = key;
      }
      tower.g.zIndex = depth(tower.at);
    }
  }

  // --- Over the scene, in screen pixels ------------------------------------

  function screenView() {
    const { width, height } = app.screen;
    return hallView(layout, width, height, camera);
  }

  function drawMarks(timeS, sv) {
    marks.clear();
    const ppm = sv.pixelsPerMetre;
    // The photo-eyes: a faint beam between the posts while clear, the
    // emitter's LED lit while a bag covers it.
    for (const sorter of sorters.values()) {
      const { incoming } = sorter;
      const trim = ends.get(incoming.id).endTrimM;
      const along = eyeAlong(sorter, trim);
      const blocked = eyeBlocked(sorter, trim, drawnBags);
      const angle = beltAngle(incoming);
      const a = sv.toScreen(frameToMap(incoming.start, angle, along, -BELT_WIDTH_M / 2 + RAIL_M / 2), RAIL_TOP_M + 0.14);
      const b = sv.toScreen(frameToMap(incoming.start, angle, along, BELT_WIDTH_M / 2 - RAIL_M / 2), RAIL_TOP_M + 0.14);
      if (!blocked) marks.moveTo(a.x, a.y).lineTo(b.x, b.y).stroke({ width: 1, color: 0xf4f6f8, alpha: 0.25 });
      if (blocked) marks.circle(a.x, a.y, Math.max(ppm * 0.12, 3)).fill({ color: 0xf4f6f8, alpha: 0.2 });
      marks.circle(a.x, a.y, Math.max(ppm * 0.035, 1.5)).fill(blocked ? 0xf4f6f8 : 0x4a535b);
    }
    // Wrong arrivals: red pulses over the chute.
    if (timeS !== null) {
      for (const [outputId, progress] of wrongExitSignals(wrongExits, timeS)) {
        const output = layout.outputs.find((node) => node.id === outputId);
        const belt = lastBelt(outputId);
        if (!output || !belt) continue;
        const alpha = (1 - progress) * (0.55 + 0.45 * Math.cos(2 * Math.PI * 3 * progress));
        const angle = beltAngle(belt);
        const corners = [[0, -0.8, BELT_TOP_M], [1.6, -0.8, 0.05], [1.6, 0.8, 0.05], [0, 0.8, BELT_TOP_M]]
          .map(([x, y, z]) => sv.toScreen(frameToMap(output.position, angle, x, y), z));
        marks.poly(corners.flatMap(({ x, y }) => [x, y]))
          .fill({ color: LIGHT_COLOURS.fault, alpha: alpha * 0.35 })
          .stroke({ width: 3, color: LIGHT_COLOURS.fault, alpha });
      }
    }
    // A symbol over every tower whose belt needs attention, as on the map.
    const blink = (nowSeconds() % BLINK_PERIOD_S) < BLINK_PERIOD_S * BLINK_ON;
    for (const tower of towers) {
      const light = lights.get(tower.belt.id);
      if (!light || light.state === 'running') continue;
      const { x, y } = sv.toScreen(tower.at, 1.4);
      const radius = 6;
      const alpha = !light.blinking || blink ? 1 : 0.3;
      marks.circle(x, y - radius - 5, radius * 1.4).fill({ color: 0x15181a, alpha: 0.85 });
      drawLight(marks, x, y - radius - 5, radius, light.state, alpha);
    }
    // A clock over every bag in a prolonged wait.
    for (const baggage of drawnBags) {
      if (!baggage.prolonged_wait) continue;
      const { x, y } = sv.toScreen(baggage.centre, BELT_TOP_M + BAG_HEIGHT_M[baggage.look.style] + 0.12);
      const r = Math.max(Math.min(ppm * 0.1, 7), 3);
      marks.circle(x, y - r, r + 1).fill({ color: 0x15181a, alpha: baggage.alpha });
      marks.circle(x, y - r, r).fill({ color: LIGHT_COLOURS.warning, alpha: baggage.alpha });
      marks.moveTo(x, y - r - r * 0.62).lineTo(x, y - r).lineTo(x + r * 0.5, y - r)
        .stroke({ width: Math.max(r * 0.22, 1), color: 0x15181a, alpha: baggage.alpha, cap: 'round', join: 'round' });
    }
    drawSelection(sv);
  }

  function outline(sv, footprint, z0, z1) {
    const bottom = footprint.map((p) => sv.toScreen({ x_m: p.x, y_m: p.y }, z0));
    const top = footprint.map((p) => sv.toScreen({ x_m: p.x, y_m: p.y }, z1));
    marks.poly(top.flatMap(({ x, y }) => [x, y]));
    if (z1 > z0) {
      marks.poly(bottom.flatMap(({ x, y }) => [x, y]));
      bottom.forEach((p, i) => marks.moveTo(p.x, p.y).lineTo(top[i].x, top[i].y));
    }
    marks.stroke({ width: 2, color: 0xffffff, alpha: 0.95, join: 'round' });
  }

  // A white frame round the selected bag, belt or desk; a selected bag that
  // has left the plant is no longer selected.
  function drawSelection(sv) {
    if (!selection) return;
    if (selection.kind === 'belt') {
      const belt = belts.get(selection.id);
      if (belt) {
        const { from, to } = railSpan(belt);
        outline(sv, rect(belt.start, beltAngle(belt), from, to, -BELT_WIDTH_M / 2 - 0.05, BELT_WIDTH_M / 2 + 0.05),
          RAIL_TOP_M + 0.01, RAIL_TOP_M + 0.01);
      }
      return;
    }
    if (selection.kind === 'input') {
      const desk = desks.find((item) => item.id === selection.id);
      if (desk) {
        outline(sv, rect(desk.belt.start, beltAngle(desk.belt), DESK_SPAN.fromM, DESK_SPAN.toM,
          -DESK_SPAN.widthM / 2, DESK_SPAN.widthM / 2), 0, 1.05);
      }
      return;
    }
    const baggage = drawnBags.find((bag) => bag.id === selection.id);
    if (!baggage) {
      select(null);
      return;
    }
    const half = baggage.length_m / 2 + 0.06;
    const side = BAGGAGE_WIDTH_M / 2 + 0.06;
    outline(sv, rect(baggage.centre, baggage.heading, -half, half, -side, side), BELT_TOP_M - 0.01,
      BELT_TOP_M + BAG_HEIGHT_M[baggage.look.style] + 0.04);
  }

  // Codes on the bags' tags once they are large enough, and each desk's
  // "+N" for the passengers beyond the lane.
  function drawTexts(sv) {
    const showTags = sv.pixelsPerMetre >= TAG_TEXT_PPM;
    const present = new Set();
    if (showTags) {
      for (const baggage of drawnBags) {
        let text = tagTexts.get(baggage.id);
        if (!text) {
          text = new Text({ text: baggage.look.label, style: { fontFamily: CANVAS_FONT, fontWeight: '700', fontSize: 10, fill: C.board } });
          text.anchor.set(0.5);
          tagTexts.set(baggage.id, text);
          labels.addChild(text);
        }
        // A small tag in the destination's colour over the bag's band, with
        // its code in dark ink, as on the map.
        const along = baggage.length_m / 2 - 0.125;
        const band = { x_m: baggage.centre.x_m + Math.cos(baggage.heading) * along, y_m: baggage.centre.y_m + Math.sin(baggage.heading) * along };
        const { x, y } = sv.toScreen(band, BELT_TOP_M + BAG_HEIGHT_M[baggage.look.style] + 0.05);
        const half = Math.max(text.width / 2 + 3, 7);
        boards.roundRect(Math.round(x - half), Math.round(y - 7), half * 2, 14, 3)
          .fill({ color: parseInt(baggage.look.tagColour.slice(1), 16), alpha: baggage.alpha })
          .stroke({ width: 1, color: C.board, alpha: 0.6 * baggage.alpha });
        text.position.set(x, y + 0.5);
        text.alpha = baggage.alpha;
        present.add(baggage.id);
      }
    }
    for (const [id, text] of tagTexts) {
      if (!present.has(id)) {
        text.destroy();
        tagTexts.delete(id);
      }
    }
    for (const { id, input, belt } of desks) {
      const extra = queueExtras.get(id) ?? 0;
      let text = queueTexts.get(id);
      if (extra <= 0) {
        text?.destroy();
        queueTexts.delete(id);
        continue;
      }
      if (!text) {
        text = new Text({ text: '', style: { fontFamily: CANVAS_FONT, fontWeight: '700', fontSize: 12, fill: 0xe8eef3 } });
        text.anchor.set(0.5, 1);
        queueTexts.set(id, text);
        labels.addChild(text);
      }
      const place = { x: LANE.fromM + LANE.pitchM * (MAX_SHOWN - 1) + 0.15, y: LANE.y };
      const { x, y } = sv.toScreen(deskToMap(input.position, beltAngle(belt), place), 1.6);
      text.text = `+${extra}`;
      text.position.set(x, y);
    }
  }

  // --- Camera ----------------------------------------------------------------

  // Moves the camera towards `to` over `durationS` (at once with reduced
  // motion), then calls `done`. A missing centre is the fitted one.
  function animateTo(to, durationS, done = () => {}) {
    if (reducedMotion() || durationS <= 0) {
      camera = to;
      animation = null;
      done();
      return;
    }
    animation = { from: camera, to, startS: nowSeconds(), durationS, done };
  }

  function stepAnimation() {
    if (!animation) return;
    const { from, to, startS, durationS, done } = animation;
    const t = Math.min((nowSeconds() - startS) / durationS, 1);
    const e = ease(t);
    const { width, height } = app.screen;
    const centreOf = (c) => {
      if (c.centre) return c.centre;
      const fitted = hallView(layout, width, height, c);
      return fitted.fromUnits(fitted.centre.u, fitted.centre.v);
    };
    const a = centreOf(from);
    const b = centreOf(to);
    camera = {
      zoom: from.zoom + (to.zoom - from.zoom) * e,
      yaw: from.yaw + (to.yaw - from.yaw) * e,
      elevation: from.elevation + (to.elevation - from.elevation) * e,
      centre: from.centre === null && to.centre === null ? null
        : { x_m: a.x_m + (b.x_m - a.x_m) * e, y_m: a.y_m + (b.y_m - a.y_m) * e },
    };
    if (t >= 1) {
      camera = to;
      animation = null;
      done();
    }
  }

  function setCamera(next) {
    if (animation) return;
    camera = next;
  }

  // --- Frame -----------------------------------------------------------------

  function update() {
    if (!active || !layout) return;
    stepAnimation();
    const sv = screenView();
    if (!projection || projection.yaw !== sv.yaw || projection.elevation !== sv.elevation || staticDirty) {
      projection = sv;
      redrawStatic();
    }
    world.scale.set(sv.pixelsPerMetre / BASE);
    const { width, height } = app.screen;
    world.position.set(width / 2 - sv.centre.u * sv.pixelsPerMetre, height / 2 - sv.centre.v * sv.pixelsPerMetre);
    const timeS = playback.advance(nowSeconds());
    if (timeS !== null) {
      moveSurfaces(timeS);
      drawSlats();
      placePassengers(timeS);
      placeBaggage(timeS);
      drawGates();
    }
    drawTowers();
    // Signs and marks stand over the scene: they fade in as the map tilts
    // up into the hall (and out as it lies down), where they would pile up.
    const tilt = Math.min(Math.max((Math.PI / 2 - sv.elevation) / (Math.PI / 2 - HALL_CAMERA.elevation), 0), 1);
    boards.alpha = tilt;
    labels.alpha = tilt;
    marks.alpha = tilt;
    drawSigns(sv);
    drawTexts(sv);
    drawMarks(timeS, sv);
  }
  app.ticker.add(update);
  // Signs use the interface's typeface and the counters B612 Mono: rebuild
  // the texts once they have loaded.
  Promise.all([`700 16px ${CANVAS_FONT}`, `700 16px ${COUNTER_FONT}`]
    .map((font) => document.fonts?.load(font))).then(() => {
    if (layout) buildLabels();
  });

  // --- Pointer ---------------------------------------------------------------

  function select(picked) {
    const same = picked?.kind === selection?.kind && picked?.id === selection?.id;
    if (same) return;
    selection = picked;
    onSelect(selection);
  }

  function pointerPoint(event) {
    const box = app.canvas.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  }

  // What is under a screen point. The line of sight goes down and away from
  // the viewer: looked at from the top of the bags down, the first bag it
  // crosses is the one in front. Otherwise a desk or belt at belt height.
  function pickScreen(point) {
    const sv = screenView();
    const tolerance = PICK_TOLERANCE_PX / sv.pixelsPerMetre;
    for (const z of [0.95, 0.88, 0.8, 0.72]) {
      const picked = pickAt(sv.toMap(point, z), drawnBags, belts, tolerance);
      if (picked?.kind === 'bag') return picked;
    }
    return pickAt(sv.toMap(point, BELT_TOP_M), [], belts, tolerance, desks);
  }

  const canvas = app.canvas;
  let press = null;
  canvas.addEventListener('wheel', (event) => {
    if (!active || !layout) return;
    event.preventDefault();
    const { width, height } = app.screen;
    const factor = Math.exp(-event.deltaY * (event.deltaMode === 1 ? 0.05 : 0.0015));
    setCamera(zoomHallAround(layout, camera, width, height, pointerPoint(event), factor));
  }, { passive: false });
  canvas.addEventListener('pointerdown', (event) => {
    if (!active || !layout || event.button !== 0) return;
    const point = pointerPoint(event);
    press = { id: event.pointerId, start: point, last: point, dragging: false };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!active || !layout) return;
    const point = pointerPoint(event);
    if (!press || press.id !== event.pointerId) {
      canvas.style.cursor = pickScreen(point) ? 'pointer' : camera.zoom > 1 ? 'grab' : '';
      return;
    }
    if (!press.dragging && Math.hypot(point.x - press.start.x, point.y - press.start.y) < CLICK_SLOP_PX) return;
    press.dragging = true;
    canvas.style.cursor = 'grabbing';
    const { width, height } = app.screen;
    setCamera(panHallBy(layout, camera, width, height, point.x - press.last.x, point.y - press.last.y));
    press.last = point;
  });
  canvas.addEventListener('pointerup', (event) => {
    if (!active || !press || press.id !== event.pointerId) return;
    if (!press.dragging) select(pickScreen(pointerPoint(event)));
    press = null;
    canvas.style.cursor = '';
  });
  canvas.addEventListener('pointercancel', () => {
    press = null;
  });

  function zoomBy(factor) {
    if (!layout) return;
    const { width, height } = app.screen;
    setCamera(zoomHallAround(layout, camera, width, height, { x: width / 2, y: height / 2 }, factor));
  }

  return {
    setActive(on) {
      active = on;
      root.visible = on;
      press = null;
      if (on) staticDirty = true;
    },
    // Tilts the flat map up into the hall (at once with `animate` false).
    enter(animate = true) {
      const to = { zoom: 1, centre: null, yaw: restYaw, elevation: HALL_CAMERA.elevation };
      camera = { zoom: 1, centre: null, yaw: nearestTurn(restYaw, 0), elevation: Math.PI / 2 };
      animateTo(to, animate ? TILT_S : 0);
    },
    // Lays the hall back down flat as the map, then calls `done`.
    leave(animate, done) {
      restYaw = animation ? animation.to.yaw : camera.yaw;
      animation = null;
      // Without a plant drawn there are no frames to animate (nothing received yet).
      animateTo({ zoom: 1, centre: null, yaw: nearestTurn(camera.yaw, 0), elevation: Math.PI / 2 },
        animate && active && layout ? TILT_S : 0, done);
    },
    // A quarter turn of the hall: 1 clockwise, -1 the other way.
    turn(direction) {
      if (!layout || !active) return;
      const base = animation ? animation.to : camera;
      const to = { ...base, yaw: base.yaw + (direction * Math.PI) / 2 };
      animation = null;
      animateTo(to, TURN_S, () => {
        restYaw = to.yaw;
      });
    },
    zoomIn: () => zoomBy(1.5),
    zoomOut: () => zoomBy(1 / 1.5),
    fit() {
      if (!layout || !active) return;
      const base = animation ? animation.to : camera;
      animation = null;
      animateTo({ ...base, zoom: 1, centre: null }, TURN_S);
    },
    clearSelection: () => select(null),
    select: (picked) => select(picked),
    setLayout(newLayout) {
      const keep = samePlant(layout, newLayout);
      layout = newLayout;
      belts = new Map(layout.belts.map((belt) => [belt.id, belt]));
      destinations = destinationLooks(layout.outputs);
      sorters = sorterBranches(layout);
      ends = beltEnds(layout);
      desks = layout.inputs.map((input) => ({
        id: input.id, input, belt: layout.belts.find((belt) => belt.source_id === input.id),
      }));
      slides = new Map();
      slideTime = null;
      edges = new Map();
      edgesKey = '';
      playback.reset();
      surfaceOffsets.clear();
      surfaceTime = null;
      newest = null;
      lights = new Map();
      wrongExits = [];
      queues = new Map();
      drawnBags = [];
      queueExtras = new Map();
      if (!keep) camera = { ...camera, zoom: 1, centre: null };
      projection = null;
      buildScene();
      if (!keep || selection?.kind === 'bag') select(null);
    },
    setSnapshot(snapshot) {
      if (newest && isNewRun(newest, snapshot)) {
        if (selection?.kind === 'bag') select(null);
        surfaceOffsets.clear();
        surfaceTime = null;
        wrongExits = [];
        queues = new Map();
        slides = new Map();
        slideTime = null;
      }
      newest = snapshot;
      queues = addQueueSnapshot(queues, snapshot);
      lights = beltLights(snapshot);
      edges = beltStates(snapshot);
      const key = JSON.stringify([...edges]);
      if (key !== edgesKey) {
        edgesKey = key;
        staticDirty = true;
      }
      wrongExits = addWrongExits(wrongExits, snapshot);
      haltedBelts = new Set(snapshot.belts.filter((belt) => belt.stopped || belt.faulty).map((belt) => belt.id));
      playback.add(snapshot, nowSeconds());
      updateCounters();
    },
  };
}
