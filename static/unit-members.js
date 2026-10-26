// Member pages use self-service endpoints; staff records never enter these views.
(() => {
  const el = (id) => document.getElementById(id),
    esc = escHtml;
  const read = async (url) => readJson(await fetch(url)),
    write = async (url, data) => readJson(await postJson(url, data));
  let context,
    home,
    epoch = 0,
    requestId = 0,
    saving = false,
    baseline = '',
    handler;
  const base = () => `/api/units/${context.unitId}`;
  const when = (seconds) => new Date(seconds * 1000).toLocaleString();
  const navigate = (tab) =>
    document.dispatchEvent(new CustomEvent('unit-navigate', { detail: tab }));
  const openSop = (id) =>
    document.dispatchEvent(
      new CustomEvent('unit-open-reference', {
        detail: { id, published: true },
      }),
    );
  const dialog = document.createElement('dialog');
  dialog.className = 'unit-dialog resource-dialog';
  dialog.setAttribute('aria-labelledby', 'member-action-title');
  dialog.innerHTML =
    '<form id="member-action-form"><div class="unit-dialog-heading"><h2 id="member-action-title"></h2><button type="button" id="member-action-close">Close</button></div><div id="member-action-body"></div><p id="member-action-error" role="alert"></p><div class="unit-dialog-footer"><button type="submit" class="btn-save" id="member-action-save">Save announcement</button></div></form>';
  document.body.append(dialog);
  el('member-action-error').tabIndex = -1;
  const form = el('member-action-form'),
    signature = () => JSON.stringify([...new FormData(form)]);
  UnitUX.registerDraft({
    dirty: () => dialog.open && signature() !== baseline,
    busy: () => dialog.open && saving,
    discard: () => dialog.close(),
  });
  const close = () => UnitUX.close(dialog);
  el('member-action-close').onclick = close;
  dialog.addEventListener('cancel', (e) => {
    e.preventDefault();
    close();
  });
  form.onsubmit = async (e) => {
    e.preventDefault();
    if (saving) return;
    saving = true;
    try {
      await UnitUX.save(dialog, handler, () => {
        dialog.close();
        document.dispatchEvent(new Event('unit-access-changed'));
      });
    } finally {
      saving = false;
    }
  };
  function announcementEditor(item = null) {
    if (saving || !home?.can_manage) return;
    const unitBase = base(),
      revision = home.revision;
    const content = `<label class="unit-field">Title<input name="title" maxlength="120" required value="${esc(item?.title || '')}"></label><label class="unit-field">Announcement<textarea name="body" maxlength="8000" required>${esc(item?.body || '')}</textarea></label><label><input type="checkbox" name="pinned" ${item?.pinned ? 'checked' : ''}> Pin above other announcements</label><label class="unit-field">Show through (optional)<input type="date" name="expires_on" value="${esc(item?.expires_on || '')}"></label>${item ? `<label><input type="checkbox" name="archived" ${item.archived ? 'checked' : ''}> Archive this announcement</label>` : ''}`;
    el('member-action-error').textContent = '';
    handler = async () => {
      const values = Object.fromEntries(new FormData(form));
      await write(`${unitBase}/announcements`, {
        ...values,
        pinned: !!values.pinned,
        archived: !!values.archived,
        revision,
        ...(item ? { id: item.id } : {}),
      });
    };
    UnitUX.prepare(dialog, {
      title: item ? 'Edit announcement' : 'New unit announcement',
      body: el('member-action-body'),
      content,
      button: 'Save announcement',
    });
    baseline = signature();
  }
  function eventCard(event, canEvents) {
    const counts = Object.fromEntries(
      ['attending', 'tentative', 'unavailable'].map((answer) => [
        answer,
        (event.responses || []).filter((r) => r.answer === answer).length,
      ]),
    );
    return `<article class="unit-block member-event"><h3>${esc(event.name)}</h3><p>${esc(when(event.starts))} – ${esc(when(event.ends))}</p><small>${esc(event.category)}${event.location ? ' · ' + esc(event.location) : ''}</small><p class="reference-prose">${esc(event.briefing)}</p><label class="unit-field">Your RSVP<select data-member-rsvp="${event.id}" ${event.can_rsvp ? '' : 'disabled'}><option value="clear">No response</option>${['attending', 'tentative', 'unavailable'].map((answer) => `<option value="${answer}" ${event.rsvp === answer ? 'selected' : ''}>${esc(answer[0].toUpperCase() + answer.slice(1))}</option>`).join('')}</select></label>${!event.can_rsvp ? '<small>RSVPs require a linked, active roster record and close when the event starts.</small>' : ''}${canEvents ? `<details><summary>Responses · ${counts.attending} attending · ${counts.tentative} tentative · ${counts.unavailable} unavailable</summary>${(event.responses || []).map((r) => `<p>${esc(r.game_name)} · ${esc(r.answer)}</p>`).join('') || '<p>No responses yet.</p>'}</details>` : ''}</article>`;
  }
  async function loadHome() {
    const current = epoch,
      id = ++requestId,
      unitBase = base(),
      data = await read(`${unitBase}/member-home`);
    if (current !== epoch || id !== requestId) return;
    home = data;
    const unread = data.reading.filter((r) => !r.acknowledged_at),
      reviews = data.reviews.filter((r) => r.review_on <= data.today);
    el('member-home-content').innerHTML =
      `<div class="unit-summary"><span>Required unread <strong>${unread.length}</strong></span><span>Upcoming events <strong>${data.events.length}</strong></span><span>Announcements <strong>${data.announcements.length}</strong></span>${data.can_manage ? `<span>Reviews due <strong>${data.review_due}</strong></span>` : ''}</div><div class="unit-toolbar"><button type="button" id="member-open-sops">SOP repository</button><button type="button" id="member-open-profile">My profile</button><button type="button" id="member-home-refresh">Refresh</button>${data.can_manage ? '<button type="button" id="member-announcement-new" class="btn-save">New announcement</button>' : ''}</div>${!data.profile_linked ? '<p class="unit-block">Your login is not linked to a roster record. Ask a unit administrator to link it for your personal profile, role-specific reading and RSVPs.</p>' : ''}<div class="unit-dashboard-grid"><section class="unit-block"><h2>Required reading</h2><p class="feature-note">Open a document, then acknowledge its published version. A new publication requires a new acknowledgement.</p>${data.reading.map((r) => `<div class="member-reading-row"><button type="button" data-member-sop="${r.id}">${esc(r.title)}</button><small>${r.acknowledged_at ? 'Acknowledged ' + esc(when(r.acknowledged_at)) : r.due && r.due < data.today ? 'Overdue · ' + esc(r.due) : r.due ? 'Due ' + esc(r.due) : 'Awaiting acknowledgement'}</small></div>`).join('') || '<p>No reading assigned to your account.</p>'}</section><section class="unit-block"><h2>Announcements</h2>${data.announcements.map((a) => `<article class="member-announcement"><h3>${a.pinned ? 'Pinned · ' : ''}${esc(a.title)}</h3><p class="reference-prose">${esc(a.body)}</p><small>${esc(a.author)} · ${esc(when(a.updated_at))}${a.expires_on ? ' · Through ' + esc(a.expires_on) : ''}</small>${data.can_manage ? `<button type="button" data-member-announcement="${a.id}">Edit announcement</button>` : ''}</article>`).join('') || '<p>No current announcements.</p>'}${data.can_manage ? `<details><summary>Manage latest 100 announcements</summary>${data.announcement_history.map((a) => `<p><button type="button" data-member-announcement="${a.id}">${esc(a.title)}</button> <small>${a.archived ? 'Archived' : a.expires_on && a.expires_on < data.today ? 'Expired' : 'Current'}</small></p>`).join('')}</details>` : ''}</section>${data.can_manage ? `<section class="unit-block"><h2>SOP review reminders</h2><p>${reviews.length} review${reviews.length === 1 ? '' : 's'} due. Review dates are reminders; they do not unpublish documents.</p>${data.reviews.map((r) => `<p><button type="button" data-review-sop="${r.id}">${esc(r.title)}</button><small>${esc(r.owner)} · ${r.review_on <= data.today ? 'Due' : 'Next review'} ${esc(r.review_on)}</small></p>`).join('') || '<p>No review dates set. Open an SOP and choose Reading & review to assign an owner and date.</p>'}</section>` : ''}</div><h2>Upcoming events</h2><p class="feature-note">RSVPs help staff plan. They never mark attendance or excuse an absence; attendance continues to use UUID evidence and staff review.</p><div class="unit-dashboard-grid">${data.events.map((e) => eventCard(e, data.can_events)).join('') || '<p class="unit-empty">No upcoming events.</p>'}</div>`;
    el('member-open-sops').onclick = () => navigate('references');
    el('member-open-profile').onclick = () => navigate('profile');
    el('member-home-refresh').onclick = () => refresh();
    el('member-announcement-new')?.addEventListener('click', () =>
      announcementEditor(),
    );
    el('member-home-content')
      .querySelectorAll('[data-member-sop]')
      .forEach((b) => (b.onclick = () => openSop(Number(b.dataset.memberSop))));
    el('member-home-content')
      .querySelectorAll('[data-review-sop]')
      .forEach(
        (b) =>
          (b.onclick = () =>
            document.dispatchEvent(
              new CustomEvent('unit-open-reference', {
                detail: { id: Number(b.dataset.reviewSop) },
              }),
            )),
      );
    el('member-home-content')
      .querySelectorAll('[data-member-announcement]')
      .forEach(
        (b) =>
          (b.onclick = () =>
            announcementEditor(
              data.announcement_history.find(
                (a) => a.id === Number(b.dataset.memberAnnouncement),
              ),
            )),
      );
    el('member-home-content')
      .querySelectorAll('[data-member-rsvp]')
      .forEach(
        (select) =>
          (select.onchange = async () => {
            const event = data.events.find(
              (e) => e.id === Number(select.dataset.memberRsvp),
            );
            select.disabled = true;
            try {
              await write(`${unitBase}/member-events/${event.id}/rsvp`, {
                answer: select.value,
                version: event.version,
              });
              if (current === epoch) await refresh();
            } catch (error) {
              if (current === epoch) {
                select.value = event.rsvp || 'clear';
                el('units-feedback').textContent = error.message;
              }
            } finally {
              if (select.isConnected) select.disabled = !event.can_rsvp;
            }
          }),
      );
  }
  async function loadProfile() {
    const current = epoch,
      id = ++requestId,
      data = await read(`${base()}/my-profile`);
    if (current !== epoch || id !== requestId) return;
    const m = data.member,
      region = el('member-profile-content');
    if (!m) {
      region.innerHTML =
        '<p class="unit-block">Your login has no linked roster member in this unit. Ask a unit administrator to link it under Accounts & access or Edit member.</p>';
      return;
    }
    const counted = data.attendance.filter(
        (e) => e.expected && ['present', 'absent'].includes(e.outcome),
      ),
      present = counted.filter((e) => e.outcome === 'present').length;
    region.innerHTML = `<div class="unit-summary"><span>Game name <strong>${esc(m.game_name)}</strong></span><span>Status <strong>${esc(m.archived ? 'Former member' : m.status === 'loa' ? 'LOA' : m.status)}</strong></span><span>Rank <strong>${esc(m.rank || 'Unassigned')}</strong></span><span>Attendance <strong>${counted.length ? Math.round((present / counted.length) * 100) + '%' : '—'}</strong></span></div><div class="unit-dashboard-grid"><section class="unit-block"><h2>My unit record</h2><p>Discord: ${esc(m.discord || 'Not set')}</p><p>Callsign: ${esc(m.effective_callsign || 'Not assigned')}</p><p>Rank structure: ${esc(m.rank_track || 'Not assigned')}</p><p>Primary position: ${esc(data.positions.join(' / ') || m.position || 'Unassigned')}</p><p>Joined: ${esc(m.joined_on || 'Not set')}</p><p>Last promotion: ${esc(m.last_promo || 'Not set')}</p><p class="feature-note">Ask staff to correct your record. Staff notes, attendance reasons and administrative history are private.</p></section><section class="unit-block"><h2>Qualifications</h2>${data.qualifications.map((q) => `<p><strong>${esc(q.certificate)}</strong><small>Awarded: ${esc(q.awarded_on || 'Date not recorded')}</small></p>`).join('') || '<p>No qualifications recorded.</p>'}</section></div><section class="unit-block"><h2>My finalized attendance</h2><p class="feature-note">Latest 100 finalized, tracked events. The rate uses expected Present/Absent decisions; unknown and excused results are excluded.</p><div class="unit-table"><table><thead><tr><th>Event</th><th>Date</th><th>Outcome</th><th>Expected</th></tr></thead><tbody>${data.attendance.map((e) => `<tr><td>${esc(e.name)}</td><td>${esc(when(e.starts))}</td><td>${esc(e.outcome || 'unknown')}</td><td>${e.expected ? 'Yes' : 'Optional / exempt'}</td></tr>`).join('') || '<tr><td colspan="4">No finalized attendance yet.</td></tr>'}</tbody></table></div></section>`;
  }
  async function refresh() {
    if (!context) return;
    const tab = document.querySelector('[data-unit-tab][aria-selected="true"]')
      ?.dataset.unitTab;
    if (!['home', 'profile'].includes(tab)) return;
    const current = epoch,
      region = el(
        tab === 'home' ? 'member-home-content' : 'member-profile-content',
      );
    region.setAttribute('aria-busy', 'true');
    try {
      await (tab === 'home' ? loadHome() : loadProfile());
    } catch (error) {
      if (current === epoch) UnitUX.error(region, error, refresh);
    } finally {
      if (current === epoch) region.removeAttribute('aria-busy');
    }
  }
  document.addEventListener('unit-loaded', (e) => {
    epoch++;
    requestId++;
    context = e.detail;
    home = null;
    if (dialog.open && !saving) dialog.close();
    el('member-home-content').textContent = 'Loading…';
    el('member-profile-content').textContent = 'Loading…';
    refresh();
  });
  document.addEventListener('unit-section-changed', refresh);
  document.addEventListener('unit-member-change', refresh);
})();
