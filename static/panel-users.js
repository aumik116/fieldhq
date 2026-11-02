// Panel-wide account management, independent of the selected server or unit.
(async () => {
  const el = (id) => document.getElementById(id);
  let inviteRequest = 0;
  async function invitations() {
    const request = ++inviteRequest;
    const unit = el('users-invite-unit').value;
    const query = new URLSearchParams({
      unit,
      q: el('users-invite-search').value.trim(),
    });
    el('users-invite-refresh').disabled = true;
    el('users-invite-status').textContent = 'Loading invitations…';
    try {
      const data = await readJson(
        await fetch('/api/member-invitations?' + query),
      );
      if (request !== inviteRequest) return;
      const select = el('users-invite-unit');
      select.replaceChildren(new Option('All units', ''));
      data.units.forEach((u) => select.add(new Option(u.name, String(u.id))));
      select.value = data.units.some((u) => String(u.id) === unit) ? unit : '';
      el('users-invite-count').textContent =
        String(data.invitations.length) + (data.more ? '+' : '');
      el('users-invite-status').textContent = data.more
        ? 'Showing the first 500 matching invitations. Search or select a unit to narrow the list.'
        : `${data.invitations.length} pending invitations match these filters.`;
      const root = el('users-invite-results');
      root.innerHTML =
        data.invitations
          .map(
            (invite, index) =>
              `<article class="unit-block feature-row"><div class="account-list-identity"><strong>${escHtml(invite.game_name)}</strong><small class="unit-meta">${escHtml(invite.unit_name)} · Invited by ${escHtml(invite.invited_by)}</small><small class="unit-meta">Created ${escHtml(new Date(invite.created_at * 1000).toLocaleString())} · Expires ${escHtml(new Date(invite.expires_at * 1000).toLocaleString())}</small></div><div class="unit-toolbar"><a class="manager-link" href="/units?unit=${invite.unit_id}&tab=roster">Open unit roster</a><button type="button" data-revoke-invite="${index}">Revoke</button></div></article>`,
          )
          .join('') || '<p>No pending signup invitations.</p>';
      root.querySelectorAll('[data-revoke-invite]').forEach((button) => {
        const invite = data.invitations[Number(button.dataset.revokeInvite)];
        button.onclick = async () => {
          if (
            !confirm(
              `Revoke the signup invitation for ${invite.game_name} in ${invite.unit_name}?`,
            )
          )
            return;
          button.disabled = true;
          try {
            await readJson(
              await postJson(
                `/api/units/${invite.unit_id}/roster/${invite.member_id}/invite`,
                { action: 'revoke' },
              ),
            );
            await invitations();
          } catch (error) {
            el('users-invite-status').textContent = error.message;
            button.disabled = false;
          }
        };
      });
    } catch (error) {
      if (request === inviteRequest) {
        el('users-invite-results').replaceChildren();
        el('users-invite-count').textContent = 'Unavailable';
        el('users-invite-status').textContent = error.message;
      }
    } finally {
      if (request === inviteRequest)
        el('users-invite-refresh').disabled = false;
    }
  }
  el('users-invite-refresh').onclick = invitations;
  el('users-invite-unit').onchange = invitations;
  let inviteSearchTimer;
  el('users-invite-search').oninput = () => {
    clearTimeout(inviteSearchTimer);
    inviteSearchTimer = setTimeout(invitations, 300);
  };
  el('users-invite-search').onsearch = invitations;
  el('users-invite-search').onkeydown = (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      clearTimeout(inviteSearchTimer);
      invitations();
    }
  };
  async function refresh() {
    el('users-refresh').disabled = true;
    el('users-restricted').hidden = true;
    try {
      await Promise.all([loadUsers(), invitations()]);
      el('users-new').disabled = false;
    } catch (error) {
      el('users-restricted').textContent = error.message;
      el('users-restricted').hidden = false;
    } finally {
      el('users-refresh').disabled = false;
    }
  }
  el('users-new').onclick = () => openUserEditor();
  el('users-refresh').onclick = refresh;
  el('users-logout').onclick = async () => {
    await postJson('/logout', {});
    location.href = '/login';
  };
  try {
    window.unitAccount = await readJson(await fetch('/api/me'));
    el('panel-backup-owner').hidden = !window.unitAccount.is_owner;
    el('panel-backup-download').onclick = (event) => {
      if (
        !confirm(
          'Download the complete panel-data backup? It contains private records, account password hashes and configuration credentials. Keep it in private storage. Game files and world saves are excluded.',
        )
      )
        event.preventDefault();
    };
    el('users-account-name').textContent = window.unitAccount.username;
    await refresh();
  } catch (error) {
    el('users-restricted').textContent = error.message;
    el('users-restricted').hidden = false;
  }
})();
