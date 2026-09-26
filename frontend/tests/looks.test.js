// Bag looks: stable per identifier, varied across bags, destination on the tag.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { SUITCASE_COLOURS, SUITCASE_STYLES, shortCode, suitcaseLook } from '../src/looks.js';

test('short codes come from the last part of an identifier', () => {
  assert.equal(shortCode('input-a'), 'A');
  assert.equal(shortCode('output-1'), '1');
  assert.equal(shortCode('belt'), 'BELT');
});

test('a bag always gets the same look', () => {
  const bag = { id: 'bag-17', destination_id: 'output-1' };
  assert.deepEqual(suitcaseLook(bag), suitcaseLook({ ...bag }));
});

test('the tag shows the destination, independently of the colour', () => {
  const look = suitcaseLook({ id: 'bag-3', destination_id: 'output-2' });
  assert.equal(look.label, '2');
  assert.ok(SUITCASE_STYLES.includes(look.style));
  assert.ok(SUITCASE_COLOURS.includes(look.colour));
});

test('consecutive bags use every style and several colours', () => {
  const looks = Array.from({ length: 30 }, (_, i) => suitcaseLook({ id: `bag-${i + 1}`, destination_id: 'output-1' }));
  assert.equal(new Set(looks.map((look) => look.style)).size, SUITCASE_STYLES.length);
  assert.ok(new Set(looks.map((look) => look.colour)).size >= 6);
});
