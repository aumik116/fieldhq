// Platform-only presentation; existing unit/account APIs enforce authorization.
(() => {
  const el = (id) => document.getElementById(id),
    esc = escHtml;
  const read = async (url) => readJson(await fetch(url));
  const write = async (url, data) => readJson(await postJson(url, data));
  const dialog = el('platform-unit-dialog'),
    form = el('platform-unit-form');
  let listing,
    active,
    cursor,
    loading = false,
    unitLoading = false,
    saving = false,
    baseline = '',
    edited;
  const signature = () => JSON.stringify([...new FormData(form)]);
  const dirty = () => dialog.open && signature() !== baseline;
  function close() {
    if (saving || (dirty() && !confirm('Discard unsaved unit settings?')))
      return;
    dialog.close();
  }
  el('platform-unit-close').onclick = close;
  dialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    close();
  });
  window.addEventListener('beforeunload', (event) => {
    const accountDirty =
      typeof userEditorDialog !== 'undefined' &&
      userEditorDialog?.open &&
      userEditorSignature() !== userEditorBaseline;
    if (saving || dirty() || accountDirty) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  async function units() {
    if (unitLoading) return;
    unitLoading = true;
    const button = el('platform-units-refresh');
    button.disabled = true;
    el('platform-units-status').textContent = 'Loading units…';
    try {
      listing = await read('/api/units');
      el('platform-units-list').innerHTML =
        listing.units
          .map(
            (unit) =>
              `<article class="unit-block feature-row"><div class="account-list-identity"><strong>${esc(unit.name)}</strong><small class="unit-meta">${esc(unit.tag || 'No short tag')} · ${unit.servers.length} linked servers</small></div><div class="formation-actions"><a class="manager-link" href="/units?unit=${unit.id}">Open unit</a><button type="button" data-unit-edit="${unit.id}">Unit settings</button></div></article>`,
          )
          .join('') ||
        '<p class="unit-empty">No units yet. Create a unit to start its roster.</p>';
      el('platform-units-list')
        .querySelectorAll('[data-unit-edit]')
        .forEach((button) => {
          button.onclick = () =>
            unitEditor(
              listing.units.find(
                (unit) => unit.id === Number(button.dataset.unitEdit),
              ),
            );
        });
      el('platform-units-status').textContent = `${listing.units.length} units`;
    } catch (error) {
      el('platform-units-status').textContent = error.message;
    } finally {
      unitLoading = false;
      button.disabled = false;
    }
  }
  async function unitEditor(unit = null) {
    try {
      if (!listing) {
        await units();
        if (!listing) return;
      }
      edited = unit;
      el('platform-unit-title').textContent = unit
        ? `Unit settings — ${unit.name}`
        : 'New unit';
      el('platform-unit-error').textContent = '';
      el('platform-unit-body').innerHTML =
        `<div class="unit-form-grid"><label class="unit-field">Unit name<input name="name" value="${esc(unit?.name || '')}" maxlength="80" required></label><label class="unit-field">Short tag<input name="tag" value="${esc(unit?.tag || '')}" maxlength="16"></label></div><h3>Linked servers</h3><p class="feature-note">Linking provides unit health visibility. Hosting permissions are assigned separately.</p><div class="unit-checks">${listing.servers.map((server) => `<label><input type="checkbox" name="servers" value="${esc(server.id)}" ${unit?.servers.includes(server.id) ? 'checked' : ''}> ${esc(server.name)}</label>`).join('') || '<p>No servers available to link.</p>'}</div>`;
      baseline = signature();
      PanelUI.open(dialog);
    } catch (error) {
      el('platform-units-status').textContent = error.message;
    }
  }
  form.onsubmit = async (event) => {
    event.preventDefault();
    if (saving) return;
    saving = true;
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    el('platform-unit-error').textContent = '';
    try {
      const values = new FormData(form);
      await write('/api/units', {
        name: values.get('name'),
        tag: values.get('tag'),
        servers: values.getAll('servers'),
        ...(edited ? { id: edited.id, revision: edited.revision } : {}),
      });
      dialog.close();
      await units();
    } catch (error) {
      el('platform-unit-error').textContent =
        error.message +
        ' Your changes are still here. Reopen unit settings if the unit changed elsewhere.';
    } finally {
      saving = false;
      button.disabled = false;
    }
  };
  el('platform-new-unit').onclick = () => unitEditor();
  el('platform-units-refresh').onclick = units;
  el('platform-demo').onclick = async () => {
    if (
      !(await PanelUI.confirm(
        'Create an editable fictional company with 48 members, formations, qualifications, SOPs and sample loadouts? If the demo already exists, it opens without resetting your edits.',
        'Create / open demo unit',
      ))
    )
      return;
    const button = el('platform-demo');
    button.disabled = true;
    try {
      const data = await write('/api/units/demo', {});
      location.href = `/units?unit=${data.id}&tab=roster`;
    } catch (error) {
      el('platform-units-status').textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
  async function activity(append = false) {
    if (loading) return;
    loading = true;
    el('platform-activity-status').textContent = 'Loading activity…';
    try {
      const data = await read(
        '/api/platform/activity' +
          (append && cursor ? '?before=' + cursor : ''),
      );
      const root = el('platform-activity-list');
      if (!append) root.replaceChildren();
      for (const item of data.events) {
        const row = document.createElement('article');
        row.className = 'unit-block';
        row.innerHTML = `<strong>${esc(item.action)}</strong> · ${esc(item.outcome)}<p class="feature-note">${esc(item.actor)} · ${esc(new Date(item.ts * 1000).toLocaleString())}</p><details><summary>Details</summary><pre>${esc(JSON.stringify(item.details, null, 2))}</pre></details>`;
        root.append(row);
      }
      cursor = data.next_before;
      el('platform-activity-more').hidden = !cursor;
      el('platform-activity-status').textContent = root.children.length
        ? ''
        : 'No activity recorded.';
    } catch (error) {
      el('platform-activity-status').textContent = error.message;
    } finally {
      loading = false;
    }
  }
  el('platform-activity-refresh').onclick = () => activity();
  el('platform-activity-more').onclick = () => activity(true);
  async function settings() {
    try {
      const data = await read('/api/platform/summary');
      el('platform-settings-values').innerHTML = `<dl class="platform-facts">${[
        ['Panel address', location.origin],
        ['Panel mode', data.mode],
        ['Listening port', data.port],
        ['Owner', data.owner],
        ['Accounts', data.accounts],
        ['Units', data.units],
        ['Hosting servers', data.servers],
      ]
        .map(
          ([label, value]) =>
            `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`,
        )
        .join('')}</dl>`;
    } catch (error) {
      el('platform-settings-values').textContent = error.message;
    }
  }
  function select(tab, push = false) {
    if (!['accounts', 'units', 'backups', 'activity', 'settings'].includes(tab))
      tab = 'accounts';
    if (
      tab !== active &&
      typeof userEditorDialog !== 'undefined' &&
      userEditorDialog?.open
    ) {
      closeUserEditor();
      if (userEditorDialog.open) return;
    }
    if (tab !== active && dialog.open) {
      close();
      if (dialog.open) return;
    }
    active = tab;
    document.querySelectorAll('[data-platform-section]').forEach((section) => {
      section.hidden = section.dataset.platformSection !== tab;
    });
    document.querySelectorAll('[data-platform-tab]').forEach((link) => {
      if (link.dataset.platformTab === tab)
        link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (push) history.pushState(null, '', '/admin?tab=' + tab);
    document.body.classList.remove('platform-navigation-open');
    el('platform-menu').setAttribute('aria-expanded', 'false');
    if (tab === 'units') units();
    if (tab === 'activity') activity();
    if (tab === 'settings') settings();
    document.dispatchEvent(
      new CustomEvent('platform-section-changed', { detail: { tab } }),
    );
  }
  document.querySelectorAll('[data-platform-tab]').forEach((link) => {
    link.onclick = (event) => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)
        return;
      event.preventDefault();
      select(link.dataset.platformTab, true);
    };
  });
  el('platform-menu').onclick = () => {
    const open = document.body.classList.toggle('platform-navigation-open');
    el('platform-menu').setAttribute('aria-expanded', String(open));
  };
  document.addEventListener('keydown', (event) => {
    if (
      event.key === 'Escape' &&
      document.body.classList.contains('platform-navigation-open')
    ) {
      document.body.classList.remove('platform-navigation-open');
      el('platform-menu').setAttribute('aria-expanded', 'false');
      el('platform-menu').focus();
    }
  });
  window.addEventListener('popstate', () => {
    const tab = new URLSearchParams(location.search).get('tab');
    select(tab);
    if (active !== tab) history.replaceState(null, '', '/admin?tab=' + active);
  });
  select(new URLSearchParams(location.search).get('tab'));
})();
