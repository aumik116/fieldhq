// Staff personnel views extend the existing unit dialog, roster and audit workflows.
window.UnitPersonnel = (() => {
  let context = null,
    actions = null,
    generation = 0,
    saving = false;
  const el = (id) => document.getElementById(id),
    esc = escHtml;
  const read = async (url) => readJson(await fetch(url));
  const base = () => `/api/units/${context.unitId}`;
  const fields = (label, name, value = '', type = 'text') =>
    `<label class="unit-field">${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}"></label>`;
  const memberName = (id) =>
    context.detail.roster.find((member) => member.id === id)?.game_name ||
    'Member';
  const path = (id) => {
    const nodes = new Map(
      context.detail.structure.map((node) => [node.id, node]),
    );
    const names = [];
    let node = nodes.get(id);
    while (node) {
      names.unshift(node.name);
      node = nodes.get(node.parent_id);
    }
    return names.join(' / ');
  };
  async function data() {
    const id = context.unitId,
      result = await read(`${base()}/personnel`);
    return context.unitId === id ? result : null;
  }
  function open(title, body, save) {
    if (!UnitUX.canLeave()) return false;
    actions.open(title, body, save);
    return true;
  }
  function readonly(title, body) {
    if (!open(title, body, async () => false)) return false;
    actions.form.querySelector('[type="submit"]').hidden = true;
    return true;
  }
  async function ensure(result) {
    return result && (await actions.ensure(result.revision));
  }
  function fail(error) {
    el('units-feedback').textContent = error.message;
  }
  function memberButton(id, name) {
    return `<button type="button" class="member-record-link" data-personnel-member="${id}">${esc(name)}</button>`;
  }
  function bind(root) {
    root
      .querySelectorAll('[data-personnel-member]')
      .forEach(
        (button) =>
          (button.onclick = () =>
            actions.member(Number(button.dataset.personnelMember))),
      );
    root.querySelectorAll('[data-personnel-jump]').forEach(
      (button) =>
        (button.onclick = () => {
          if (!UnitUX.canLeave()) return;
          actions.form.closest('dialog').close();
          actions.jump(Number(button.dataset.personnelJump));
        }),
    );
    root
      .querySelectorAll('[data-personnel-renew]')
      .forEach(
        (button) =>
          (button.onclick = () =>
            actions.qualification(
              Number(button.dataset.member),
              button.dataset.personnelRenew,
            )),
      );
  }
  async function vacancies() {
    try {
      const result = await data();
      if (!(await ensure(result))) return;
      if (
        !readonly(
          'Open billets',
          `<p>${result.vacancies.length} permanently unfilled billets. Temporary cover does not fill a primary slot.</p><div class="unit-table"><table><thead><tr><th>Billet / formation</th><th>Temporary cover</th><th></th></tr></thead><tbody>${result.vacancies.map((slot) => `<tr><td>${esc(slot.path)}</td><td>${esc(slot.cover.join(', ') || '—')}</td><td><button type="button" data-vacancy-assign="${slot.id}">Assign</button><button type="button" data-personnel-jump="${slot.formation_id}">Go to formation</button></td></tr>`).join('') || '<tr><td colspan="3">No open billets.</td></tr>'}</tbody></table></div>`,
        )
      )
        return;
      const root = el('unit-dialog-body');
      root
        .querySelectorAll('[data-vacancy-assign]')
        .forEach(
          (button) =>
            (button.onclick = () =>
              actions.assign(Number(button.dataset.vacancyAssign))),
        );
      bind(root);
    } catch (error) {
      fail(error);
    }
  }
  async function temporary(memberId = null) {
    try {
      const result = await data();
      if (!(await ensure(result))) return;
      const members = context.detail.roster.filter(
          (member) => !member.archived,
        ),
        slots = context.detail.structure.filter(
          (node) => node.kind === 'billet',
        );
      if (!slots.length) {
        readonly(
          'Temporary cover',
          '<p>Create named billets in Structure before assigning temporary cover.</p>',
        );
        return;
      }
      open(
        'Assign temporary cover',
        `<p>Primary placement stays unchanged. Dates are inclusive. One member or billet cannot have overlapping temporary covers.</p><label class="unit-field">Member<select name="member_id">${members.map((member) => `<option value="${member.id}" ${member.id === memberId ? 'selected' : ''}>${esc(member.game_name)}</option>`).join('')}</select></label><label class="unit-field">Covering billet<select name="billet_id">${slots.map((slot) => `<option value="${slot.id}">${esc(path(slot.id))}</option>`).join('')}</select></label>${fields('Starts', 'starts_on', result.today, 'date')}${fields('Ends (optional)', 'ends_on', '', 'date')}<label class="unit-field">Coverage note<textarea name="notes" maxlength="1000"></textarea></label>`,
        async () => {
          const values = Object.fromEntries(new FormData(actions.form));
          await actions.write(`${base()}/temporary-assignments`, {
            ...values,
            member_id: Number(values.member_id),
            billet_id: Number(values.billet_id),
            revision: context.detail.unit.revision,
          });
        },
      );
    } catch (error) {
      fail(error);
    }
  }
  async function coverage() {
    try {
      const result = await data();
      if (!(await ensure(result))) return;
      if (
        !readonly(
          'Temporary assignments',
          `<button type="button" id="coverage-add">Assign temporary cover</button><div class="unit-table"><table><thead><tr><th>Member</th><th>Covering</th><th>Dates</th><th></th></tr></thead><tbody>${result.temporary.map((item) => `<tr><td>${memberButton(item.member_id, item.game_name)}</td><td>${esc(item.path)}<small>${esc(item.notes)}</small></td><td>${esc(item.starts_on)} → ${esc(item.ends_on || 'Until cancelled')}<small>${item.active ? 'Active' : 'Upcoming'}</small></td><td><button type="button" data-cover-cancel="${item.id}">Cancel cover</button></td></tr>`).join('') || '<tr><td colspan="4">No current or upcoming cover.</td></tr>'}</tbody></table></div>`,
        )
      )
        return;
      el('coverage-add').onclick = () => temporary();
      const root = el('unit-dialog-body');
      bind(root);
      root
        .querySelectorAll('[data-cover-cancel]')
        .forEach(
          (button) =>
            (button.onclick = () =>
              open(
                'Cancel temporary cover',
                '<p>The member’s primary placement and historical event attendance stay unchanged.</p>',
                async () =>
                  actions.write(
                    `${base()}/temporary-assignments/${Number(button.dataset.coverCancel)}/cancel`,
                    { revision: context.detail.unit.revision },
                  ),
              )),
        );
    } catch (error) {
      fail(error);
    }
  }
  function followup(memberId = null, existing = null) {
    const members = context.detail.roster;
    if (
      !open(
        existing ? 'Edit follow-up' : 'Add staff follow-up',
        `${fields('Title', 'title', existing?.title || '')}${fields('Due date (optional)', 'due_on', existing?.due_on || '', 'date')}<label class="unit-field">Member (optional)<select name="member_id"><option value="">Unit-wide follow-up</option>${members.map((member) => `<option value="${member.id}" ${member.id === (existing?.member_id || memberId) ? 'selected' : ''}>${esc(member.game_name)}${member.archived ? ' (former)' : ''}</option>`).join('')}</select></label><label class="unit-field">Notes<textarea name="notes" maxlength="2000">${esc(existing?.notes || '')}</textarea></label><p class="feature-note">Staff-only action item. Completion does not change a rank, qualification or attendance decision.</p>`,
        async () => {
          const values = Object.fromEntries(new FormData(actions.form));
          await actions.write(`${base()}/followups`, {
            ...values,
            member_id: Number(values.member_id) || null,
            ...(existing
              ? { id: existing.id, completed: !!existing.completed }
              : {}),
            revision: context.detail.unit.revision,
          });
        },
      )
    )
      return;
    if (actions.form.elements.title) {
      actions.form.elements.title.required = true;
      actions.form.elements.title.maxLength = 120;
    }
  }
  async function meeting() {
    if (!context?.detail.can_edit) return;
    const current = context.unitId,
      request = ++generation;
    el('meeting-status').textContent = 'Loading agenda…';
    try {
      const result = await data();
      if (!result || current !== context.unitId || request !== generation)
        return;
      const openFollowups = result.followups.filter((item) => !item.completed);
      el('meeting-content').innerHTML =
        `<div class="unit-summary"><span>Promotion reviews <strong>${result.eligible.length}</strong></span><span>Open billets <strong>${result.vacancies.length}</strong></span><span>Qualification renewals <strong>${result.renewals.length}</strong></span><span>Open follow-ups <strong>${openFollowups.length}</strong></span></div><div class="unit-dashboard-grid"><section class="unit-block"><h3>Promotion reviews</h3>${result.eligible.map((member) => `<p>${memberButton(member.id, member.name)} → ${esc(member.next_rank)} <button type="button" data-agenda-promote="${member.id}">Review</button></p>`).join('') || '<p>No eligible promotions.</p>'}</section><section class="unit-block"><h3>Open billets</h3>${result.vacancies.map((slot) => `<p><button type="button" class="member-record-link" data-personnel-jump="${slot.formation_id}">${esc(slot.path)}</button>${slot.cover.length ? `<small>Covered by ${esc(slot.cover.join(', '))}</small>` : ''}</p>`).join('') || '<p>No vacancies.</p>'}</section><section class="unit-block"><h3>Expired / expiring within 30 days</h3>${result.renewals.map((item) => `<p>${memberButton(item.member_id, item.game_name)} · ${esc(item.certificate)}<small class="${item.expires_on < result.today ? 'unit-warn' : ''}">${item.expires_on < result.today ? 'Expired' : 'Expires'} ${esc(item.expires_on)}</small><button type="button" data-personnel-renew="${esc(item.certificate)}" data-member="${item.member_id}">Update award / renew</button></p>`).join('') || '<p>No renewals due.</p>'}</section></div><section class="unit-block"><div class="formation-heading"><h3>Staff follow-ups</h3><button type="button" id="meeting-add-followup">Add follow-up</button></div>${openFollowups.map((item) => `<article class="meeting-followup"><strong>${esc(item.title)}</strong>${item.game_name ? ` · ${memberButton(item.member_id, item.game_name)}` : ''}<small>${item.due_on ? 'Due ' + esc(item.due_on) : 'No due date'} · ${esc(item.author)}</small><p>${esc(item.notes)}</p><button type="button" data-followup-done="${item.id}">Mark complete</button><button type="button" data-followup-edit="${item.id}">Edit</button></article>`).join('') || '<p>No open follow-ups.</p>'}<details><summary>Recently completed follow-ups</summary>${
          result.followups
            .filter((item) => item.completed)
            .map(
              (item) =>
                `<p>${esc(item.title)} <button type="button" data-followup-reopen="${item.id}">Reopen</button></p>`,
            )
            .join('') || '<p>None recorded.</p>'
        }</details></section>`;
      const root = el('meeting-content');
      bind(root);
      el('meeting-add-followup').onclick = () => followup();
      root.querySelectorAll('[data-agenda-promote]').forEach(
        (button) =>
          (button.onclick = () =>
            document.dispatchEvent(
              new CustomEvent('unit-review-promotion', {
                detail: Number(button.dataset.agendaPromote),
              }),
            )),
      );
      root.querySelectorAll('[data-followup-edit]').forEach(
        (button) =>
          (button.onclick = () =>
            followup(
              null,
              result.followups.find(
                (item) => item.id === Number(button.dataset.followupEdit),
              ),
            )),
      );
      root
        .querySelectorAll('[data-followup-done],[data-followup-reopen]')
        .forEach(
          (button) =>
            (button.onclick = async () => {
              if (saving) return;
              saving = true;
              button.disabled = true;
              try {
                await actions.write(`${base()}/followups`, {
                  id: Number(
                    button.dataset.followupDone ||
                      button.dataset.followupReopen,
                  ),
                  completed: !!button.dataset.followupDone,
                  revision: result.revision,
                });
                saving = false;
                await actions.reload();
              } catch (error) {
                el('meeting-status').textContent = error.message;
              } finally {
                saving = false;
                button.disabled = false;
              }
            }),
        );
      el('meeting-status').textContent =
        'Staff review only — these lists do not apply changes automatically.';
    } catch (error) {
      if (current === context?.unitId)
        el('meeting-status').textContent = error.message;
    }
  }
  async function compare(memberId) {
    try {
      const current = context.unitId,
        result = await read(`${base()}/roster/${memberId}/compare`);
      if (current !== context.unitId) return;
      if (
        !readonly(
          'Compare versions — ' + memberName(memberId),
          '<p>Compare recorded roster fields, qualifications and placements. Older history may omit fields; “Not recorded” is not proof that a value changed. Dated staff notes remain separate.</p><div class="unit-toolbar"><label class="unit-field">From<select id="compare-from"></select></label><label class="unit-field">To<select id="compare-to"></select></label><label><input type="checkbox" id="compare-show-all"> Include unchanged fields</label></div><div id="compare-fields"></div><p id="compare-status" role="status"></p>',
        )
      )
        return;
      const option = (item) =>
        `<option value="${item.id}">${esc(new Date(item.when * 1000).toLocaleString())} · ${esc(item.kind)} · ${esc(item.actor)}</option>`;
      for (const key of ['from', 'to'])
        el('compare-' + key).innerHTML =
          '<option value="current">Current record</option>' +
          result.versions.map(option).join('');
      el('compare-from').value = result.from_version;
      el('compare-to').value = result.to_version;
      let payload = result,
        request = 0;
      const value = (data, known) =>
        !known
          ? 'Not recorded'
          : data === null
            ? 'None'
            : typeof data === 'object'
              ? JSON.stringify(data, null, 2)
              : String(data);
      function draw() {
        const fields = payload.fields.filter(
          (item) => item.changed || el('compare-show-all').checked,
        );
        el('compare-fields').innerHTML =
          `<div class="unit-table"><table><thead><tr><th>Field</th><th>From version</th><th>To version</th></tr></thead><tbody>${fields.map((item) => `<tr class="${item.changed ? 'record-field-changed' : ''}"><th>${esc(item.field.replaceAll('_', ' '))}${item.changed ? ' · Changed' : ''}</th><td><pre>${esc(value(item.before, item.before_known))}</pre></td><td><pre>${esc(value(item.after, item.after_known))}</pre></td></tr>`).join('') || '<tr><td colspan="3">No differences in recorded fields.</td></tr>'}</tbody></table></div>`;
      }
      async function load() {
        const requestId = ++request,
          region = el('compare-fields');
        try {
          const query = new URLSearchParams({
            from: el('compare-from').value,
            to: el('compare-to').value,
          });
          const next = await read(
            `/api/units/${current}/roster/${memberId}/compare?${query}`,
          );
          if (
            current !== context.unitId ||
            requestId !== request ||
            !region.isConnected
          )
            return;
          payload = next;
          draw();
        } catch (error) {
          if (region.isConnected)
            el('compare-status').textContent = error.message;
        }
      }
      el('compare-from').onchange = load;
      el('compare-to').onchange = load;
      el('compare-show-all').onchange = draw;
      draw();
    } catch (error) {
      fail(error);
    }
  }
  function search() {
    const root = el('roster-search-results');
    if (!context) return;
    const query = el('roster-search').value.trim().toLowerCase();
    root.hidden = !query;
    if (!query) {
      root.replaceChildren();
      return;
    }
    const status = el('roster-status').value,
      members = context.detail.roster.filter(
        (member) =>
          (status === 'archived'
            ? member.archived
            : !member.archived && (!status || member.status === status)) &&
          [
            member.game_name,
            member.rank,
            member.rank_display,
            member.effective_callsign,
            member.discord,
            member.identity,
            member.assignment_path,
            member.certificates,
          ]
            .join(' ')
            .toLowerCase()
            .includes(query),
      );
    root.innerHTML = `<p>${members.length} matching members across this unit${members.length > 50 ? ' · Showing first 50' : ''}</p>${
      members
        .slice(0, 50)
        .map((member) => {
          const formation =
            member.placement_id ||
            context.detail.structure.find(
              (node) => node.id === member.billet_id,
            )?.parent_id;
          return `<p>${context.detail.can_edit ? memberButton(member.id, member.game_name) : esc(member.game_name)}<small>${esc(member.assignment_path || 'Unassigned')}</small>${formation ? `<button type="button" data-personnel-jump="${formation}">Go to formation</button>` : ''}</p>`;
        })
        .join('') || '<p>No matches.</p>'
    }`;
    bind(root);
  }
  function connect(callbacks) {
    actions = callbacks;
    el('roster-vacancies').onclick = vacancies;
    el('roster-temporary').onclick = coverage;
    el('meeting-refresh').onclick = meeting;
    el('meeting-add').onclick = () => followup();
    el('roster-search').addEventListener('input', search);
    el('roster-status').addEventListener('change', search);
    document.addEventListener('unit-compare-member', (event) =>
      compare(event.detail),
    );
    document.addEventListener('unit-temporary-member', (event) =>
      temporary(event.detail),
    );
    document.addEventListener('unit-followup-member', (event) =>
      followup(event.detail),
    );
    UnitUX.registerDraft({ dirty: () => false, busy: () => saving });
  }
  document.addEventListener('unit-loaded', (event) => {
    context = event.detail;
    generation++;
    el('roster-vacancies').hidden = !context.detail.can_edit;
    el('roster-temporary').hidden = !context.detail.can_edit;
    search();
    if (!el('unit-meeting').hidden) meeting();
  });
  document.addEventListener('unit-section-changed', (event) => {
    if (event.detail.tab === 'meeting' && context?.unitId === actions?.unit())
      meeting();
  });
  return { connect };
})();
