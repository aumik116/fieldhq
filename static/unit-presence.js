// Advisory presence: saved-data conflicts are enforced separately by the API.
window.UnitPresence = (() => {
  const tracked = new WeakSet();
  const client = [...crypto.getRandomValues(new Uint8Array(16))]
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('');
  let current = null,
    generation = 0;
  async function ping(active = true) {
    const state = current,
      serial = generation;
    if (!state) return;
    try {
      const response = await postJson(`/api/units/${state.unit}/editing`, {
        client,
        resource: state.resource,
        active,
      });
      const data = await readJson(response);
      if (current !== state || serial !== generation) return;
      state.region.textContent = data.editors.length
        ? `${data.editors.join(', ')} ${data.editors.length === 1 ? 'is' : 'are'} also editing this item. Changes are checked when you save.`
        : 'No other editors currently working on this item.';
    } catch (error) {
      if (current === state)
        state.region.textContent =
          'Editing status unavailable. Changes will still be checked when you save.';
    }
  }
  function stop() {
    if (!current) return;
    ping(false);
    clearInterval(current.timer);
    current.region.remove();
    current = null;
    generation++;
  }
  function start(unit, resource, dialog) {
    stop();
    const region = document.createElement('p');
    region.className = 'editing-presence feature-note';
    region.setAttribute('role', 'status');
    region.textContent = 'Checking other editors…';
    const body = dialog.querySelector(
      '#unit-dialog-body, #roster-tools-body, #event-dialog-body',
    );
    if (body) body.before(region);
    else (dialog.querySelector('h2,h3') || dialog).after(region);
    current = { unit, resource, region, dialog };
    generation++;
    current.timer = setInterval(() => {
      if (
        (dialog instanceof HTMLDialogElement && !dialog.open) ||
        dialog.hidden
      )
        stop();
      else if (!document.hidden) ping();
    }, 15000);
    if (!tracked.has(dialog)) {
      tracked.add(dialog);
      dialog.addEventListener('close', () => {
        if (!dialog.open && current?.dialog === dialog) stop();
      });
    }
    ping();
  }
  document.addEventListener('unit-editor-reset', stop);
  document.addEventListener('unit-loaded', (event) => {
    if (current && current.unit !== event.detail.unitId) stop();
  });
  document.addEventListener('unit-section-changed', () => {
    if (current?.dialog.hidden) stop();
  });
  function show(editors) {
    const root = document.getElementById('unit-roster');
    if (!root) return;
    root
      .querySelectorAll('.member-editing-indicator')
      .forEach((node) => node.remove());
    for (const button of root.querySelectorAll(
      '.member-record-link[data-record],[data-board-action="record"]',
    )) {
      const id = button.dataset.record || button.dataset.member;
      const names = [
        ...new Set(
          editors
            .filter((item) =>
              new RegExp(`^(member|note):${id}(:|$)`).test(item.resource),
            )
            .map((item) => item.name),
        ),
      ];
      if (names.length) {
        const badge = document.createElement('small');
        badge.className = 'member-editing-indicator';
        badge.textContent = 'Editing: ' + names.join(', ');
        button.after(badge);
      }
    }
  }
  return { start, stop, show };
})();
