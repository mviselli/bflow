// Explicit conversion between engine metres and screen pixels.
//
// The layout places every node and belt end on a map in metres, x to the
// right and y downwards, as on the screen. A belt is a straight segment from
// `start` to `end`; a bag's position_m is its rear edge along the belt and it
// occupies [position_m, position_m + length_m]. Nothing here decides movement
// or collisions: it only maps the engine's numbers onto the screen.

// Graphics-only sizes: the engine has no widths, only lengths along the belt.
export const BELT_WIDTH_M = 1.0;
export const BAGGAGE_WIDTH_M = 0.45;
// Floor shown around the plant, in metres: room for the check-in desks, the
// output chutes and the signs.
export const PLANT_MARGIN_M = 2.2;

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

// Builds the conversion for the whole plant drawn in a screen area. The
// scale is the largest that fits the plant plus its margins; the plant is
// then centred on the screen.
export function plantGeometry(layout, screenWidth, screenHeight) {
  const bounds = plantBounds(layout);
  const widthM = bounds.right - bounds.left + 2 * PLANT_MARGIN_M;
  const heightM = bounds.bottom - bounds.top + 2 * PLANT_MARGIN_M;
  const pixelsPerMetre = Math.max(Math.min(screenWidth / widthM, screenHeight / heightM), 1e-3);
  // Screen position of the map origin (0, 0).
  const originX = screenWidth / 2 - ((bounds.left + bounds.right) / 2) * pixelsPerMetre;
  const originY = screenHeight / 2 - ((bounds.top + bounds.bottom) / 2) * pixelsPerMetre;

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
  };
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

// Whether each end of a belt is free (at an input or an output, drawn with a
// drum) or at a joint (another belt, a merge or a sorter, drawn as a square
// transfer plate). Belt id → { startJoint, endJoint }.
export function beltEnds(layout) {
  const inputIds = new Set(layout.inputs.map((node) => node.id));
  const outputIds = new Set(layout.outputs.map((node) => node.id));
  return new Map(layout.belts.map((belt) => [belt.id, {
    startJoint: !inputIds.has(belt.source_id),
    endJoint: !outputIds.has(belt.target_id),
  }]));
}

// The points where belts meet: every merge and sorter, and every corner
// where one belt feeds the next. Each joint lists the directions (radians)
// in which its belts leave the point, so the drawing can close the others.
export function plantJoints(layout) {
  const beltIds = new Set(layout.belts.map((belt) => belt.id));
  const points = [
    ...[...layout.merges, ...layout.sorters].map((node) => ({ id: node.id, position: node.position })),
    ...layout.belts.filter((belt) => beltIds.has(belt.target_id))
      .map((belt) => ({ id: `${belt.id}>${belt.target_id}`, position: belt.end })),
  ];
  const same = (a, b) => a.x_m === b.x_m && a.y_m === b.y_m;
  return points.map(({ id, position }) => ({
    id,
    position,
    directions: layout.belts.flatMap((belt) => {
      if (same(belt.start, position)) return [beltAngle(belt)];
      if (same(belt.end, position)) return [beltAngle(belt) + Math.PI];
      return [];
    }),
  }));
}
