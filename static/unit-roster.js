// Roster collaboration and a compact feed. Saved changes sync; drafts remain local.
window.UnitRoster = (() => {
  let context = null,
    callbacks = null,
    timer = null,
    inFlight = false,
    selection = new Set(),
    feedCursor = null,
    feedGeneration = 0,
    accessLost = false,
    unavailable = false;
  const el = (id) => document.getElementById(id),
    esc = escHtml;
  function selectedCount() {
    const count = el('roster-selected-count');
    count.textContent = `${selection.size} selected`;
    el('roster-place-selected').disabled = !selection.size;
    document
      .querySelectorAll('[data-roster-select]')
      .forEach(
        (input) =>
          (input.checked = selection.has(Number(input.dataset.rosterSelect))),
      );
  }
  function rendered(view) {
    el('roster-selection-bar').hidden =
      view !== 'unassigned' || !context?.detail.can_edit;
    selectedCount();
  }
  const labels = {
    created: 'Member added',
    rank: 'Rank / promotion changed',
    billet: 'Assignment changed',
    qualification_granted: 'Qualification awarded',
    qualification_revoked: 'Qualification removed',
    qualification_updated: 'Qualification details changed',
    status: 'Status / LOA changed',
    callsign: 'Callsign changed',
    note: 'Staff note added',
    unit_member_note_delete: 'Staff note deleted',
    unit_member_note_edit: 'Staff note edited',
    profile: 'Profile fields changed',
    temporary: 'Temporary cover changed',
    unit_followup_save: 'Follow-up changed',
    unit_temporary_save: 'Temporary cover assigned',
    unit_temporary_cancel: 'Temporary cover cancelled',
    unit_roster_delete: 'Member deleted',
    unit_member_login_create: 'Member login created',
    unit_member_login_manage: 'Member access changed',
    unit_staff_save: 'Unit role changed',
    unit_formation_template_delete: 'Template deleted',
    unit_structure_save: 'Formation changed',
    unit_structure_delete: 'Formation removed',
    unit_catalog_save: 'Rank / qualification rules changed',
    unit_structure_copy: 'Layout copied',
    unit_structure_billets: 'Billets added',
    unit_structure_order: 'Structure reordered',
    unit_billet_types_save: 'Billet types changed',
    unit_qualification_delete: 'Qualification deleted',
    unit_formation_template_save: 'Template saved',
    unit_formation_template_apply: 'Template applied',
  };
  async function feed(append = false) {
    if (!context?.detail.can_edit) return;
    const current = context.unitId,
      generation = ++feedGeneration,
      button = el('roster-feed-more');
    button.disabled = true;
    el('roster-feed-status').textContent = '';
    try {
      const query = new URLSearchParams(append && feedCursor ? feedCursor : {});
      const data = await readJson(
        await fetch(`/api/units/${current}/roster/feed?${query}`),
      );
      if (context?.unitId !== current || generation !== feedGeneration) return;
      const root = el('roster-feed-entries');
      if (!append) root.replaceChildren();
      for (const entry of data.entries) {
        const row = document.createElement('article');
        row.className = 'roster-feed-entry';
        row.innerHTML = `<strong>${esc(labels[entry.kind] || entry.kind)}</strong> · ${entry.member_id ? `<button type="button" class="member-record-link" data-feed-member="${entry.member_id}">${esc(entry.name)}</button>` : esc(entry.name)}<small>${esc(entry.actor)} · ${esc(new Date(entry.when * 1000).toLocaleString())}</small>${entry.reason ? `<p>${esc(entry.reason)}</p>` : ''}${entry.before || entry.after ? `<details><summary>Before / after</summary><pre>${esc(JSON.stringify({ before: entry.before, after: entry.after }, null, 2))}</pre></details>` : ''}`;
        row
          .querySelector('[data-feed-member]')
          ?.addEventListener('click', () =>
            callbacks.openMember(entry.member_id),
          );
        root.append(row);
      }
      if (!root.children.length)
        root.textContent = 'No roster changes recorded yet.';
      feedCursor = data.next_cursor;
      button.hidden = !feedCursor;
    } catch (error) {
      if (context?.unitId === current)
        el('roster-feed-status').textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }
  function status(message, refresh = false) {
    el('unit-live-status').hidden = !message;
    el('unit-live-message').textContent = message;
    el('unit-live-refresh').hidden = !refresh;
  }
  async function poll() {
    if (!context || !callbacks || inFlight || accessLost) {
      schedule();
      return;
    }
    if (document.hidden || callbacks.current() !== context.unitId) {
      schedule();
      return;
    }
    const current = context.unitId;
    inFlight = true;
    const controller = new AbortController(),
      timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(`/api/units/${current}/sync`, {
        cache: 'no-store',
        signal: controller.signal,
      });
      if (current !== context?.unitId) return;
      if ([401, 403, 404].includes(response.status)) {
        accessLost = true;
        status('Unit access changed. Reload the page to continue.');
        return;
      }
      const data = await readJson(response);
      if (unavailable) {
        unavailable = false;
        status('');
      }
      if (current !== context?.unitId) return;
      if (data.token !== context.detail.sync_token) {
        if (UnitUX.hasDraft() || UnitUX.isBusy() || callbacks.busy()) {
          const member = callbacks.recordId();
          const same = member && (data.member_id === member || !data.member_id);
          status(
            `${data.staff && data.actor ? data.actor + ' saved changes.' : 'Saved changes are available.'} ${same ? 'The open record may have changed. ' : ''}Your unsaved work is kept; saving will recheck for conflicts.`,
            true,
          );
        } else {
          const refreshed = await callbacks.refresh();
          if (refreshed && context?.unitId === current)
            status(
              data.staff && data.actor
                ? `Updated from ${data.actor}’s saved changes.`
                : 'Roster updated.',
            );
        }
      }
    } catch (error) {
      unavailable = true;
      if (context?.unitId === current)
        status(
          'Live updates are temporarily unavailable; retrying. Your edits are kept.',
        );
    } finally {
      clearTimeout(timeout);
      inFlight = false;
      schedule();
    }
  }
  function schedule() {
    clearTimeout(timer);
    if (!accessLost) timer = setTimeout(poll, 3000);
  }
  function connect(actions) {
    callbacks = actions;
    el('roster-place-selected').onclick = () => callbacks.place([...selection]);
    el('roster-clear-selection').onclick = () => {
      selection.clear();
      selectedCount();
    };
    el('roster-select-shown').onclick = () => {
      document
        .querySelectorAll('[data-roster-select]')
        .forEach((input) => selection.add(Number(input.dataset.rosterSelect)));
      selectedCount();
    };
    el('roster-member-list').addEventListener('change', (event) => {
      const key = Number(event.target.dataset.rosterSelect);
      if (!key) return;
      if (event.target.checked) selection.add(key);
      else selection.delete(key);
      selectedCount();
    });
    el('roster-change-feed').ontoggle = () => {
      if (el('roster-change-feed').open) feed();
    };
    el('roster-feed-more').onclick = () => feed(true);
    el('roster-feed-refresh').onclick = () => feed();
    el('unit-live-refresh').onclick = async () => {
      if (await callbacks.refresh()) status('Roster refreshed.');
    };
    for (const name of ['callsigns', 'qualifications', 'status'])
      el('roster-show-' + name).onchange = () => {
        if (!context) return;
        const config = UnitStructure.config(context.detail);
        config.display[name] = el('roster-show-' + name).checked;
        UnitStructure.saveConfig(context.detail);
        callbacks.render();
      };
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        clearTimeout(timer);
        poll();
      }
    });
  }
  document.addEventListener('unit-loaded', (event) => {
    const next = event.detail,
      changed = context?.unitId !== next.unitId;
    if (changed) {
      accessLost = false;
      selection.clear();
      status('');
      feedGeneration++;
      el('roster-feed-entries').replaceChildren();
    }
    if (context?.detail.sync_token !== next.detail.sync_token) status('');
    accessLost = false;
    context = next;
    selection = new Set(
      [...selection].filter((id) =>
        next.detail.roster.some(
          (member) =>
            member.id === id &&
            !member.archived &&
            !member.billet_id &&
            !member.placement_id,
        ),
      ),
    );
    const config = UnitStructure.config(next.detail);
    for (const name of ['callsigns', 'qualifications', 'status'])
      el('roster-show-' + name).checked = config.display[name];
    rendered(callbacks?.view());
    el('roster-change-feed').hidden = !next.detail.can_edit;
    if (el('roster-change-feed').open && next.detail.can_edit) feed();
    schedule();
  });
  return { connect, rendered, isSelected: (id) => selection.has(id) };
})();
