// The side panel (dock) and the rail of pages beside it.
//
// One page is open at a time. A click on a page's rail button opens it; a
// click on the page already open hides the dock, so the map takes the
// whole width, and the next click shows it again. The map stays visible in
// every case. The layout change is a CSS transition (styles.css); the map
// follows the new size smoothly (see the renderer's resize handling).
//
// dockAfterClick() is pure (tested with node --test).

export const PAGES = {
  inspect: 'Details',
  alarms: 'Alarms',
  events: 'Event log',
  operate: 'Controls',
  stats: 'Indicators',
  legend: 'Legend',
};

// The dock's state after a click on a page's rail button.
export function dockAfterClick(state, page) {
  if (state.open && state.page === page) return { page, open: false };
  return { page, open: true };
}

// Remembers the open page between visits, in this browser only. Storage
// can be unavailable (private windows, blocked site data): then the dock
// simply starts on the details page.
const STORAGE_KEY = 'baggageflow.dock';

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved && saved.page in PAGES) return { page: saved.page, open: saved.open !== false };
  } catch {
    // Nothing saved, or storage unavailable.
  }
  return { page: 'inspect', open: true };
}

function saveState(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage unavailable: the dock still works, it just starts fresh next time.
  }
}

// Wires the rail buttons and the pages. `app` is the element whose
// data-dock attribute opens and closes the dock in CSS.
export function createDock(app, { onChange = () => {} } = {}) {
  const buttons = [...app.querySelectorAll('.rail button[data-page]')];
  const pages = [...app.querySelectorAll('.dock .page[data-page]')];
  const title = app.querySelector('#dock-title');
  let state = loadState();

  function show(next) {
    state = next;
    app.dataset.dock = state.open ? 'open' : 'closed';
    title.textContent = PAGES[state.page];
    for (const button of buttons) {
      button.setAttribute('aria-pressed', String(button.dataset.page === state.page));
    }
    for (const page of pages) page.hidden = page.dataset.page !== state.page;
    saveState(state);
    onChange(state);
  }

  for (const button of buttons) {
    button.addEventListener('click', () => show(dockAfterClick(state, button.dataset.page)));
  }
  app.querySelector('#dock-close').addEventListener('click', () => show({ ...state, open: false }));
  show(state);

  return {
    // Opens a page (and the dock, if hidden).
    open(page) {
      if (!state.open || state.page !== page) show({ page, open: true });
    },
    get state() {
      return state;
    },
  };
}
