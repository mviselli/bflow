// WebSocket link to the Python server.
//
// The page connects to /ws on its own address: in development Vite forwards
// it to the Python server, and the same path will work when FastAPI serves
// the page. If the connection drops, it retries every second; on every new
// connection the server sends the layout and a full snapshot again.

const RETRY_DELAY_MS = 1000;

export function connect({ onMessage, onConnectionChange }) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${protocol}//${window.location.host}/ws`;
  let socket = null;

  function open() {
    socket = new WebSocket(url);
    socket.addEventListener('open', () => onConnectionChange(true));
    socket.addEventListener('message', (event) => onMessage(JSON.parse(event.data)));
    socket.addEventListener('close', () => {
      onConnectionChange(false);
      setTimeout(open, RETRY_DELAY_MS);
    });
  }

  open();

  return {
    // Sends a command such as { type: 'start' }; ignored while disconnected.
    send(command) {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(command));
    },
  };
}
