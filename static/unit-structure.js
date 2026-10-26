// Formation and billet views. Mutations and permission checks stay with the unit workspace/API.
window.UnitStructure = {
  index(detail) {
    const nodes = detail.structure || [],
      byId = new Map(nodes.map((n) => [n.id, n])),
      children = new Map(),
      occupants = new Map(),
      direct = new Map();
    for (const node of nodes) {
      if (!children.has(node.parent_id)) children.set(node.parent_id, []);
      children.get(node.parent_id).push(node);
    }
    const active = detail.roster.filter((m) => !m.archived);
    for (const member of active) {
      if (member.billet_id) occupants.set(member.billet_id, member);
      else if (member.placement_id) {
        if (!direct.has(member.placement_id))
          direct.set(member.placement_id, []);
        direct.get(member.placement_id).push(member);
      }
    }
    const totals = new Map();
    function count(node) {
      if (totals.has(node.id)) return totals.get(node.id);
      const own = direct.get(node.id) || [],
        value = {
          slots: node.kind === 'billet' ? 1 : 0,
          filled: occupants.has(node.id) ? 1 : 0,
          direct: own.length,
          members: own.length + (occupants.has(node.id) ? 1 : 0),
        };
      for (const child of children.get(node.id) || []) {
        const nested = count(child);
        for (const key of Object.keys(value)) value[key] += nested[key];
      }
      totals.set(node.id, value);
      return value;
    }
    nodes.filter((n) => n.parent_id === null).forEach(count);
    return {
      nodes,
      byId,
      children,
      occupants,
      direct,
      totals,
      unassigned: active.filter((m) => !m.billet_id && !m.placement_id),
    };
  },
  summary(value) {
    return `${value.members} members · ${value.filled}/${value.slots} billets filled${value.slots > value.filled ? ' · ' + (value.slots - value.filled) + ' open' : ''}${value.direct ? ' · ' + value.direct + ' without billets' : ''}`;
  },
  renderBuilder(root, detail, state, actions) {
    const esc = escHtml,
      index = this.index(detail),
      { nodes, children, occupants, direct, totals } = index;
    const selected = index.byId.get(state.selected) || nodes[0];
    if (!selected) {
      root.innerHTML =
        '<p class="unit-empty">Start with a formation group, such as 1st Platoon. Add named billets, smaller formations or members directly.</p>';
      return null;
    }
    const matching = (node) =>
      !state.query ||
      node.name.toLowerCase().includes(state.query) ||
      (children.get(node.id) || []).some(matching);
    const tree = (parent) =>
      (children.get(parent) || [])
        .filter(matching)
        .map(
          (node) =>
            `<div class="formation-nav-branch"><button type="button" data-structure-action="select" data-node="${node.id}" aria-current="${node.id === selected.id ? 'page' : 'false'}"><span>${esc(node.name)}</span><small>${node.kind === 'billet' ? 'Billet' : node.kind === 'group' ? 'Group' : 'Formation'}</small></button>${tree(node.id)}</div>`,
        )
        .join('');
    const childNodes = children.get(selected.id) || [],
      summary = totals.get(selected.id),
      assigned = occupants.get(selected.id),
      members = direct.get(selected.id) || [];
    const row = (node, i) => {
      const person = occupants.get(node.id);
      return `<tr><td><button type="button" class="member-record-link" data-structure-action="select" data-node="${node.id}">${esc(node.name)}</button><small>${node.kind === 'billet' ? 'Named billet' : this.summary(totals.get(node.id))}</small></td><td>${node.kind === 'billet' ? (person ? `<button type="button" class="member-record-link" data-structure-action="record" data-member="${person.id}">${esc([person.rank, person.game_name].filter(Boolean).join(' '))}</button>` : '<span class="billet-open">Open</span>') : '—'}</td><td class="formation-actions">${node.kind === 'billet' ? `<button type="button" data-structure-action="assign" data-node="${node.id}">${person ? 'Change' : 'Assign'}</button>` : `<button type="button" data-structure-action="place" data-node="${node.id}">Add members</button>`}<button type="button" data-structure-action="edit" data-node="${node.id}">Edit</button><button type="button" data-structure-action="up" data-node="${node.id}" ${i === 0 ? 'disabled' : ''} aria-label="Move ${esc(node.name)} up">↑</button><button type="button" data-structure-action="down" data-node="${node.id}" ${i === childNodes.length - 1 ? 'disabled' : ''} aria-label="Move ${esc(node.name)} down">↓</button></td></tr>`;
    };
    root.innerHTML = `<div class="formation-builder"><nav class="formation-navigator" aria-label="Structure items">${tree(null) || '<p>No matching items.</p>'}</nav><section class="unit-block formation-inspector"><div class="formation-heading"><div><small>${esc(selected.kind === 'billet' ? 'Named billet' : 'Formation layout')}</small><h3>${esc(selected.name)}</h3><p>${esc(this.summary(summary))}</p></div><div class="formation-actions"><button type="button" data-structure-action="edit" data-node="${selected.id}">Edit / move</button><button type="button" data-structure-action="copy" data-node="${selected.id}">Copy empty layout</button><button type="button" data-structure-action="remove" data-node="${selected.id}">Remove</button></div></div>${selected.kind === 'billet' ? `<p>${assigned ? esc(assigned.game_name) : 'This billet is open.'}</p><button type="button" data-structure-action="assign" data-node="${selected.id}">${assigned ? 'Change assignment' : 'Assign member'}</button>` : `<div class="unit-toolbar"><button type="button" data-structure-action="add" data-node="${selected.id}">Add formation</button><button type="button" data-structure-action="billets" data-node="${selected.id}">Add billets</button><button type="button" data-structure-action="place" data-node="${selected.id}">Assign members without billets</button></div><div class="unit-table"><table><thead><tr><th>Formation / billet</th><th>Occupant</th><th>Actions</th></tr></thead><tbody>${childNodes.map(row).join('') || '<tr><td colspan="3">No named billets or smaller formations yet.</td></tr>'}</tbody></table></div><section class="formation-direct"><h4>Members assigned directly · ${members.length}</h4><p class="feature-note">These members belong here without occupying a named billet.</p>${members.map((m) => `<p><button type="button" class="member-record-link" data-structure-action="record" data-member="${m.id}">${esc([m.rank, m.game_name].filter(Boolean).join(' '))}</button> <button type="button" data-structure-action="move-member" data-member="${m.id}">Move / unassign</button></p>`).join('') || '<p>No members assigned directly.</p>'}</section>`}</section></div>`;
    root.onclick = (event) => {
      const button = event.target.closest('[data-structure-action]');
      if (!button || button.disabled) return;
      const node = index.byId.get(Number(button.dataset.node)),
        member = Number(button.dataset.member);
      switch (button.dataset.structureAction) {
        case 'select':
          actions.select(node.id);
          break;
        case 'edit':
          actions.edit(node);
          break;
        case 'copy':
          actions.copy(node);
          break;
        case 'remove':
          actions.remove(node);
          break;
        case 'add':
          actions.add(node.id);
          break;
        case 'billets':
          actions.billets(node);
          break;
        case 'place':
          actions.place(node.id);
          break;
        case 'assign':
          actions.assign(node.id);
          break;
        case 'up':
        case 'down':
          actions.order(node.id, button.dataset.structureAction);
          break;
        case 'record':
          actions.record(member);
          break;
        case 'move-member':
          actions.moveMember(member);
          break;
      }
    };
    return selected.id;
  },
  renderBoard(root, detail, state, actions) {
    const esc = escHtml,
      index = this.index(detail),
      { children, occupants, direct, totals } = index;
    const match = (member) =>
      (!state.status || member.status === state.status) &&
      (!state.query ||
        [
          member.game_name,
          member.rank,
          member.assignment_path,
          member.certificates,
        ]
          .join(' ')
          .toLowerCase()
          .includes(state.query));
    const selected = detail.roster.find(
      (m) => m.id === state.member && !m.archived,
    );
    const person = (m) =>
      `<button type="button" class="member-record-link" data-board-action="record" data-member="${m.id}">${esc([m.rank, m.game_name].filter(Boolean).join(' '))}</button>${m.status !== 'active' ? `<small>${m.status === 'loa' ? 'LOA' : 'Reserve'}</small>` : ''}`;
    function formation(node) {
      const childNodes = children.get(node.id) || [],
        directMembers = (direct.get(node.id) || []).filter(match),
        slots = childNodes.filter((n) => n.kind === 'billet');
      const rows = slots
        .filter((slot) => {
          const m = occupants.get(slot.id);
          return m
            ? match(m)
            : !state.status &&
                (!state.query || slot.name.toLowerCase().includes(state.query));
        })
        .map((slot) => {
          const m = occupants.get(slot.id);
          return `<tr class="${m ? '' : 'billet-vacant'}"><td>${esc(slot.name)}</td><td>${m ? person(m) : '<span class="billet-open">Open</span>'}</td><td>${detail.can_edit ? `<button type="button" data-board-action="assign" data-node="${slot.id}">${selected ? 'Assign selected' : m ? 'Change' : 'Assign'}</button>` : ''}</td></tr>`;
        })
        .join('');
      const nested = childNodes
        .filter((n) => n.kind !== 'billet')
        .map(formation)
        .join('');
      if (
        (state.query || state.status) &&
        !rows &&
        !directMembers.length &&
        !nested
      )
        return '';
      return `<section class="formation-board-section"><div class="formation-heading"><div><h3>${esc(node.name)}</h3><small>${esc(UnitStructure.summary(totals.get(node.id)))}</small></div><div class="formation-actions">${detail.can_edit ? `<button type="button" data-board-action="place" data-node="${node.id}">Add members</button>` : ''}${detail.can_staff ? `<button type="button" data-board-action="build" data-node="${node.id}">Edit layout</button>` : ''}</div></div>${rows ? `<div class="billet-table"><table><thead><tr><th>Named billet</th><th>Member</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}${directMembers.length ? `<div class="formation-direct"><h4>Members without named billets · ${directMembers.length}</h4>${directMembers.map((m) => `<div class="formation-member-row">${person(m)}${detail.can_edit ? `<button type="button" data-board-action="move" data-member="${m.id}">Move / unassign</button>` : ''}</div>`).join('')}</div>` : ''}${nested}</section>`;
    }
    const groups = state.group
      ? index.nodes.filter((n) => n.id === state.group)
      : children.get(null) || [];
    root.innerHTML = `<div class="formation-board${detail.can_edit ? '' : ' formation-board-readonly'}">${
      detail.can_edit
        ? `<aside class="unit-block formation-pool"><h3>Unassigned · ${index.unassigned.length}</h3><p class="feature-note">Choose a member for a named billet, or place them directly in a formation.</p>${selected ? `<p class="formation-selection">Selected: <strong>${esc(selected.game_name)}</strong> <button type="button" data-board-action="clear">Clear</button></p>` : ''}${
            index.unassigned
              .filter(match)
              .map(
                (m) =>
                  `<article><strong>${esc(m.game_name)}</strong><small>${esc(m.rank || 'No rank')}</small><div class="formation-actions"><button type="button" data-board-action="select" data-member="${m.id}">Select for billet</button><button type="button" data-board-action="move" data-member="${m.id}">Place</button>${!m.panel_user_id ? `<button type="button" data-board-action="login" data-member="${m.id}">Create login</button>` : ''}</div></article>`,
              )
              .join('') || '<p>No matching unassigned members.</p>'
          }</aside>`
        : ''
    }<div class="formation-board-groups">${groups.map(formation).join('') || '<p class="unit-empty">No matching formations. The All members roster works without a structure.</p>'}</div></div>`;
    root.onclick = (event) => {
      const b = event.target.closest('[data-board-action]');
      if (!b) return;
      const member = Number(b.dataset.member),
        node = Number(b.dataset.node);
      switch (b.dataset.boardAction) {
        case 'record':
          actions.record(member);
          break;
        case 'assign':
          actions.assign(node, selected?.id);
          break;
        case 'place':
          actions.place(node, selected?.id);
          break;
        case 'move':
          actions.place(null, member);
          break;
        case 'select':
          actions.select(member);
          break;
        case 'clear':
          actions.select(null);
          break;
        case 'build':
          actions.build(node);
          break;
        case 'login':
          actions.login(member);
          break;
      }
    };
  },
};
