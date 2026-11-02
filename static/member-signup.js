(() => {
  const el = (id) => document.getElementById(id);
  const token = location.hash.slice(1);
  // Fragment tokens stay out of HTTP requests; retain it so refresh still works.
  const form = el('signup-form'),
    error = el('signup-error'),
    button = el('signup-submit');
  let kind = 'signup',
    busy = false;
  const mode = () => (kind === 'reset' ? 'reset' : el('signup-mode').value);
  async function send(path, data) {
    const response = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': document.querySelector('[name="csrf-token"]').content,
      },
      body: JSON.stringify({ ...data, token }),
    });
    let result;
    try {
      result = await response.json();
    } catch (_) {
      throw new Error('The server could not complete this request. Try again.');
    }
    if (!response.ok)
      throw new Error(result.error || 'This request could not be completed.');
    return result;
  }
  function fields() {
    const existing = mode() === 'existing',
      reset = mode() === 'reset';
    el('signup-mode-field').hidden = reset;
    el('signup-username-field').hidden = reset;
    el('signup-username').disabled = reset;
    el('signup-confirm-field').hidden = existing;
    el('signup-confirm').disabled = existing;
    el('signup-password').minLength = existing ? 1 : 10;
    el('signup-password').autocomplete = existing
      ? 'current-password'
      : 'new-password';
    el('signup-password-label').textContent = existing
      ? 'Your existing password'
      : 'Choose a new password';
    el('signup-password-hint').hidden = existing;
    button.textContent = existing
      ? 'Sign in and accept invitation'
      : reset
        ? 'Set password'
        : 'Create account';
  }
  el('signup-mode').onchange = () => {
    el('signup-password').value = '';
    el('signup-confirm').value = '';
    fields();
  };
  form.onsubmit = async (event) => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    error.hidden = true;
    busy = true;
    button.disabled = true;
    try {
      const data = await send('/api/signup/accept', {
        mode: mode(),
        username: el('signup-username').value.trim(),
        password: el('signup-password').value,
        confirm_password: el('signup-confirm').value,
      });
      location.replace(data.redirect);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      busy = false;
      button.disabled = false;
    }
  };
  send('/api/signup/info', {})
    .then((data) => {
      kind = data.kind;
      el('signup-title').textContent =
        kind === 'reset' ? 'Reset your password' : 'Join ' + data.unit;
      el('signup-context').textContent =
        `${data.member} · ${data.unit}. ${kind === 'reset' ? 'Set your password to continue. Existing sessions will be signed out.' : 'This links your login to your existing roster record with Member access.'}`;
      if (data.icon) {
        el('signup-icon').src = data.icon;
        el('signup-icon').hidden = false;
      }
      fields();
      form.hidden = false;
    })
    .catch((err) => {
      el('signup-context').textContent = '';
      error.textContent = err.message;
      error.hidden = false;
    });
})();
