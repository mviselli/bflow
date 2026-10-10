// Explicit conversion between engine metres and screen pixels.
//
// The layout places every node and belt end on a map in metres, x to the
// right and y downwards, as on the screen. A belt is a straight segment from
// `start` to `end`; a bag's position_m is its rear edge along the belt and it
// occupies [position_m, position_m + length_m]. Nothing here decides movement
// or collisions: it only maps the engine's numbers onto the screen.

// Graphics-only sizes: the engine has no widths, only lengths along the belt.
// The belt width matches the engine's JUNCTION_SIZE_M: the transfer plate of
// a merge or sorter is a square as wide as a belt, and a belt joining from the
// side ends at its edge.
export const BELT_WIDTH_M = 1.0;
export const BAGGAGE_WIDTH_M = 0.45;
// A check-in desk stands behind the start of its belt: from DESK_SPAN.fromM
// to DESK_SPAN.toM along the belt (negative: before its start), widthM wide.
// Used to pick and outline a desk; assets.js draws it inside this area.
export const DESK_SPAN = { fromM: -1.6, toM: 0, widthM: 2.2 };
// Floor shown around the plant, in metres: room for the check-in desks, the
// queue lane beside an outer desk, the output chutes and the signs behind
// the desks.
export const PLANT_MARGIN_M = 3;

// Smallest rectangle holding every node and belt end of the layout.
export function plantBounds(layout) {
  const points = [
    ...[...layout.inputs, ...layout.merges, ...layout.sorters, ...layout.outputs]
      .map((node) => node.position),
    ...layout.belts.flatMap((belt) => [belt.start, belt.end]),
  ];
  if (points.length === 0) throw new Error('The layout has nothing to draw');
  const xs = points.map((point) => point.x_m);
  const ys = points.map((point) => point.y_m);
  return {
    left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys),
  };
}

// The camera: how much the view is magnified (1 = the whole plant fits) and
// the map point shown at the centre of the screen (null = the plant's centre).
// True when two layout messages describe the same plant, whatever the tick
// they were sent at: after a reconnection to the same plant the page keeps
// its view and the selected belt or desk.
export function samePlant(a, b) {
  if (!a || !b) return false;
  const plant = ({ tick, time_s, ...rest }) => JSON.stringify(rest);
  return plant(a) === plant(b);
}

export const FIT_CAMERA = { zoom: 1, centre: null };
export const MAX_ZOOM = 6;

// Scale at which the plant plus its margins just fits the screen area.
function fitScale(bounds, screenWidth, screenHeight) {
  const widthM = bounds.right - bounds.left + 2 * PLANT_MARGIN_M;
  const heightM = bounds.bottom - bounds.top + 2 * PLANT_MARGIN_M;
  return Math.max(Math.min(screenWidth / widthM, screenHeight / heightM), 1e-3);
}

// Builds the conversion for the plant drawn in a screen area, seen through
// the camera. With FIT_CAMERA the scale is the largest that fits the plant
// plus its margins, and the plant is centred on the screen.
export function plantGeometry(layout, screenWidth, screenHeight, camera = FIT_CAMERA) {
  const bounds = plantBounds(layout);
  const pixelsPerMetre = fitScale(bounds, screenWidth, screenHeight) * camera.zoom;
  const centre = camera.centre
    ?? { x_m: (bounds.left + bounds.right) / 2, y_m: (bounds.top + bounds.bottom) / 2 };
  // Screen position of the map origin (0, 0).
  const originX = screenWidth / 2 - centre.x_m * pixelsPerMetre;
  const originY = screenHeight / 2 - centre.y_m * pixelsPerMetre;

  return {
    pixelsPerMetre,
    originX,
    originY,
    bounds,
    // A length in metres as a length in pixels.
    toPixels: (metres) => metres * pixelsPerMetre,
    // A map point in metres as a screen point in pixels.
    toScreen: (point) => ({
      x: originX + point.x_m * pixelsPerMetre,
      y: originY + point.y_m * pixelsPerMetre,
    }),
    // A screen point in pixels as a map point in metres: the inverse, used to
    // find what the pointer is on.
    toMap: (screen) => ({
      x_m: (screen.x - originX) / pixelsPerMetre,
      y_m: (screen.y - originY) / pixelsPerMetre,
    }),
  };
}

// Keeps a camera within limits: zoom between 1 and MAX_ZOOM, and a centre
// that never shows more than the area seen with the whole plant fitted, so
// the plant cannot be dragged off the screen.
export function clampCamera(layout, camera, screenWidth, screenHeight) {
  const zoom = Math.min(Math.max(camera.zoom, 1), MAX_ZOOM);
  const fitted = plantGeometry(layout, screenWidth, screenHeight);
  const topLeft = fitted.toMap({ x: 0, y: 0 });
  const bottomRight = fitted.toMap({ x: screenWidth, y: screenHeight });
  const halfWidth = (bottomRight.x_m - topLeft.x_m) / zoom / 2;
  const halfHeight = (bottomRight.y_m - topLeft.y_m) / zoom / 2;
  const centre = camera.centre ?? fitted.toMap({ x: screenWidth / 2, y: screenHeight / 2 });
  const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
  return {
    zoom,
    centre: {
      x_m: clamp(centre.x_m, topLeft.x_m + halfWidth, bottomRight.x_m - halfWidth),
      y_m: clamp(centre.y_m, topLeft.y_m + halfHeight, bottomRight.y_m - halfHeight),
    },
  };
}

// The camera after zooming by `factor` around a screen point, which keeps
// the map point under it in place (the pointer, for the mouse wheel).
export function zoomAround(layout, camera, screenWidth, screenHeight, screen, factor) {
  const before = plantGeometry(layout, screenWidth, screenHeight, camera);
  const anchor = before.toMap(screen);
  const zoom = Math.min(Math.max(camera.zoom * factor, 1), MAX_ZOOM);
  const pixelsPerMetre = before.pixelsPerMetre * (zoom / camera.zoom);
  const centre = {
    x_m: anchor.x_m - (screen.x - screenWidth / 2) / pixelsPerMetre,
    y_m: anchor.y_m - (screen.y - screenHeight / 2) / pixelsPerMetre,
  };
  return clampCamera(layout, { zoom, centre }, screenWidth, screenHeight);
}

// The camera after dragging the map by (dx, dy) screen pixels.
export function panBy(layout, camera, screenWidth, screenHeight, dx, dy) {
  const geometry = plantGeometry(layout, screenWidth, screenHeight, camera);
  const centre = geometry.toMap({ x: screenWidth / 2 - dx, y: screenHeight / 2 - dy });
  return clampCamera(layout, { zoom: camera.zoom, centre }, screenWidth, screenHeight);
}

// Direction of travel of a belt, in radians (0 = right, π/2 = down).
export function beltAngle(belt) {
  return Math.atan2(belt.end.y_m - belt.start.y_m, belt.end.x_m - belt.start.x_m);
}

// The map point at a distance along a belt, from its start.
export function pointAlong(belt, distanceM) {
  const fraction = distanceM / belt.length_m;
  return {
    x_m: belt.start.x_m + (belt.end.x_m - belt.start.x_m) * fraction,
    y_m: belt.start.y_m + (belt.end.y_m - belt.start.y_m) * fraction,
  };
}

// Where a bag is drawn: the screen point of its centre, from the middle of
// [position_m, position_m + length_m] along its belt, and the belt's angle.
export function baggagePlacement(geometry, belt, baggage) {
  return {
    ...geometry.toScreen(pointAlong(belt, baggage.position_m + baggage.length_m / 2)),
    angle: beltAngle(belt),
  };
}

function distance(a, b) {
  return Math.hypot(b.x_m - a.x_m, b.y_m - a.y_m);
}

// The centre of the joint where a bag passes from belt `from` to belt `to`:
// where the two belts' lines cross. A belt joining from the side stops at the
// edge of the plate, so this can lie a little past its end. Belts in line
// meet where one ends and the other starts.
export function jointPoint(from, to) {
  const d1 = { x: from.end.x_m - from.start.x_m, y: from.end.y_m - from.start.y_m };
  const d2 = { x: to.end.x_m - to.start.x_m, y: to.end.y_m - to.start.y_m };
  const cross = d1.x * d2.y - d1.y * d2.x;
  if (Math.abs(cross) < 1e-9) return from.end;
  const dx = to.start.x_m - from.start.x_m;
  const dy = to.start.y_m - from.start.y_m;
  const along = (dx * d2.y - dy * d2.x) / cross;
  return { x_m: from.start.x_m + d1.x * along, y_m: from.start.y_m + d1.y * along };
}

// Whether each end of a belt is free (at an input or an output, drawn with a
// drum) or at a joint (another belt, a merge or a sorter, drawn as a square
// transfer plate), and how much of the belt the plate covers at each end: half
// a plate for a belt reaching the joint's centre, nothing for one stopping at
// its edge. Belt id → { startJoint, endJoint, startTrimM, endTrimM }.
export function beltEnds(layout) {
  const inputIds = new Set(layout.inputs.map((node) => node.id));
  const outputIds = new Set(layout.outputs.map((node) => node.id));
  const centres = new Map([...layout.merges, ...layout.sorters]
    .map((node) => [node.id, node.position]));
  // A belt-to-belt corner is centred where the two belts meet.
  const trim = (point, centre) => Math.max(BELT_WIDTH_M / 2 - distance(point, centre ?? point), 0);
  return new Map(layout.belts.map((belt) => {
    const startJoint = !inputIds.has(belt.source_id);
    const endJoint = !outputIds.has(belt.target_id);
    return [belt.id, {
      startJoint,
      endJoint,
      startTrimM: startJoint ? trim(belt.start, centres.get(belt.source_id)) : 0,
      endTrimM: endJoint ? trim(belt.end, centres.get(belt.target_id)) : 0,
    }];
  }));
}

// The points where belts meet: every merge and sorter, and every corner
// where one belt feeds the next. Each joint lists the directions (radians)
// in which its belts leave the point, so the drawing can close the others.
export function plantJoints(layout) {
  const beltIds = new Set(layout.belts.map((belt) => belt.id));
  const nodes = [...layout.merges, ...layout.sorters].map((node) => ({
    id: node.id,
    position: node.position,
    directions: layout.belts.flatMap((belt) => {
      if (belt.source_id === node.id) return [beltAngle(belt)];
      if (belt.target_id === node.id) return [beltAngle(belt) + Math.PI];
      return [];
    }),
  }));
  const corners = layout.belts.filter((belt) => beltIds.has(belt.target_id)).map((belt) => {
    const next = layout.belts.find((other) => other.id === belt.target_id);
    return {
      id: `${belt.id}>${next.id}`,
      position: belt.end,
      directions: [beltAngle(next), beltAngle(belt) + Math.PI],
    };
  });
  return [...nodes, ...corners];
}

// A map point in the frame of a belt: `along` from its start in the
// direction of travel, `across` from its centre line.
function inBeltFrame(belt, point) {
  const ux = (belt.end.x_m - belt.start.x_m) / belt.length_m;
  const uy = (belt.end.y_m - belt.start.y_m) / belt.length_m;
  const dx = point.x_m - belt.start.x_m;
  const dy = point.y_m - belt.start.y_m;
  return { along: dx * ux + dy * uy, across: dy * ux - dx * uy };
}

// What is under a map point: a bag if the point is on one (bags are drawn
// above the belts), otherwise a check-in desk, otherwise a belt, otherwise
// null. `bags` are the bags as drawn (belt and position_m), `belts` maps ids
// to the layout's belts, `desks` lists { id, belt } for each input and the
// belt it feeds, and `toleranceM` widens every shape a little so small bags
// are easy to hit. When shapes overlap (a bag crossing a plate, belts
// meeting at a joint) the one whose centre line is nearest wins. Returns
// { kind: 'bag' | 'input' | 'belt', id } or null.
export function pickAt(point, bags, belts, toleranceM = 0, desks = []) {
  let best = null;
  for (const bag of bags) {
    const belt = belts.get(bag.conveyor_id);
    if (!belt) continue;
    const { along, across } = inBeltFrame(belt, point);
    const fromCentre = Math.abs(along - (bag.position_m + bag.length_m / 2));
    const hit = fromCentre <= bag.length_m / 2 + toleranceM
      && Math.abs(across) <= BAGGAGE_WIDTH_M / 2 + toleranceM;
    const distance = Math.hypot(fromCentre, across);
    if (hit && (!best || distance < best.distance)) best = { kind: 'bag', id: bag.id, distance };
  }
  if (best) return { kind: best.kind, id: best.id };
  for (const desk of desks) {
    const { along, across } = inBeltFrame(desk.belt, point);
    if (along >= DESK_SPAN.fromM && along <= DESK_SPAN.toM
      && Math.abs(across) <= DESK_SPAN.widthM / 2) return { kind: 'input', id: desk.id };
  }
  for (const belt of belts.values()) {
    const { along, across } = inBeltFrame(belt, point);
    const hit = along >= -toleranceM && along <= belt.length_m + toleranceM
      && Math.abs(across) <= BELT_WIDTH_M / 2 + toleranceM;
    if (hit && (!best || Math.abs(across) < best.distance)) {
      best = { kind: 'belt', id: belt.id, distance: Math.abs(across) };
    }
  }
  return best && { kind: best.kind, id: best.id };
}
