// WebSocket link to the Python server.
//
// The page connects to /ws on its own address: in development Vite forwards
// it to the Python server, and the same path will work when FastAPI serves
// the page. If the connection drops, it retries every second; on every new
// connection the server sends the layout and a full snapshot again, so the
// page never has to patch an old state.
//
// A link can also die silently (a laptop waking from sleep, a network that
// went away) without the browser closing the socket for a long time. The
// server sends snapshots about 12 times per second, even while paused, so a
// link with no message for STALE_AFTER_MS is treated as lost: the socket is
// closed and a new one opened.

export const RETRY_DELAY_MS = 1000;
export const STALE_AFTER_MS = 3000;
const WATCH_INTERVAL_MS = 500;
// WebSocket readyState values (named here so tests need no browser).
const OPEN = 1;
const CLOSED = 3;

function defaultUrl() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws`;
}

// `createSocket` and `now` can be replaced in tests.
export function connect({
  onMessage, onConnectionChange, url = defaultUrl(),
  createSocket = (address) => new WebSocket(address), now = () => Date.now(),
}) {
  let socket = null;
  let connected = false;
  let lastMessage = 0;

  function setConnected(value) {
    if (value === connected) return;
    connected = value;
    onConnectionChange(value);
  }

  function open() {
    const current = createSocket(url);
    socket = current;
    lastMessage = now();
    // Events of a socket that was replaced are ignored.
    current.addEventListener('open', () => {
      if (current !== socket) return;
      lastMessage = now();
      setConnected(true);
    });
    current.addEventListener('message', (event) => {
      if (current !== socket) return;
      lastMessage = now();
      onMessage(JSON.parse(event.data));
    });
    current.addEventListener('close', () => {
      if (current !== socket) return;
      retry();
    });
  }

  // Gives up the current socket and opens a new one a little later.
  function retry() {
    const old = socket;
    socket = null;
    setConnected(false);
    if (old && old.readyState !== CLOSED) old.close();
    setTimeout(open, RETRY_DELAY_MS);
  }

  function checkStale() {
    if (socket && now() - lastMessage > STALE_AFTER_MS) retry();
  }

  open();
  setInterval(checkStale, WATCH_INTERVAL_MS);

  return {
    // Sends a command such as { type: 'start' }; ignored while disconnected.
    send(command) {
      if (connected && socket?.readyState === OPEN) socket.send(JSON.stringify(command));
    },
    // Checks the link at once, e.g. when a hidden tab becomes visible again
    // (timers of hidden tabs can be slowed down to once a minute).
    checkStale,
  };
}
