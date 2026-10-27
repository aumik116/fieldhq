// Show configuration, queued additions and downloaded versions as separate states.
(() => {
  const root = document.getElementById('mod-lifecycle-summary'),
    panel = document.getElementById('panel-mods');
  if (!root) return;
  let configured = typeof modLibrary === 'undefined' ? [] : modLibrary.mods,
    queued = null,
    downloaded = null,
    downloadedPartial = false,
    busy = false,
    timer,
    lastDraw = '';
  const label = document.createElement('label');
  label.className = 'mod-pinned-filter';
  label.innerHTML =
    '<input type="checkbox" id="mods-pinned-only"> Pinned versions only';
  document.getElementById('mods-search').parentElement.append(label);
  label.querySelector('input').onchange = () => {
    modLibrary.page = 1;
    drawModLibrary();
  };
  function draw() {
    const signature = JSON.stringify([
      configured.length,
      configured.filter((mod) => !!mod.version).length,
      queued,
      downloaded,
      downloadedPartial,
      typeof can !== 'function' || can('mods'),
      panel.querySelector('.section-tabs [aria-selected="true"]')?.id,
    ]);
    if (signature === lastDraw) return;
    lastDraw = signature;
    const pinned = configured.filter((mod) => !!mod.version).length;
    root.replaceChildren();
    for (const [text, value, action] of [
      [
        'Configured',
        configured.length,
        () => {
          document.getElementById('mods-search').value = '';
          document.getElementById('mods-pinned-only').checked = false;
          modLibrary.page = 1;
          drawModLibrary();
          document.getElementById('section-tab-mods-installed').click();
        },
      ],
      [
        'Queued additions',
        queued,
        () => document.getElementById('mod-draft-open').click(),
      ],
      [
        'Downloaded versions',
        downloaded,
        () => document.getElementById('section-tab-mods-downloaded').click(),
      ],
      [
        'Pinned',
        pinned,
        () => {
          document.getElementById('section-tab-mods-installed').click();
          document.getElementById('mods-pinned-only').checked = true;
          document.getElementById('mods-search').value = '';
          modLibrary.page = 1;
          drawModLibrary();
        },
      ],
    ]) {
      const button = document.createElement('button');
      button.type = 'button';
      if (
        text === 'Queued additions' &&
        typeof can === 'function' &&
        !can('mods')
      ) {
        button.disabled = true;
        button.title = 'Manager access is required to change the queue';
      }
      const count = document.createElement('strong');
      count.textContent = value === null ? '—' : String(value);
      if (text === 'Downloaded versions' && downloadedPartial && value !== null)
        count.textContent += '+';
      if (text === 'Downloaded versions' && downloadedPartial)
        button.title = 'Partial inventory: this count is a lower bound';
      const caption = document.createElement('span');
      caption.textContent = text;
      button.append(count, caption);
      button.onclick = action;
      root.append(button);
    }
    const active =
      panel.querySelector('.section-tabs [aria-selected="true"]')?.id || '';
    document.getElementById('mod-lifecycle-help').textContent = active.endsWith(
      'downloaded',
    )
      ? 'Downloaded files are local versions on this server. A downloaded mod can be configured, a dependency, or unused. Removing it from configuration keeps its files unless you explicitly delete them.'
      : active.endsWith('installed')
        ? 'Configured mods are saved in the server configuration. Unpinned versions track latest; pins keep an explicit version. Changes load on the next start or restart.'
        : active.endsWith('updates')
          ? 'Update review compares configured pins with available versions. Review and save changes before restarting.'
          : active.endsWith('compare')
            ? 'Compare an external or saved mod list before choosing changes. Comparing alone does not change server configuration.'
            : active.endsWith('presets')
              ? 'Presets save reusable mod and scenario selections. Applying a preset changes configuration; restart when ready to load it.'
              : 'Add now saves a mod to configuration. Add to queue holds additions for review. Queued mods are not configured until you apply the queue.';
  }
  async function refresh() {
    clearTimeout(timer);
    if (panel.hidden || document.hidden || busy) return;
    busy = true;
    try {
      const results = await Promise.allSettled([
        fetch('/api/mods/draft').then(readJson),
        fetch('/api/mods/downloaded').then(readJson),
      ]);
      queued =
        results[0].status === 'fulfilled'
          ? results[0].value.entries.length
          : null;
      downloaded =
        results[1].status === 'fulfilled' && results[1].value.status === 'ready'
          ? results[1].value.mods.length
          : null;
      downloadedPartial =
        results[1].status === 'fulfilled' && !!results[1].value.partial;
    } finally {
      busy = false;
      draw();
      timer = setTimeout(refresh, downloaded === null ? 3000 : 15000);
    }
  }
  document.addEventListener('mod-library-state', (event) => {
    configured = event.detail;
    draw();
  });
  document.addEventListener('panel-change', (event) => {
    if (/^\/api\/(mods|config|workshop|presets)/.test(event.detail)) {
      clearTimeout(timer);
      timer = setTimeout(refresh, 250);
    }
  });
  panel.addEventListener('click', (event) => {
    if (event.target.closest('.section-tabs')) requestAnimationFrame(draw);
  });
  new MutationObserver(() => {
    if (!panel.hidden) refresh();
    else clearTimeout(timer);
  }).observe(panel, { attributes: true, attributeFilter: ['hidden'] });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });
  draw();
  refresh();
})();
