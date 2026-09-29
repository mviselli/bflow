// Bag looks: stable per identifier, varied across bags, destination on the tag.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  DESTINATION_COLOURS, SUITCASE_COLOURS, SUITCASE_STYLES, destinationLooks, shortCode, suitcaseLook,
} from '../src/looks.js';

const OUTPUTS = [{ id: 'output-1' }, { id: 'output-2' }, { id: 'output-3' }];
const destinations = destinationLooks(OUTPUTS);

test('short codes come from the last part of an identifier', () => {
  assert.equal(shortCode('input-a'), 'A');
  assert.equal(shortCode('output-1'), '1');
  assert.equal(shortCode('belt'), 'BELT');
});

test('each output gets its code and a distinct colour, in layout order', () => {
  assert.deepEqual([...destinations], [
    ['output-1', { code: '1', colour: DESTINATION_COLOURS[0] }],
    ['output-2', { code: '2', colour: DESTINATION_COLOURS[1] }],
    ['output-3', { code: '3', colour: DESTINATION_COLOURS[2] }],
  ]);
});

test('a bag always gets the same look', () => {
  const bag = { id: 'bag-17', destination_id: 'output-1' };
  assert.deepEqual(suitcaseLook(bag, destinations), suitcaseLook({ ...bag }, destinations));
});

test('the tag shows the destination, independently of the body colour', () => {
  const look = suitcaseLook({ id: 'bag-3', destination_id: 'output-2' }, destinations);
  assert.equal(look.label, '2');
  assert.equal(look.tagColour, DESTINATION_COLOURS[1]);
  assert.ok(SUITCASE_STYLES.includes(look.style));
  assert.ok(SUITCASE_COLOURS.includes(look.colour));
  // Same bag, other destination: same body, other tag.
  const other = suitcaseLook({ id: 'bag-3', destination_id: 'output-3' }, destinations);
  assert.equal(other.colour, look.colour);
  assert.equal(other.tagColour, DESTINATION_COLOURS[2]);
});

test('an unknown destination still shows its code', () => {
  assert.equal(suitcaseLook({ id: 'bag-1', destination_id: 'output-9' }, destinations).label, '9');
});

test('consecutive bags use every style and several colours', () => {
  const looks = Array.from({ length: 30 },
    (_, i) => suitcaseLook({ id: `bag-${i + 1}`, destination_id: 'output-1' }, destinations));
  assert.equal(new Set(looks.map((look) => look.style)).size, SUITCASE_STYLES.length);
  assert.ok(new Set(looks.map((look) => look.colour)).size >= 6);
});
