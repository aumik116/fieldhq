// Unit-scoped communications cards; no print/export view.
(() => {
  const el = (id) => document.getElementById(id),
    esc = escHtml;
  const dialog = el('comms-dialog'),
    form = el('comms-form');
  let context,
    cards = [],
    canEdit = false,
    request = 0,
    baseline = '',
    saving = false;
  const signature = () => JSON.stringify([...new FormData(form)]);
  const read = async (url) => readJson(await fetch(url));
  const write = async (url, data) => readJson(await postJson(url, data));
  UnitUX.registerDraft({
    dirty: () => dialog.open && signature() !== baseline,
    busy: () => saving,
    discard: () => dialog.close(),
  });
  el('comms-close').onclick = () => UnitUX.close(dialog);
  dialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    UnitUX.close(dialog);
  });
  dialog.addEventListener('close', () => {
    if (!dialog.open) {
      form.reset();
      el('comms-body').replaceChildren();
    }
  });
  function secret(value) {
    if (!value) return '<span class="feature-note">—</span>';
    // Values are attached by closures, never interpolated into markup attributes.
    return '<button type="button" data-comm-secret aria-expanded="false">Show</button><span class="comms-secret" hidden></span>';
  }
  function render() {
    const root = el('comms-cards');
    root.replaceChildren();
    for (const card of cards) {
      const article = document.createElement('article');
      article.className = 'unit-block comms-card';
      article.innerHTML = `<header class="comms-heading"><div><h3>${esc(card.title)}</h3><p class="feature-note">${card.effective_on ? `Effective ${esc(card.effective_on)} · ` : ''}Updated ${esc(new Date(card.updated_at * 1000).toLocaleString())} · ${esc(card.updated_by)}</p></div>${canEdit ? '<div class="comms-actions"><button type="button" data-edit>Edit card</button><button type="button" data-delete>Delete</button></div>' : ''}</header>`;
      const groups = new Map();
      for (const row of card.circuits) {
        const name = row.group || 'Circuits';
        if (!groups.has(name)) groups.set(name, []);
        groups.get(name).push(row);
      }
      for (const [name, rows] of groups) {
        const section = document.createElement('section');
        section.className = 'comms-group';
        const crypto = rows.some((row) => row.crypto),
          password = rows.some((row) => row.password);
        section.innerHTML = `<h4>${esc(name)}</h4><div class="unit-table"><table><thead><tr><th scope="col">Frequency</th><th scope="col">Circuit name</th><th scope="col">Radio type</th>${crypto ? '<th scope="col">Crypto</th>' : ''}${password ? '<th scope="col">Password</th>' : ''}</tr></thead><tbody>${rows.map((row) => `<tr><td class="comms-frequency">${esc(row.frequency)}</td><td>${esc(row.name)}</td><td>${esc(row.radio)}</td>${crypto ? `<td>${secret(row.crypto)}</td>` : ''}${password ? `<td>${secret(row.password)}</td>` : ''}</tr>`).join('')}</tbody></table></div>`;
        section.querySelectorAll('tbody tr').forEach((tr, index) => {
          const keys = [
            ...(crypto ? ['crypto'] : []),
            ...(password ? ['password'] : []),
          ];
          keys.forEach((key, i) => {
            const cell = tr.children[3 + i],
              button = cell.querySelector('button'),
              text = cell.querySelector('span.comms-secret');
            if (!button) return;
            button.setAttribute(
              'aria-label',
              `Show ${key} for ${rows[index].name}`,
            );
            button.onclick = () => {
              const show = text.hidden;
              text.hidden = !show;
              text.textContent = show ? rows[index][key] : '';
              button.textContent = show ? 'Hide' : 'Show';
              button.setAttribute('aria-expanded', String(show));
              button.setAttribute(
                'aria-label',
                `${show ? 'Hide' : 'Show'} ${key} for ${rows[index].name}`,
              );
            };
          });
        });
        article.append(section);
      }
      if (card.notes) {
        const notes = document.createElement('p');
        notes.className = 'comms-notes';
        notes.textContent = card.notes;
        article.append(notes);
      }
      article
        .querySelector('[data-edit]')
        ?.addEventListener('click', () => edit(card));
      article
        .querySelector('[data-delete]')
        ?.addEventListener('click', async (event) => {
          if (!confirm(`Delete communications card “${card.title}”?`)) return;
          const unitId = context.unitId;
          event.target.disabled = true;
          try {
            await write(`/api/units/${unitId}/comms/${card.id}/delete`, {
              version: card.version,
            });
            if (context?.unitId === unitId) await load();
          } catch (error) {
            if (context?.unitId === unitId)
              el('comms-status').textContent = error.message;
          } finally {
            event.target.disabled = false;
          }
        });
      root.append(article);
    }
    if (!cards.length)
      root.innerHTML = '<p class="unit-empty">No communications cards yet.</p>';
  }
  async function load() {
    if (!context || el('unit-comms').hidden) return;
    const unitId = context.unitId,
      current = ++request;
    el('comms-status').textContent = 'Loading communications cards…';
    try {
      const data = await read(`/api/units/${unitId}/comms`);
      if (current !== request || context?.unitId !== unitId) return;
      cards = data.cards;
      canEdit = data.can_edit;
      el('comms-new').hidden = !canEdit;
      el('comms-status').textContent = 'Members can view · Staff can edit';
      render();
    } catch (error) {
      if (current === request) {
        UnitUX.error(el('comms-cards'), error, load);
        el('comms-status').textContent = '';
      }
    }
  }
  function field(label, name, value = '', required = false, type = 'text') {
    return `<label class="unit-field">${label}<input name="${name}" type="${type}" value="${esc(value)}" maxlength="${name === 'frequency' ? 40 : 120}" ${required ? 'required' : ''} autocomplete="off"></label>`;
  }
  function addRow(row = {}) {
    const root = el('comms-rows');
    if (root.children.length >= 200) return;
    const block = document.createElement('details');
    block.className = 'unit-block';
    block.dataset.circuit = '';
    block.open = !row.name;
    block.innerHTML =
      '<summary>New circuit</summary><div class="unit-form-grid">' +
      field('Circuit name', 'name', row.name, true) +
      field('Frequency / channel', 'frequency', row.frequency, true) +
      field('Radio type', 'radio', row.radio, true) +
      field('Group (optional)', 'group', row.group) +
      field('Crypto (optional)', 'crypto', row.crypto, false, 'password') +
      field(
        'Password (optional)',
        'password',
        row.password,
        false,
        'password',
      ) +
      '</div><div class="comms-actions"><button type="button" data-up>Move up</button><button type="button" data-down>Move down</button><button type="button" data-remove>Remove circuit</button></div>';
    block.oninput = () => {
      block.querySelector('summary').textContent =
        `${block.querySelector('[name="frequency"]').value || 'Frequency'} · ${block.querySelector('[name="name"]').value || 'New circuit'}`;
    };
    block.oninput();
    block.addEventListener(
      'invalid',
      () => {
        block.open = true;
      },
      true,
    );
    block.querySelector('[data-remove]').onclick = () => {
      if (!confirm('Remove this circuit from the card?')) return;
      block.remove();
    };
    block.querySelector('[data-up]').onclick = () => {
      if (block.previousElementSibling)
        root.insertBefore(block, block.previousElementSibling);
    };
    block.querySelector('[data-down]').onclick = () => {
      if (block.nextElementSibling)
        root.insertBefore(block.nextElementSibling, block);
    };
    root.append(block);
  }
  function edit(card = null) {
    if (!canEdit || !UnitUX.canLeave()) return;
    const unitId = context.unitId;
    UnitUX.prepare(dialog, {
      title: card ? 'Edit commo card' : 'New commo card',
      body: el('comms-body'),
      content: `<div class="unit-form-grid">${field('Card title', 'title', card?.title, true)}<label class="unit-field">Effective date (optional)<input type="date" name="effective_on" value="${esc(card?.effective_on || '')}"></label></div><p class="feature-note">Group circuits by company, command or radio net using the optional Group field. Crypto and password fields are optional and visible to members when revealed.</p><div id="comms-rows"></div><button type="button" id="comms-add-row">Add circuit</button><label class="unit-field">Radio notes<textarea name="notes" maxlength="4000">${esc(card?.notes || '')}</textarea></label>`,
    });
    (card?.circuits || [{}]).forEach(addRow);
    el('comms-add-row').onclick = () => addRow();
    baseline = signature();
    form.onsubmit = async (event) => {
      event.preventDefault();
      if (saving) return;
      saving = true;
      try {
        await UnitUX.save(
          dialog,
          async () => {
            const values = new FormData(form);
            const circuits = [...el('comms-rows').children].map((block) =>
              Object.fromEntries(
                [
                  'name',
                  'frequency',
                  'radio',
                  'group',
                  'crypto',
                  'password',
                ].map((key) => [
                  key,
                  block.querySelector(`[name="${key}"]`).value,
                ]),
              ),
            );
            await write(`/api/units/${unitId}/comms`, {
              title: values.get('title'),
              effective_on: values.get('effective_on'),
              notes: values.get('notes'),
              circuits,
              ...(card ? { id: card.id, version: card.version } : {}),
            });
          },
          async () => {
            dialog.close();
            if (context?.unitId === unitId) await load();
          },
        );
      } finally {
        saving = false;
      }
    };
  }
  el('comms-new').onclick = () => edit();
  el('comms-refresh').onclick = load;
  document.addEventListener('unit-loaded', (event) => {
    if (context?.unitId !== event.detail.unitId) {
      request++;
      cards = [];
      el('comms-cards').replaceChildren();
      if (dialog.open) dialog.close();
    }
    context = event.detail;
    load();
  });
  document.addEventListener('unit-section-changed', () => {
    if (!el('unit-comms').hidden) load();
    else render();
  });
})();
