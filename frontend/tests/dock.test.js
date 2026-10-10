// Side panel pages: which page is open and whether the panel is shown.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { PAGES, dockAfterClick } from '../src/dock.js';

test('a click on another page opens it, showing the panel if it was hidden', () => {
  assert.deepEqual(dockAfterClick({ page: 'inspect', open: true }, 'alarms'), { page: 'alarms', open: true });
  assert.deepEqual(dockAfterClick({ page: 'inspect', open: false }, 'alarms'), { page: 'alarms', open: true });
});

test('a click on the page already open hides the panel, and the next one shows it again', () => {
  const hidden = dockAfterClick({ page: 'alarms', open: true }, 'alarms');
  assert.deepEqual(hidden, { page: 'alarms', open: false });
  assert.deepEqual(dockAfterClick(hidden, 'alarms'), { page: 'alarms', open: true });
});

test('every page has a title', () => {
  assert.deepEqual(Object.keys(PAGES), ['inspect', 'alarms', 'events', 'operate', 'stats', 'legend']);
  assert.ok(Object.values(PAGES).every((title) => title.length > 0));
});
