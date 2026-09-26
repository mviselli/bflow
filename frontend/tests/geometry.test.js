// Metres → pixels conversion and time formatting, with Node's built-in runner.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { BAGGAGE_WIDTH_M, BELT_WIDTH_M, MARGIN_PX, baggageRect, beltGeometry } from '../src/geometry.js';
import { formatTime } from '../src/controls.js';

test('the belt length fills the width between the margins', () => {
  const geometry = beltGeometry(10, 2 * MARGIN_PX + 800, 400);
  assert.equal(geometry.pixelsPerMetre, 80);
  assert.equal(geometry.startX, MARGIN_PX);
  assert.equal(geometry.endX, MARGIN_PX + 800);
  assert.equal(geometry.positionToX(0), geometry.startX);
  assert.equal(geometry.positionToX(10), geometry.endX);
  assert.equal(geometry.positionToX(2.5), MARGIN_PX + 200);
});

test('the belt is centred vertically with its width in metres', () => {
  const geometry = beltGeometry(10, 2 * MARGIN_PX + 800, 400);
  assert.equal(geometry.centreY, 200);
  assert.equal(geometry.beltHeight, BELT_WIDTH_M * 80);
  assert.equal(geometry.beltTop, 200 - (BELT_WIDTH_M * 80) / 2);
});

test('a bag spans from its rear edge to its front edge', () => {
  const geometry = beltGeometry(10, 2 * MARGIN_PX + 800, 400);
  const rect = baggageRect(geometry, { position_m: 9.4, length_m: 0.6 });
  assert.equal(rect.x, geometry.positionToX(9.4));
  assert.ok(Math.abs(rect.x + rect.width - geometry.endX) < 1e-9, 'front edge at the end of the belt');
  assert.equal(rect.height, BAGGAGE_WIDTH_M * 80);
  assert.equal(rect.y + rect.height / 2, geometry.centreY);
});

test('the minimum gap between bags keeps its proportion on screen', () => {
  const geometry = beltGeometry(4, 2 * MARGIN_PX + 400, 300);
  const ahead = baggageRect(geometry, { position_m: 2.0, length_m: 0.6 });
  const behind = baggageRect(geometry, { position_m: 1.2, length_m: 0.6 });
  assert.ok(Math.abs(ahead.x - (behind.x + behind.width) - geometry.toPixels(0.2)) < 1e-9);
});

test('the scale follows the screen width', () => {
  assert.equal(beltGeometry(10, 2 * MARGIN_PX + 400, 300).pixelsPerMetre, 40);
  assert.equal(beltGeometry(5, 2 * MARGIN_PX + 400, 300).pixelsPerMetre, 80);
});

test('an invalid belt length is rejected', () => {
  assert.throws(() => beltGeometry(0, 800, 400));
  assert.throws(() => beltGeometry(Number.NaN, 800, 400));
});

test('simulated time is shown as minutes and seconds', () => {
  assert.equal(formatTime(0), '00:00.00');
  assert.equal(formatTime(1.05), '00:01.05');
  assert.equal(formatTime(61.5), '01:01.50');
  assert.equal(formatTime(600), '10:00.00');
});
