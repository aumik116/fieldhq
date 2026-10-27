// Shared authenticated request helpers.
let CSRF = '';

// Selection is explicit per page. Reloading on switch clears all drafts/cursors.
const selectedServerId =
  new URLSearchParams(location.search).get('server') || '';
const originalFetch = window.fetch.bind(window);
window.fetch = (input, options = {}) => {
  const url = new URL(
    input instanceof Request ? input.url : input,
    location.href,
  );
  if (
    selectedServerId &&
    url.origin === location.origin &&
    url.pathname.startsWith('/api/')
  ) {
    const headers = new Headers(
      options.headers || (input instanceof Request ? input.headers : undefined),
    );
    if (!headers.has('X-Server-ID'))
      headers.set('X-Server-ID', selectedServerId);
    options = { ...options, headers };
  }
  return originalFetch(input, options);
};

async function readJson(response) {
  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('Please sign in');
  }
  let data;
  try {
    data = await response.json();
  } catch (_) {
    const error = new Error(
      response.status === 413
        ? 'The upload is larger than the server allows. Choose a smaller file.'
        : response.status >= 500
          ? 'The server could not complete this request. Try again; if it continues, copy the error details for an administrator.'
          : `The server returned an unexpected response (HTTP ${response.status}).`,
    );
    error.status = response.status;
    throw error;
  }
  if (!response.ok || data?.ok === false) {
    const error = new Error(
      data?.error || `Request failed (HTTP ${response.status}).`,
    );
    error.status = response.status;
    throw error;
  }
  return data;
}

async function postJson(url, body, options = {}) {
  if (!CSRF) {
    try {
      const r = await fetch('/api/csrf');
      if (r.ok) CSRF = (await r.json()).csrf || '';
    } catch (e) {}
  }
  const headers = new Headers(options.headers);
  headers.set('Content-Type', 'application/json');
  headers.set('X-CSRF-Token', CSRF);
  const r = await fetch(url, {
    ...options,
    method: 'POST',
    headers,
    body: JSON.stringify({ ...(body || {}), _csrf: CSRF }),
  });
  if (r.status === 401) {
    window.location.href = '/login';
    throw new Error('Please sign in');
  }
  if (r.status === 403) {
    // CSRF expired — refresh token and surface error
    try {
      const cr = await fetch('/api/csrf');
      if (cr.ok) CSRF = (await cr.json()).csrf || '';
    } catch (e) {}
  }
  document.dispatchEvent(new CustomEvent('panel-change', { detail: url }));
  return r;
}

const activeServerControls = new Set();
async function controlServer(
  action,
  serverId = selectedServerId,
  serverName = '',
) {
  if (!['start', 'stop', 'restart'].includes(action))
    throw new Error('Unsupported server action');
  if (activeServerControls.has(serverId))
    throw new Error('A server control request is already in progress.');
  activeServerControls.add(serverId);
  const operation = {
    serverId,
    serverName: serverName || serverId || 'Existing server',
    action,
    started: Date.now(),
    state: 'running',
    message: 'Waiting for the server control response.',
  };
  const report = () =>
    document.dispatchEvent(
      new CustomEvent('server-operation', { detail: { ...operation } }),
    );
  report();
  try {
    const result = await readJson(
      await postJson(
        '/api/' + action,
        {},
        { headers: { 'X-Server-ID': serverId } },
      ),
    );
    operation.state = 'success';
    operation.message = `${action[0].toUpperCase() + action.slice(1)} completed. ${action === 'stop' ? 'Server stop request finished.' : 'Open the console to inspect mission startup.'}`;
    report();
    return result;
  } catch (error) {
    operation.state = error.status >= 400 ? 'failed' : 'unknown';
    operation.message =
      operation.state === 'unknown'
        ? 'The response could not be confirmed. The request may still finish; check server status before sending another control request. ' +
          error.message
        : error.message;
    report();
    throw error;
  } finally {
    activeServerControls.delete(serverId);
  }
}

async function postForm(url, formData, options = {}) {
  if (!CSRF) {
    try {
      const r = await fetch('/api/csrf');
      if (r.ok) CSRF = (await r.json()).csrf || '';
    } catch (e) {}
  }
  formData.append('_csrf', CSRF);
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'X-CSRF-Token': CSRF },
    body: formData,
    signal: options.signal,
  });
  if (r.status === 401) {
    window.location.href = '/login';
    throw new Error('Please sign in');
  }
  document.dispatchEvent(new CustomEvent('panel-change', { detail: url }));
  return r;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Coalesce identical GETs; only live roster reads get a short display cache.
const panelReads = new Map();
function readPanelData(url) {
  const previous = panelReads.get(url),
    now = Date.now(),
    ttl = url === '/api/players' ? 2500 : 0;
  if (previous && (previous.pending || now - previous.at < ttl))
    return previous.promise;
  const entry = { at: now, pending: true };
  entry.promise = fetch(url)
    .then(readJson)
    .then((data) => {
      entry.at = Date.now();
      return data;
    })
    .catch((error) => {
      if (panelReads.get(url) === entry) panelReads.delete(url);
      throw error;
    })
    .finally(() => {
      entry.pending = false;
      if (!ttl && panelReads.get(url) === entry) panelReads.delete(url);
    });
  panelReads.set(url, entry);
  return entry.promise;
}
document.addEventListener('panel-change', () => panelReads.clear());
