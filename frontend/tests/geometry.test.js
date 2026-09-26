// Metres → pixels conversion and time formatting, with Node's built-in runner.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  BAGGAGE_WIDTH_M, BELT_WIDTH_M, SIDE_MARGIN_M, VIEW_HEIGHT_M, baggageRect, beltGeometry,
} from '../src/geometry.js';
import { formatTime } from '../src/controls.js';

// A 10 m belt with its margins is 13.4 m wide: 1340 px gives 100 px per metre.
const WIDE = [1340, 1000];

test('the belt and its margins fill the width, centred', () => {
  const geometry = beltGeometry(10, ...WIDE);
  assert.equal(geometry.pixelsPerMetre, 100);
  assert.equal(geometry.startX, SIDE_MARGIN_M * 100);
  assert.equal(geometry.endX, 1340 - SIDE_MARGIN_M * 100);
  assert.equal(geometry.positionToX(0), geometry.startX);
  assert.equal(geometry.positionToX(10), geometry.endX);
  assert.equal(geometry.positionToX(2.5), geometry.startX + 250);
});

test('a short screen limits the scale and keeps the belt centred', () => {
  const geometry = beltGeometry(10, 1340, VIEW_HEIGHT_M * 50);
  assert.equal(geometry.pixelsPerMetre, 50);
  assert.equal(geometry.startX, (1340 - 500) / 2);
  assert.equal(geometry.endX, (1340 + 500) / 2);
});

test('the belt is centred vertically with its width in metres', () => {
  const geometry = beltGeometry(10, ...WIDE);
  assert.equal(geometry.centreY, 500);
  assert.equal(geometry.beltHeight, BELT_WIDTH_M * 100);
  assert.equal(geometry.beltTop, 500 - (BELT_WIDTH_M * 100) / 2);
});

test('a bag spans from its rear edge to its front edge', () => {
  const geometry = beltGeometry(10, ...WIDE);
  const rect = baggageRect(geometry, { position_m: 9.4, length_m: 0.6 });
  assert.equal(rect.x, geometry.positionToX(9.4));
  assert.ok(Math.abs(rect.x + rect.width - geometry.endX) < 1e-9, 'front edge at the end of the belt');
  assert.equal(rect.height, BAGGAGE_WIDTH_M * 100);
  assert.equal(rect.y + rect.height / 2, geometry.centreY);
});

test('the minimum gap between bags keeps its proportion on screen', () => {
  const geometry = beltGeometry(4, 1000, 1000);
  const ahead = baggageRect(geometry, { position_m: 2.0, length_m: 0.6 });
  const behind = baggageRect(geometry, { position_m: 1.2, length_m: 0.6 });
  assert.ok(Math.abs(ahead.x - (behind.x + behind.width) - geometry.toPixels(0.2)) < 1e-9);
});

test('the scale follows the screen width', () => {
  assert.equal(beltGeometry(10, 670, 1000).pixelsPerMetre, 50);
  assert.equal(beltGeometry(6.6, 1000, 1000).pixelsPerMetre, 100);
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
