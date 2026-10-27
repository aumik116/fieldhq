// Loadout layouts share the resource library's publishing and template workflow.
window.UnitLoadouts = (() => {
  const standard = [
    'Helmet',
    'Jacket',
    'ArmoredVest',
    'Pants',
    'Boots',
    'Back',
    'Vest',
    'HandWear',
    'Head',
    'Eyes',
    'Ears',
    'Face',
    'Neck',
    'Extra',
    'Extra 2',
    'Extra 3',
    'Extra 4',
    'Extra 5',
    'Extra 6',
    'Waist',
    'NVS_NVGSLOT',
    'Primary Weapon',
    'Secondary Weapon',
    'Sidearm',
  ];
  const esc = escHtml;
  const input = (label, name, value = '', max = 120) =>
    `<label class="unit-field">${label}<input name="${name}" value="${esc(value)}" maxlength="${max}"></label>`;
  function addEntry(root, entry = {}) {
    if (root.children.length >= 100) return;
    const row = document.createElement('div');
    row.className = 'loadout-item-row';
    row.innerHTML =
      input('Item', 'item_name', entry.name) +
      `<label class="unit-field">Quantity<input name="item_quantity" type="number" min="1" max="999" value="${Number(entry.quantity) || 1}" required></label>` +
      input('Notes', 'item_notes', entry.notes, 1000) +
      '<button type="button">Remove item</button>';
    row.querySelector('[name="item_name"]').required = true;
    row.querySelector('button').onclick = () => row.remove();
    root.append(row);
  }
  function addSlot(root, slot = {}) {
    if (root.children.length >= 40) return;
    const row = document.createElement('details');
    row.className = 'unit-block loadout-slot-editor';
    row.dataset.loadoutSlot = '';
    row.open = !slot.slot;
    row.innerHTML =
      '<summary></summary>' +
      input('Slot', 'slot_slot', slot.slot) +
      input('Main item', 'slot_standard', slot.standard, 2000) +
      ['inventory', 'attachments']
        .map(
          (key) =>
            `<section><h4>${key === 'inventory' ? 'Inventory contents' : 'Attachments'}</h4><div data-list="${key}"></div><button type="button" data-add="${key}">Add ${key === 'inventory' ? 'inventory item' : 'attachment'}</button></section>`,
        )
        .join('') +
      input(
        'Alternatives (optional)',
        'slot_alternatives',
        slot.alternatives,
        2000,
      ) +
      input('Slot notes', 'slot_notes', slot.notes, 2000) +
      '<button type="button" data-remove-slot>Remove slot</button>';
    const summary = () => {
      row.querySelector('summary').textContent =
        `${row.querySelector('[name="slot_slot"]').value || 'New slot'} · ${row.querySelector('[name="slot_standard"]').value || 'No item set'}`;
    };
    row.querySelector('[name="slot_slot"]').required = true;
    row.addEventListener(
      'invalid',
      () => {
        row.open = true;
      },
      true,
    );
    row.addEventListener('input', summary);
    for (const key of ['inventory', 'attachments']) {
      const list = row.querySelector(`[data-list="${key}"]`);
      (slot[key] || []).forEach((entry) => addEntry(list, entry));
      row.querySelector(`[data-add="${key}"]`).onclick = () => addEntry(list);
    }
    row.querySelector('[data-remove-slot]').onclick = () => row.remove();
    summary();
    root.append(row);
  }
  function collect(root) {
    return [...root.querySelectorAll('[data-loadout-slot]')].map((row) => {
      const slot = Object.fromEntries(
        ['slot', 'standard', 'alternatives', 'notes'].map((key) => [
          key,
          row.querySelector(`[name="slot_${key}"]`).value,
        ]),
      );
      for (const key of ['inventory', 'attachments'])
        slot[key] = [...row.querySelector(`[data-list="${key}"]`).children].map(
          (entry) => ({
            name: entry.querySelector('[name="item_name"]').value,
            quantity: Number(
              entry.querySelector('[name="item_quantity"]').value,
            ),
            notes: entry.querySelector('[name="item_notes"]').value,
          }),
        );
      return slot;
    });
  }
  function display(root, slots) {
    root.innerHTML = slots
      .map(
        (slot) =>
          `<details class="unit-block"><summary>${esc(slot.slot)} · ${esc(slot.standard || 'No item set')}</summary>${['inventory', 'attachments'].map((key) => (slot[key]?.length ? `<h4>${key === 'inventory' ? 'Inventory contents' : 'Attachments'}</h4><ul>${slot[key].map((entry) => `<li>${esc(entry.name)} × ${esc(entry.quantity)}${entry.notes ? ` — ${esc(entry.notes)}` : ''}</li>`).join('')}</ul>` : '')).join('')}${slot.alternatives ? `<p>Alternatives: ${esc(slot.alternatives)}</p>` : ''}${slot.notes ? `<p>${esc(slot.notes)}</p>` : ''}</details>`,
      )
      .join('');
  }
  return { standard, addSlot, collect, display };
})();
