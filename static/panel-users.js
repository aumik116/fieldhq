// Panel-wide account management, independent of the selected server or unit.
(async () => {
  const el = (id) => document.getElementById(id);
  async function refresh() {
    el('users-refresh').disabled = true;
    el('users-restricted').hidden = true;
    try {
      await loadUsers();
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
