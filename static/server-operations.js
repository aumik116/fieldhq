// One accessible status area for server controls and existing software workers.
(() => {
  const operations = new Map(),
    dismissed = new Map();
  let region = null;
  function render() {
    if (!region) {
      region = document.createElement('section');
      region.id = 'server-operation-feedback';
      region.className = 'unit-block';
      region.setAttribute('aria-label', 'Server action results');
      document.querySelector('main').prepend(region);
    }
    region.replaceChildren();
    for (const [key, operation] of operations) {
      const card = document.createElement('article');
      card.className = 'operation-result';
      card.dataset.state = operation.state;
      const title = document.createElement('strong');
      title.textContent = operation.serverName + ' · ' + operation.action;
      const status = document.createElement('p');
      status.setAttribute('role', 'status');
      status.textContent =
        (operation.state === 'running'
          ? 'In progress'
          : operation.state === 'success'
            ? 'Completed'
            : operation.state === 'unknown'
              ? 'Unconfirmed'
              : 'Failed') +
        ' · ' +
        operation.message;
      card.append(title, status);
      if (operation.state === 'running') {
        const progress = document.createElement('progress');
        progress.setAttribute('aria-label', 'Operation in progress');
        card.append(progress);
      } else {
        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.textContent = 'Dismiss';
        dismiss.onclick = () => {
          dismissed.set(
            key,
            operation.started + ':' + operation.state + ':' + operation.message,
          );
          operations.delete(key);
          render();
        };
        card.append(dismiss);
      }
      if (operation.started) {
        const time = document.createElement('small');
        time.textContent =
          'Started ' + new Date(operation.started).toLocaleString();
        card.append(time);
      }
      if (
        operation.state === 'failed' &&
        ['start', 'stop', 'restart'].includes(operation.action)
      ) {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.textContent = 'Retry';
        retry.onclick = async () => {
          if (
            !(await PanelUI.confirm(
              `Retry ${operation.action} on ${operation.serverName}? Stop/restart disconnects players.`,
            ))
          )
            return;
          try {
            await controlServer(
              operation.action,
              operation.serverId,
              operation.serverName,
            );
          } catch (_) {}
        };
        card.append(retry);
      }
      if (operation.state === 'unknown') {
        const check = document.createElement('button');
        check.type = 'button';
        check.textContent = 'Check server status';
        check.onclick = () => {
          const refresh = document.getElementById('overview-refresh');
          if (refresh) refresh.click();
          else if (typeof fetchStatus === 'function') fetchStatus();
        };
        card.append(check);
      }
      if (operation.state === 'failed' || operation.state === 'unknown') {
        const copy = document.createElement('button');
        copy.type = 'button';
        copy.textContent = 'Copy error';
        copy.onclick = async () => {
          try {
            await navigator.clipboard.writeText(
              operation.serverName + ': ' + operation.message,
            );
            copy.textContent = 'Copied';
          } catch (_) {
            copy.textContent = 'Select the error text to copy';
          }
        };
        card.append(copy);
      }
      region.append(card);
    }
    region.hidden = !operations.size;
  }
  document.addEventListener('server-operation', (event) => {
    const operation = event.detail,
      key = operation.serverId + ':' + operation.action;
    if (
      dismissed.get(key) ===
      operation.started + ':' + operation.state + ':' + operation.message
    )
      return;
    const previous = operations.get(key);
    if (
      previous &&
      previous.state === operation.state &&
      previous.message === operation.message &&
      previous.started === operation.started
    )
      return;
    operations.set(key, operation);
    if (operations.size > 6) {
      const old = [...operations].find(
        ([id, row]) => id !== key && row.state !== 'running',
      );
      if (old) operations.delete(old[0]);
    }
    render();
  });
})();
