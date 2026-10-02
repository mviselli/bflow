// WebSocket link: retries, silent links and commands while disconnected.
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';
import { RETRY_DELAY_MS, STALE_AFTER_MS, connect } from '../src/connection.js';

// A socket the test opens, feeds and closes by hand.
class FakeSocket extends EventTarget {
  constructor() {
    super();
    this.readyState = 0;
    this.sent = [];
  }

  serverOpens() {
    this.readyState = 1;
    this.dispatchEvent(new Event('open'));
  }

  serverSends(message) {
    const event = new Event('message');
    event.data = JSON.stringify(message);
    this.dispatchEvent(event);
  }

  send(data) {
    this.sent.push(JSON.parse(data));
  }

  close() {
    this.readyState = 3;
    this.dispatchEvent(new Event('close'));
  }
}

function setup(t) {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'], now: 0 });
  t.after(() => mock.timers.reset());
  const sockets = [];
  const changes = [];
  const messages = [];
  const link = connect({
    url: 'ws://test/ws',
    createSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    onConnectionChange: (connected) => changes.push(connected),
    onMessage: (message) => messages.push(message),
  });
  return { link, sockets, changes, messages };
}

test('a closed connection is reported once and retried after a second', (t) => {
  const { sockets, changes } = setup(t);
  sockets[0].serverOpens();
  sockets[0].close();
  assert.deepEqual(changes, [true, false]);
  mock.timers.tick(RETRY_DELAY_MS - 1);
  assert.equal(sockets.length, 1);
  mock.timers.tick(1);
  assert.equal(sockets.length, 2);
  sockets[1].serverOpens();
  assert.deepEqual(changes, [true, false, true]);
});

test('a link silent for too long is closed and opened again', (t) => {
  const { sockets, changes } = setup(t);
  sockets[0].serverOpens();
  // Snapshots keep it alive.
  for (let i = 0; i < 10; i += 1) {
    mock.timers.tick(1000);
    sockets[0].serverSends({ type: 'snapshot' });
  }
  assert.deepEqual(changes, [true]);
  // Then nothing arrives, and the browser does not close the socket.
  mock.timers.tick(STALE_AFTER_MS + 500);
  assert.deepEqual(changes, [true, false]);
  assert.equal(sockets[0].readyState, 3);
  mock.timers.tick(RETRY_DELAY_MS);
  assert.equal(sockets.length, 2);
});

test('events of a replaced socket are ignored', (t) => {
  const { sockets, changes, messages } = setup(t);
  sockets[0].serverOpens();
  mock.timers.tick(STALE_AFTER_MS + 500);
  mock.timers.tick(RETRY_DELAY_MS);
  sockets[1].serverOpens();
  sockets[0].serverSends({ type: 'snapshot', tick: 1 });
  sockets[0].dispatchEvent(new Event('close'));
  assert.deepEqual(messages, []);
  assert.deepEqual(changes, [true, false, true]);
});

test('commands are sent only while connected', (t) => {
  const { link, sockets } = setup(t);
  link.send({ type: 'start' });
  sockets[0].serverOpens();
  link.send({ type: 'pause' });
  sockets[0].close();
  link.send({ type: 'reset' });
  assert.deepEqual(sockets[0].sent, [{ type: 'pause' }]);
});
