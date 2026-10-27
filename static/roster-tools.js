// Qualifications, promotion review and previewed bulk edits share the roster revision.
(() => {
  const el = (id) => document.getElementById(id),
    esc = escHtml;
  const dialog = el('roster-tools-dialog'),
    form = el('roster-tools-form');
  let context,
    metadata,
    save,
    baseline = '',
    saving = false,
    generation = 0;
  const read = async (url) => readJson(await fetch(url));
  const write = async (url, data) => readJson(await postJson(url, data));
  const base = () => `/api/units/${context.unitId}`;
  const feedback = (message) => {
    el('units-feedback').textContent = message;
  };
  const current = () => context.detail.roster.filter((m) => !m.archived);
  const awards = (member) =>
    (metadata?.awards || []).filter((a) => a.member_id === member.id);
  const held = (member) => member.certificates.split(';').filter(Boolean);
  const sign = () => JSON.stringify([...new FormData(form)]);
  UnitUX.registerDraft({
    dirty: () => dialog.open && sign() !== baseline,
    busy: () => dialog.open && saving,
    discard: () => dialog.close(),
  });
  const close = () => UnitUX.close(dialog);
  el('roster-tools-close').onclick = close;
  dialog.addEventListener('cancel', (e) => {
    e.preventDefault();
    close();
  });
  function open(title, html, handler, button = 'Save changes') {
    save = handler;
    UnitUX.prepare(dialog, {
      title,
      body: el('roster-tools-body'),
      content: html,
      save: !!handler,
      button,
    });
    baseline = sign();
  }
  form.onsubmit = async (e) => {
    e.preventDefault();
    if (saving || !save) return;
    saving = true;
    try {
      await UnitUX.save(dialog, save, (result) => {
        if (result !== false) {
          dialog.close();
          document.dispatchEvent(new Event('unit-access-changed'));
        } else baseline = sign();
      });
    } finally {
      saving = false;
    }
  };
  function path(id) {
    const nodes = new Map(context.detail.structure.map((n) => [n.id, n]));
    const result = [];
    let node = nodes.get(id);
    while (node) {
      result.push(node.name);
      node = nodes.get(node.parent_id);
    }
    return result.reverse().join(' / ');
  }
  function sectionMembers(id, members) {
    if (id === 'all') return members;
    if (id === 'unassigned')
      return members.filter((m) => !m.billet_id && !m.placement_id);
    const descendants = new Set([Number(id)]);
    for (let i = 0; i < 7; i++)
      context.detail.structure.forEach((n) => {
        if (descendants.has(n.parent_id)) descendants.add(n.id);
      });
    return members.filter(
      (m) => descendants.has(m.billet_id) || descendants.has(m.placement_id),
    );
  }
  function memberButton(member) {
    return `<button type="button" class="member-record-link" data-tool-record="${member.id}">${esc(member.game_name)}</button><small>${esc([member.rank_track, member.rank_display || member.rank].filter(Boolean).join(' · '))}</small>`;
  }
  function bindMembers(root) {
    root.querySelectorAll('[data-tool-record]').forEach(
      (b) =>
        (b.onclick = () => {
          document.dispatchEvent(
            new CustomEvent('unit-open-member', {
              detail: Number(b.dataset.toolRecord),
            }),
          );
        }),
    );
  }
  function renderMatrix() {
    if (!context || !metadata) return;
    renderRenewals();
    const certificates = context.detail.unit.catalog.certificates || [];
    const status = el('matrix-status').value,
      search = el('matrix-search').value.trim().toLowerCase();
    let members = context.detail.roster.filter(
      (m) =>
        (status === 'archived'
          ? m.archived
          : !m.archived && (!status || m.status === status)) &&
        [
          m.game_name,
          m.rank,
          m.rank_display,
          m.rank_track,
          m.discord,
          m.billet_path,
        ]
          .join(' ')
          .toLowerCase()
          .includes(search),
    );
    members = sectionMembers(el('matrix-section').value, members);
    const scope = members;
    const selected = el('matrix-certificate').value,
      mode = el('matrix-held').value;
    if (mode !== 'all' && !selected) {
      el('qualification-matrix').innerHTML =
        '<p class="unit-empty">Choose a qualification to filter who holds or is missing it.</p>';
      el('matrix-coverage').replaceChildren();
      return;
    }
    if (mode !== 'all')
      members = members.filter(
        (m) => held(m).includes(selected) === (mode === 'held'),
      );
    const rankOrder = new Map();
    let index = 0;
    (context.detail.unit.catalog.rank_structures || []).forEach((s) =>
      s.ranks.forEach((r) =>
        rankOrder.set(JSON.stringify([s.name, r.name]), index++),
      ),
    );
    const key = el('matrix-sort').value;
    members = [...members].sort(
      (a, b) =>
        (key === 'rank'
          ? (rankOrder.get(JSON.stringify([a.rank_track, a.rank])) ?? 9999) -
            (rankOrder.get(JSON.stringify([b.rank_track, b.rank])) ?? 9999)
          : key === 'section'
            ? (a.billet_path || 'ZZZ').localeCompare(b.billet_path || 'ZZZ')
            : 0) || a.game_name.localeCompare(b.game_name),
    );
    const columns = selected ? [selected] : certificates;
    const unitMembers = current();
    el('matrix-coverage').innerHTML = columns
      .map((c) => {
        const count = scope.filter((m) => held(m).includes(c)).length;
        return `<div class="unit-block"><strong>${esc(c)}</strong><span>Filtered coverage: ${count}/${scope.length}${scope.length ? ` · ${Math.round((count / scope.length) * 100)}%` : ''}</span><small>Whole current unit: ${unitMembers.filter((m) => held(m).includes(c)).length}/${unitMembers.length}</small></div>`;
      })
      .join('');
    el('qualification-matrix').innerHTML = certificates.length
      ? `<table><thead><tr><th>Member</th><th>Primary billet</th>${columns.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${
          members
            .map(
              (m) =>
                `<tr><td>${memberButton(m)}<small>${m.archived ? 'Former' : esc(m.status)}</small></td><td>${esc(m.assignment_path || m.billet_path || 'Unassigned')}</td>${columns
                  .map((c) => {
                    const has = held(m).includes(c),
                      award = awards(m).find((a) => a.certificate === c);
                    const title = has
                      ? `Awarded: ${award?.awarded_on || 'Unknown'} · Issuer: ${award?.issuer || 'Unknown'}${award?.notes ? ' · ' + award.notes : ''}`
                      : 'Not held';
                    return `<td><button type="button" class="qualification-cell ${has ? 'qualification-held' : 'qualification-missing'}" data-qual-member="${m.id}" data-qual-name="${esc(c)}" title="${esc(title)}" aria-label="${esc(m.game_name + ' · ' + c + ' · ' + (has ? 'Held' : 'Missing'))}">${has ? (award?.expires_on && award.expires_on < metadata.today ? 'Expired' : '✓') : '—'}</button>${has && !el('matrix-checks').checked ? `<small>${esc(award?.awarded_on || 'Date unknown')}${award?.expires_on ? ' · Expires ' + esc(award.expires_on) : ''}</small>` : ''}</td>`;
                  })
                  .join('')}</tr>`,
            )
            .join('') ||
          `<tr><td colspan="${columns.length + 2}" class="unit-empty">No members match these filters.</td></tr>`
        }</tbody></table>`
      : '<p class="unit-empty">Create qualifications in Ranks & qualifications to build the matrix.</p>';
    bindMembers(el('qualification-matrix'));
    el('qualification-matrix')
      .querySelectorAll('[data-qual-member]')
      .forEach(
        (b) =>
          (b.onclick = () =>
            qualificationEditor(
              Number(b.dataset.qualMember),
              b.dataset.qualName,
            )),
      );
  }
  const renewalSelection = new Set();
  let renewalDraft = null;
  function renderRenewals() {
    const root = el('renewal-queue');
    if (!root || !context || !metadata) return;
    const renewing = new Set(
      (context.detail.unit.catalog.qualification_details || [])
        .filter((item) => item.renewal_required)
        .map((item) => item.name),
    );
    root.closest('details').hidden = !renewing.size;
    if (!renewing.size) return;
    if (root.dataset.unit !== String(context.unitId)) {
      renewalSelection.clear();
      renewalDraft = null;
      root.dataset.unit = context.unitId;
      root.innerHTML =
        '<h3>Qualification renewals</h3><div class="unit-toolbar"><label>Due<select id="renewal-range"><option value="30">Expired / within 30 days</option><option value="expired">Expired only</option><option value="90">Expired / within 90 days</option></select></label><label>Qualification<select id="renewal-certificate"></select></label><input type="search" id="renewal-search" placeholder="Search members" aria-label="Search renewal members"><button type="button" id="renewal-select">Select shown</button><button type="button" id="renewal-clear">Clear</button><button type="button" id="renewal-open">Renew selected</button></div><p id="renewal-count" role="status"></p><div class="unit-table renewal-table"><table><thead><tr><th>Select</th><th>Member</th><th>Qualification</th><th>Expiry</th></tr></thead><tbody id="renewal-rows"></tbody></table></div>';
    }
    const members = new Map(current().map((member) => [member.id, member]));
    const awards = (metadata.awards || []).filter(
      (award) =>
        members.has(award.member_id) && renewing.has(award.certificate),
    );
    const keys = new Set(
      awards.map((award) =>
        JSON.stringify([award.member_id, award.certificate]),
      ),
    );
    for (const key of renewalSelection)
      if (!keys.has(key)) renewalSelection.delete(key);
    const certificate = el('renewal-certificate'),
      previous = certificate.value;
    certificate.innerHTML =
      '<option value="">All qualifications</option>' +
      [...new Set(awards.map((award) => award.certificate))]
        .sort()
        .map((name) => `<option>${esc(name)}</option>`)
        .join('');
    certificate.value = previous;
    if (certificate.selectedIndex < 0) certificate.value = '';
    let shown = [];
    function draw() {
      [...renewalSelection]
        .slice(500)
        .forEach((key) => renewalSelection.delete(key));
      const range = el('renewal-range').value,
        query = el('renewal-search').value.trim().toLowerCase();
      const horizon = new Date(
        Date.parse(metadata.today + 'T00:00:00Z') +
          (range === 'expired' ? 0 : Number(range)) * 86400000,
      )
        .toISOString()
        .slice(0, 10);
      const matches = awards
        .filter(
          (award) =>
            (range === 'expired'
              ? !!award.expires_on && award.expires_on < metadata.today
              : !award.expires_on || award.expires_on <= horizon) &&
            (!certificate.value || award.certificate === certificate.value) &&
            members
              .get(award.member_id)
              .game_name.toLowerCase()
              .includes(query),
        )
        .sort((a, b) => a.expires_on.localeCompare(b.expires_on));
      shown = matches.slice(0, 500);
      el('renewal-rows').innerHTML =
        shown
          .map((award) => {
            const key = JSON.stringify([award.member_id, award.certificate]);
            return `<tr><td><input type="checkbox" data-renewal-key="${esc(key)}" ${renewalSelection.has(key) ? 'checked' : ''} aria-label="Select ${esc(members.get(award.member_id).game_name + ' ' + award.certificate)}"></td><td>${esc(members.get(award.member_id).game_name)}</td><td>${esc(award.certificate)}</td><td><span class="${award.expires_on < metadata.today ? 'unit-warn' : ''}">${esc(award.expires_on)}${award.expires_on < metadata.today ? ' · Expired' : ''}</span></td></tr>`;
          })
          .join('') || '<tr><td colspan="4">No renewals match.</td></tr>';
      el('renewal-count').textContent =
        `${matches.length} due · ${renewalSelection.size} selected${matches.length > 500 ? ' · Showing first 500; narrow your filters' : ''}`;
      el('renewal-open').disabled =
        !context.detail.can_edit || !renewalSelection.size;
      el('renewal-rows')
        .querySelectorAll('tr')
        .forEach((row, index) => {
          if (shown[index] && !shown[index].expires_on) {
            row.lastElementChild.textContent = 'Expiry not set';
            row.lastElementChild.className = 'unit-warn';
          }
        });
      el('renewal-select').disabled = !context.detail.can_edit;
      el('renewal-clear').disabled = !context.detail.can_edit;
      root.querySelectorAll('[data-renewal-key]').forEach((input) => {
        input.disabled = !context.detail.can_edit;
        input.onchange = () => {
          if (
            input.checked &&
            !renewalSelection.has(input.dataset.renewalKey) &&
            renewalSelection.size >= 500
          ) {
            input.checked = false;
            el('renewal-count').textContent =
              'Select at most 500 awards per renewal batch.';
            return;
          }
          if (input.checked) renewalSelection.add(input.dataset.renewalKey);
          else renewalSelection.delete(input.dataset.renewalKey);
          el('renewal-count').textContent =
            `${matches.length} due · ${renewalSelection.size} selected${matches.length > 500 ? ' · Showing first 500' : ''}`;
          el('renewal-open').disabled =
            !context.detail.can_edit || !renewalSelection.size;
        };
      });
    }
    for (const id of ['renewal-range', 'renewal-certificate'])
      el(id).onchange = draw;
    el('renewal-search').oninput = draw;
    el('renewal-select').onclick = () => {
      shown.forEach((award) =>
        renewalSelection.add(
          JSON.stringify([award.member_id, award.certificate]),
        ),
      );
      draw();
    };
    el('renewal-clear').onclick = () => {
      renewalSelection.clear();
      draw();
    };
    el('renewal-open').onclick = () => {
      const chosen = [...renewalSelection].map((key) => {
        const [member_id, certificate] = JSON.parse(key);
        return { member_id, certificate };
      });
      open(
        'Renew selected qualifications',
        `<p>${chosen.length} selected awards. Existing award notes are retained.</p><label class="unit-field">Renewal date<input name="awarded_on" type="date" required max="${metadata.today}" value="${metadata.today}"></label><label class="unit-field">New expiry (blank = permanent)<input name="expires_on" type="date"></label><label class="unit-field">Instructor<input name="issuer" maxlength="120" required value="${esc(metadata.actor)}"></label><label class="unit-field">Reason<textarea name="reason" maxlength="1000" required></textarea></label>`,
        async () => {
          const payload = {
            ...Object.fromEntries(new FormData(form)),
            awards: chosen,
          };
          renewalDraft = payload;
          const preview = await write(
            `${base()}/qualifications/renew`,
            payload,
          );
          open(
            'Review qualification renewals',
            `<p>${preview.changed} awards will change.</p><p>Renewal date: ${esc(payload.awarded_on)} · New expiry: ${esc(payload.expires_on || 'Permanent')} · Instructor: ${esc(payload.issuer)}</p><div class="unit-table"><table><thead><tr><th>Member</th><th>Qualification</th><th>Old expiry</th></tr></thead><tbody>${preview.changes.map((row) => `<tr><td>${esc(row.name)}</td><td>${esc(row.certificate)}</td><td>${esc(row.before.expires_on || 'Permanent')}</td></tr>`).join('')}</tbody></table></div><label><input type="checkbox" required> Confirm these renewals.</label>`,
            async () => {
              if (!preview.changed)
                throw new Error('There are no changes to apply.');
              await write(`${base()}/qualifications/renew`, {
                ...payload,
                confirmed: true,
                preview_token: preview.preview_token,
              });
              renewalSelection.clear();
              renewalDraft = null;
            },
            'Apply renewals',
          );
          const body = el('roster-tools-body'),
            back = document.createElement('button');
          back.type = 'button';
          back.textContent = 'Back to renewal details';
          back.onclick = () => el('renewal-open').onclick();
          const reason = document.createElement('p');
          reason.textContent = 'Reason: ' + payload.reason;
          body.append(reason, back);
          for (const [name, value] of Object.entries({
            ...payload,
            awards: JSON.stringify(payload.awards),
          })) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = value;
            body.append(input);
          }
          return false;
        },
        'Review renewals',
      );
      form.elements.expires_on.required = true;
      if (renewalDraft)
        for (const name of ['awarded_on', 'expires_on', 'issuer', 'reason'])
          form.elements[name].value = renewalDraft[name];
      form.elements.expires_on.closest('label').firstChild.textContent =
        'New expiry date';
      baseline = sign();
    };
    draw();
  }
  function qualificationEditor(memberId, certificate = '') {
    if (saving) return;
    if (!metadata) {
      feedback(
        'Award records are not loaded yet. Refresh the unit and try again.',
      );
      return;
    }
    const member = context.detail.roster.find((m) => m.id === memberId);
    if (!member) return;
    const catalog = (context.detail.unit.catalog.certificates || []).filter(
      (name) =>
        !context.detail.unit.catalog.qualification_details?.some(
          (item) => item.name === name && item.archived,
        ) || member.certificates.split(';').includes(name),
    );
    certificate ||= catalog[0];
    if (!certificate) {
      feedback(
        'No active qualifications are available. Create or restore one in Rank & qualification setup.',
      );
      return;
    }
    const canEdit = context.detail.can_edit,
      revision = context.detail.unit.revision;
    open(
      `${member.game_name} — qualification`,
      `<label class="unit-field">Qualification<select name="certificate">${catalog.map((c) => `<option ${c === certificate ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label><div id="qualification-award-fields"></div>`,
      canEdit
        ? async () => {
            const values = Object.fromEntries(new FormData(form));
            await write(`${base()}/roster/${member.id}/qualifications`, {
              ...values,
              member_token: member.edit_token,
              revision,
            });
          }
        : null,
    );
    function fields() {
      const chosen = form.elements.certificate.value,
        has = held(member).includes(chosen),
        award = awards(member).find((a) => a.certificate === chosen);
      el('qualification-award-fields').innerHTML =
        `<p>${has ? 'Currently held' : 'Not held'} · Issuer: ${esc(award?.issuer || (has ? 'Unknown — existing record' : 'Defaults to your name in this unit; enter the original instructor if needed'))}</p>${canEdit ? `<label class="unit-field">Action<select name="action">${has ? '<option value="update">Update award details</option><option value="revoke">Revoke qualification</option>' : '<option value="grant">Grant qualification</option>'}</select></label>` : ''}<label class="unit-field">Award date<input type="date" name="awarded_on" value="${esc(has ? award?.awarded_on || '' : metadata.today)}" max="${metadata.today}" ${canEdit ? '' : 'disabled'}></label><label class="unit-field">Expires on (optional)<input type="date" name="expires_on" value="${esc(award?.expires_on || '')}" ${canEdit ? '' : 'disabled'}></label><label class="unit-field">Issuing staff / instructor<input name="issuer" maxlength="120" value="${esc(has ? award?.issuer || '' : metadata.actor)}" ${canEdit ? '' : 'disabled'} placeholder="Unknown if left blank"></label><label class="unit-field">Award notes<textarea name="notes" maxlength="1000" ${canEdit ? '' : 'disabled'}>${esc(award?.notes || '')}</textarea></label>${canEdit ? '<label class="unit-field">Change / revocation reason<textarea name="reason" maxlength="1000"></textarea></label>' : ''}<p class="feature-note">Grant/revoke changes affect promotion readiness. Earlier grant and revocation entries remain in the member timeline. The issuing name changes only when you edit it; the timeline separately records who saved the change.</p>`;
      if (canEdit) {
        const renews = context.detail.unit.catalog.qualification_details?.some(
          (item) => item.name === chosen && item.renewal_required,
        );
        form.elements.expires_on.closest('label').hidden = !renews;
        form.elements.expires_on.closest('label').firstChild.textContent =
          'Expiry date';
        form.elements.expires_on.disabled = !renews;
        const setRequired = () => {
          form.elements.awarded_on.required =
            form.elements.action.value === 'grant';
          form.elements.reason.required =
            form.elements.action.value === 'revoke';
          form.elements.expires_on.required =
            !!renews && form.elements.action.value !== 'revoke';
        };
        form.elements.action.onchange = setRequired;
        setRequired();
      } else
        form.elements.expires_on.closest('label').hidden =
          !context.detail.unit.catalog.qualification_details?.some(
            (item) => item.name === chosen && item.renewal_required,
          );
      baseline = sign();
    }
    fields();
    form.elements.certificate.onchange = () => {
      const selected = form.elements.certificate.value;
      form.elements.certificate.value = certificate;
      if (sign() !== baseline && !confirm('Discard unsaved award details?')) {
        form.elements.certificate.value = certificate;
        return;
      }
      certificate = selected;
      form.elements.certificate.value = selected;
      fields();
    };
    baseline = sign();
  }
  function renderPromotions() {
    if (!context) return;
    const filter = el('promotion-filter').value,
      query = el('promotion-search').value.trim().toLowerCase();
    const upcomingUntil = metadata
      ? new Date(Date.parse(metadata.today + 'T00:00:00Z') + 30 * 86400000)
          .toISOString()
          .slice(0, 10)
      : '';
    const members = current()
      .filter(
        (m) =>
          [m.game_name, m.rank_track, m.rank, m.promotion.next_rank]
            .join(' ')
            .toLowerCase()
            .includes(query) &&
          (filter === 'all' ||
            (filter === 'upcoming'
              ? !!m.promotion.next_date &&
                m.promotion.next_date > metadata?.today &&
                m.promotion.next_date <= upcomingUntil
              : filter === 'eligible'
                ? m.promotion.eligible
                : !m.promotion.eligible)),
      )
      .sort(
        (a, b) =>
          Number(b.promotion.eligible) - Number(a.promotion.eligible) ||
          (a.promotion.next_date || '9999').localeCompare(
            b.promotion.next_date || '9999',
          ) ||
          a.game_name.localeCompare(b.game_name),
      );
    el('promotion-queue').innerHTML =
      `<table><thead><tr><th>Member</th><th>Current rank</th><th>Next rank</th><th>Eligibility</th><th>Unmet requirements</th><th>Review</th></tr></thead><tbody>${
        members
          .map((m) => {
            const p = m.promotion;
            return `<tr><td>${memberButton(m)}</td><td>${esc(m.rank || 'Not assigned')}</td><td>${esc(p.next_rank || 'No next rank')}</td><td>${p.eligible ? '<strong class="unit-good">Eligible for review</strong>' : 'Not eligible'}<small>${esc(p.next_date || (p.next_rank ? 'Set last promotion date' : 'Configure a rank path'))}</small></td><td>${esc(p.missing.join(', ') || (p.next_rank ? 'Qualifications met' : 'No advancement path'))}${p.next_date && p.next_date > metadata?.today ? '<small>Time requirement not met</small>' : ''}</td><td>${context.detail.can_edit ? `<button type="button" data-promote="${m.id}" ${p.next_rank && metadata ? '' : 'disabled'}>Review promotion</button>` : 'View only'}</td></tr>`;
          })
          .join('') ||
        '<tr><td colspan="6" class="unit-empty">No members match this review queue.</td></tr>'
      }</tbody></table>`;
    bindMembers(el('promotion-queue'));
    el('promotion-queue')
      .querySelectorAll('[data-promote]')
      .forEach(
        (b) => (b.onclick = () => promotionEditor(Number(b.dataset.promote))),
      );
  }
  function promotionEditor(memberId) {
    if (saving || !metadata) return;
    const member = context.detail.roster.find((item) => item.id === memberId),
      revision = context.detail.unit.revision;
    if (!member?.promotion.next_rank || !context.detail.can_edit) return;
    const target = member.promotion.next_rank;
    open(
      `Review promotion — ${member.game_name}`,
      `<p>${esc(member.rank_track)} · ${esc(member.rank)} → <strong>${esc(target)}</strong></p><label class="unit-field">Effective promotion date<input type="date" name="effective_date" required max="${metadata.today}" value="${metadata.today}"></label><p class="feature-note">Use the actual effective date when catching up on paperwork. Time and recorded qualification dates are rechecked for that date.</p><div id="promotion-date-preview" role="status"></div><label class="unit-field">Staff review note<textarea name="reason" required maxlength="1000"></textarea></label><label><input type="checkbox" name="confirmed" required> I approve this promotion and its effective date.</label>`,
      async () => {
        await write(`${base()}/roster/${member.id}/promote`, {
          revision,
          member_token: member.edit_token,
          effective_date: form.elements.effective_date.value,
          confirm_rank: target,
          confirm_date: metadata.today,
          reason: form.elements.reason.value,
        });
      },
      'Confirm promotion',
    );
    let request = 0;
    async function preview() {
      const serial = ++request,
        button = form.querySelector('[type="submit"]'),
        region = el('promotion-date-preview');
      button.disabled = true;
      try {
        const data = await write(
          `${base()}/roster/${member.id}/promotion-preview`,
          { effective_date: form.elements.effective_date.value },
        );
        if (serial !== request || !region.isConnected) return;
        const p = data.promotion;
        region.textContent = p.eligible
          ? `Eligible on ${data.effective_date}. Approval remains manual.`
          : `Not eligible on this date. ${p.next_date ? 'Time requirement date: ' + p.next_date + '. ' : 'Set the previous promotion date. '}${p.missing.length ? 'Missing/invalid qualifications: ' + p.missing.join(', ') : ''}`;
        button.disabled = !p.eligible;
      } catch (error) {
        if (serial === request && region.isConnected)
          region.textContent = error.message;
      }
    }
    form.elements.effective_date.onchange = preview;
    preview();
    baseline = sign();
  }
  function bulkEditor(initial = {}) {
    if (saving && !initial.fromPreview) return;
    if (!context?.detail.can_edit || !metadata) return;
    const members = current(),
      chosen = new Set(initial.members || []),
      catalog = context.detail.unit.catalog.certificates || [];
    const sections = context.detail.structure.filter(
      (n) => n.kind === 'section',
    );
    open(
      'Bulk roster edit',
      `<p class="feature-note">Select up to 500 current members. Review every proposed change before applying. Section moves fill open primary billets; ranks and qualifications do not restrict placement.</p><div class="bulk-layout"><section><div class="unit-toolbar"><input type="search" id="bulk-search" aria-label="Find members for bulk editing" placeholder="Search members"><button type="button" id="bulk-select-visible">Select shown</button><button type="button" id="bulk-clear">Clear selection</button></div><p id="bulk-count" role="status"></p><div class="bulk-member-list">${members.map((m) => `<label data-bulk-row="${m.id}"><input type="checkbox" name="bulk_members" value="${m.id}" ${chosen.has(m.id) ? 'checked' : ''}><span>${esc(m.game_name)}<small>${esc([m.rank_display || m.rank, m.status, m.assignment_path || m.billet_path || 'Unassigned'].join(' · '))}</small></span></label>`).join('') || '<p>No current members.</p>'}</div></section><section><label class="unit-field">Change<select name="action"><option value="grant">Grant qualification</option><option value="revoke">Revoke qualification</option><option value="status">Change status</option><option value="section">Move to section’s open billets</option><option value="unassign">Remove primary placement</option></select></label><div id="bulk-fields"></div><label class="unit-field">Reason / award note<textarea name="reason" required maxlength="1000">${esc(initial.reason || '')}</textarea></label></section></div>`,
      async () => {
        const data = Object.fromEntries(new FormData(form));
        delete data.bulk_members;
        const payload = {
          ...data,
          members: [
            ...form.querySelectorAll('[name="bulk_members"]:checked'),
          ].map((c) => Number(c.value)),
          revision: context.detail.unit.revision,
        };
        if (data.section_id !== undefined)
          payload.section_id = Number(data.section_id);
        const preview = await write(`${base()}/roster/bulk/preview`, payload);
        showBulkPreview(payload, preview);
        return false;
      },
      'Preview changes',
    );
    form.elements.action.value = initial.action || 'grant';
    function fields() {
      const action = form.elements.action.value;
      const available =
        action === 'grant'
          ? catalog.filter(
              (name) =>
                !context.detail.unit.catalog.qualification_details?.some(
                  (item) => item.name === name && item.archived,
                ),
            )
          : catalog;
      el('bulk-fields').innerHTML =
        action === 'grant' || action === 'revoke'
          ? `<label class="unit-field">Qualification<select name="certificate" required>${available.map((c) => `<option ${c === initial.certificate ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>${!available.length ? '<p class="unit-warn">Create or restore a qualification in setup first.</p>' : ''}${action === 'grant' ? `<label class="unit-field">Award date<input type="date" name="awarded_on" required value="${esc(initial.awarded_on || metadata.today)}" max="${metadata.today}"></label><label class="unit-field">Instructor<input name="issuer" maxlength="120" value="${esc(initial.issuer || metadata.actor)}"></label><label class="unit-field">Expires on (optional)<input type="date" name="expires_on" value="${esc(initial.expires_on || '')}"></label><p class="feature-note">Members who already hold it keep their current award date, expiry and issuer. Renew existing awards through Manage qualifications.</p>` : ''}`
          : action === 'status'
            ? `<label class="unit-field">New status<select name="status">${['active', 'reserve', 'loa'].map((s) => `<option value="${s}" ${s === initial.status ? 'selected' : ''}>${s === 'loa' ? 'LOA' : s[0].toUpperCase() + s.slice(1)}</option>`).join('')}</select></label><p class="feature-note">Changing status clears the previous LOA dates. Set date ranges in Edit member. Future event rosters update; past and active event expectations stay unchanged.</p>`
            : action === 'section'
              ? `<label class="unit-field">Target section<select name="section_id" required>${sections.map((s) => `<option value="${s.id}" ${s.id === initial.section_id ? 'selected' : ''}>${esc(path(s.id))}</option>`).join('')}</select></label><p class="feature-note">Members already in this section stay in their billets. Others receive vacant billets in structure order. The preview lists each assignment. No change is applied if there are too few vacancies.</p>${!sections.length ? '<p class="unit-warn">Create sections and billets in Structure first.</p>' : ''}`
              : '<p>Selected members will become unassigned. Their roster records remain.</p>';
    }
    const renderFields = () => {
      fields();
      const expiry = form.elements.expires_on;
      if (expiry) {
        const toggle = () => {
          const enabled =
            context.detail.unit.catalog.qualification_details?.some(
              (item) =>
                item.name === form.elements.certificate.value &&
                item.renewal_required,
            );
          expiry.closest('label').hidden = !enabled;
          expiry.disabled = !enabled;
          expiry.required = !!enabled;
        };
        form.elements.certificate.onchange = toggle;
        toggle();
      }
    };
    renderFields();
    form.elements.action.onchange = renderFields;
    const updateCount = () => {
      el('bulk-count').textContent =
        `${form.querySelectorAll('[name="bulk_members"]:checked').length} selected`;
    };
    form
      .querySelectorAll('[name="bulk_members"]')
      .forEach((c) => (c.onchange = updateCount));
    el('bulk-search').oninput = () => {
      const query = el('bulk-search').value.trim().toLowerCase();
      form.querySelectorAll('[data-bulk-row]').forEach((row) => {
        row.hidden = !row.textContent.toLowerCase().includes(query);
      });
    };
    el('bulk-select-visible').onclick = () => {
      form
        .querySelectorAll('[data-bulk-row]:not([hidden]) input')
        .forEach((c) => {
          c.checked = true;
        });
      updateCount();
    };
    el('bulk-clear').onclick = () => {
      form.querySelectorAll('[name="bulk_members"]').forEach((c) => {
        c.checked = false;
      });
      updateCount();
    };
    updateCount();
    baseline = sign();
  }
  function showBulkPreview(payload, preview) {
    const changed = preview.changes.filter(
      (c) => JSON.stringify(c.before) !== JSON.stringify(c.after),
    ).length;
    const describe = (s) =>
      payload.action === 'status'
        ? s.status
        : payload.action === 'section' || payload.action === 'unassign'
          ? s.assignment_path ||
            s.billet_path ||
            s.placement_path ||
            'Unassigned'
          : s.certificates.split(';').filter(Boolean).join(', ') || 'None';
    open(
      'Review bulk changes',
      `<p><strong>${changed}</strong> of ${preview.changes.length} selected members will change.</p><p class="member-record-note">Reason: ${esc(payload.reason)}</p>${payload.action === 'grant' ? `<p>Award date: ${esc(payload.awarded_on)} · Instructor: ${esc(payload.issuer || metadata.actor)} · Expiry: ${esc(payload.expires_on || 'None')}</p>` : ''}<div class="unit-table bulk-preview-table"><table><thead><tr><th>Member</th><th>Before</th><th>After</th></tr></thead><tbody>${preview.changes.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(describe(c.before))}</td><td>${esc(describe(c.after))}${JSON.stringify(c.before) === JSON.stringify(c.after) ? '<small>No change</small>' : ''}</td></tr>`).join('')}</tbody></table></div><button type="button" id="bulk-back">Back to selection</button><label class="bulk-confirm"><input type="checkbox" name="confirm" required> Apply exactly these changes to the listed members.</label>`,
      async () => {
        if (!changed)
          throw new Error(
            'No changes to apply. Go back and choose a different change.',
          );
        await write(`${base()}/roster/bulk/apply`, {
          ...payload,
          preview_token: preview.preview_token,
        });
      },
      'Apply reviewed changes',
    );
    if (payload.action === 'grant') {
      const description = form.querySelector(
        '.bulk-preview-table',
      ).previousElementSibling;
      description.textContent = `Award date: ${payload.awarded_on} · Instructor: ${payload.issuer || metadata.actor}${payload.expires_on ? ' · Expiry: ' + payload.expires_on : ''}`;
    }
    el('bulk-back').onclick = () =>
      bulkEditor({ ...payload, fromPreview: true });
    baseline = sign();
  }
  async function loaded(event) {
    const token = ++generation;
    if (dialog.open && !saving) dialog.close();
    context = event.detail;
    metadata = null;
    if (context.detail.role === 'member') return;
    el('roster-bulk').hidden = !context.detail.can_edit;
    el('roster-bulk').disabled = true;
    for (const [id, options] of [
      ['matrix-section', ['all', 'All groups / sections']],
      ['matrix-certificate', ['', 'All qualifications']],
    ]) {
      const previous = el(id).value;
      el(id).replaceChildren(new Option(options[1], options[0]));
      if (id === 'matrix-section') {
        el(id).add(new Option('Unassigned', 'unassigned'));
        context.detail.structure
          .filter((n) => n.kind !== 'billet')
          .forEach((n) => el(id).add(new Option(path(n.id), n.id)));
      } else
        (context.detail.unit.catalog.certificates || []).forEach((c) =>
          el(id).add(new Option(c, c)),
        );
      if ([...el(id).options].some((o) => o.value === previous))
        el(id).value = previous;
    }
    el('qualification-matrix').textContent = 'Loading award records…';
    if (!el('unit-promotions').hidden) renderPromotions();
    try {
      const result = await read(`${base()}/roster-tools`);
      if (token !== generation) return;
      if (result.revision !== context.detail.unit.revision) {
        feedback(
          'This unit changed while loading. Refresh to see the current roster.',
        );
        return;
      }
      metadata = result;
      el('roster-bulk').disabled = false;
      if (!el('unit-qualifications').hidden) renderMatrix();
      if (!el('unit-promotions').hidden) renderPromotions();
    } catch (error) {
      if (token === generation) {
        feedback(error.message);
        const retry = () =>
          document.dispatchEvent(new Event('unit-access-changed'));
        UnitUX.error(el('qualification-matrix'), error, retry);
        UnitUX.error(el('promotion-queue'), error, retry);
      }
    }
  }
  document.addEventListener('unit-loaded', loaded);
  document.addEventListener('unit-section-changed', (event) => {
    if (event.detail.tab === 'qualifications') renderMatrix();
    if (event.detail.tab === 'promotions') renderPromotions();
  });
  document.addEventListener('unit-review-promotion', (e) =>
    promotionEditor(e.detail),
  );
  document.addEventListener('unit-manage-qualification', (e) =>
    qualificationEditor(
      typeof e.detail === 'object' ? e.detail.member_id : e.detail,
      typeof e.detail === 'object' ? e.detail.certificate : '',
    ),
  );
  el('roster-bulk').onclick = () => {
    el('roster-bulk').closest('details')?.removeAttribute('open');
    bulkEditor();
  };
  document.querySelectorAll('[data-bulk-action]').forEach(
    (button) =>
      (button.onclick = () => {
        button.closest('details').open = false;
        bulkEditor({ action: button.dataset.bulkAction });
      }),
  );
  for (const id of [
    'matrix-search',
    'matrix-status',
    'matrix-section',
    'matrix-certificate',
    'matrix-held',
    'matrix-sort',
    'matrix-checks',
  ])
    el(id).addEventListener(
      id === 'matrix-search' ? 'input' : 'change',
      renderMatrix,
    );
  el('promotion-search').oninput = renderPromotions;
  el('promotion-filter').onchange = renderPromotions;
})();
