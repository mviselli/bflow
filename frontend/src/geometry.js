// Explicit conversion between engine metres and screen pixels.
//
// The engine works in metres along the belt: a bag's position_m is its rear
// edge and it occupies [position_m, position_m + length_m]. The belt runs
// left to right, from the input (position 0) to the output (length_m).
// Nothing here decides movement or collisions: it only maps the engine's
// numbers onto the screen.

// Graphics-only sizes: the engine has no widths, only lengths along the belt.
export const BELT_WIDTH_M = 1.0;
export const BAGGAGE_WIDTH_M = 0.45;
// Floor shown around the belt, in metres: room for the check-in desk, the
// output chute and the signs.
export const SIDE_MARGIN_M = 1.7;
export const VIEW_HEIGHT_M = 3.6;

// Builds the conversion for one belt drawn horizontally in a screen area.
// The scale is the largest that fits both the width (belt plus side margins)
// and the height; the belt is then centred on the screen.
export function beltGeometry(lengthM, screenWidth, screenHeight) {
  if (!(lengthM > 0)) throw new Error('The belt length must be positive');
  const pixelsPerMetre = Math.max(
    Math.min(screenWidth / (lengthM + 2 * SIDE_MARGIN_M), screenHeight / VIEW_HEIGHT_M),
    1e-3,
  );
  const startX = (screenWidth - lengthM * pixelsPerMetre) / 2;
  const centreY = screenHeight / 2;

  return {
    pixelsPerMetre,
    // A length in metres as a length in pixels.
    toPixels: (metres) => metres * pixelsPerMetre,
    // A position along the belt as a screen x coordinate.
    positionToX: (positionM) => startX + positionM * pixelsPerMetre,
    startX,
    endX: startX + lengthM * pixelsPerMetre,
    centreY,
    beltTop: centreY - (BELT_WIDTH_M * pixelsPerMetre) / 2,
    beltHeight: BELT_WIDTH_M * pixelsPerMetre,
  };
}

// Screen rectangle of a bag: from its rear edge to its front edge.
export function baggageRect(geometry, baggage) {
  const height = geometry.toPixels(BAGGAGE_WIDTH_M);
  return {
    x: geometry.positionToX(baggage.position_m),
    y: geometry.centreY - height / 2,
    width: geometry.toPixels(baggage.length_m),
    height,
  };
}
