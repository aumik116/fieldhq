// Formation and billet views. Mutations and permission checks stay with the unit workspace/API.
window.UnitStructure = {
  expanded: new Map(),
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
    if (!detail.can_staff) {
      for (const button of root.querySelectorAll('[data-structure-action]'))
        if (
          ['edit', 'copy', 'remove', 'add', 'billets', 'up', 'down'].includes(
            button.dataset.structureAction,
          )
        )
          button.remove();
    }
    return selected.id;
  },
  renderBoard(root, detail, state, actions) {
    const esc = escHtml,
      index = this.index(detail);
    const { children, occupants, direct, totals } = index;
    const match = (member) =>
      (!state.status || member.status === state.status) &&
      (!state.query ||
        [
          member.game_name,
          member.rank,
          member.rank_display,
          member.assignment_path,
          member.certificates,
          member.effective_callsign,
        ]
          .join(' ')
          .toLowerCase()
          .includes(state.query));
    const person = (member) =>
      `${detail.role === 'member' ? esc(member.game_name) : `<button type="button" class="member-record-link" data-board-action="record" data-member="${member.id}">${esc(member.game_name)}</button>`}${member.effective_callsign ? `<small>${esc(member.effective_callsign)}</small>` : ''}${member.status !== 'active' ? `<small>${member.status === 'loa' ? 'LOA' : 'Reserve'}</small>` : ''}`;
    const counts = (node) => {
      const value = totals.get(node.id);
      return `${value.members} member${value.members === 1 ? '' : 's'}${value.slots ? ` · ${value.filled}/${value.slots} billets filled${value.slots > value.filled ? ` · ${value.slots - value.filled} open` : ''}` : ''}`;
    };
    const expanded = this.expanded,
      key = (id) => `${detail.unit.id}:${id}`;
    function parents(node) {
      const path = [];
      let parent = index.byId.get(node.parent_id);
      while (parent) {
        path.unshift(parent);
        parent = index.byId.get(parent.parent_id);
      }
      return path;
    }
    function formation(node, depth = 0) {
      const childNodes = children.get(node.id) || [];
      const rows =
        childNodes
          .filter((n) => n.kind === 'billet')
          .filter((slot) => {
            const member = occupants.get(slot.id);
            return member
              ? match(member)
              : !state.status &&
                  (!state.query ||
                    [node.name, slot.name]
                      .join(' ')
                      .toLowerCase()
                      .includes(state.query));
          })
          .map((slot) => {
            const member = occupants.get(slot.id);
            return `<tr class="${member ? '' : 'billet-vacant'}"><td>${esc(slot.name)}</td><td title="${member ? esc(member.rank) : ''}">${member ? esc(member.rank_display || member.rank || '—') : '—'}</td><td>${member ? person(member) : detail.can_edit ? `<button type="button" class="member-record-link billet-open" data-board-action="assign" data-node="${slot.id}" aria-label="Assign ${esc(slot.name)}">— Open —</button>` : '<span class="billet-open">— Open —</span>'}</td></tr>`;
          })
          .join('') +
        (direct.get(node.id) || [])
          .filter(match)
          .map(
            (member) =>
              `<tr><td class="feature-note">—</td><td title="${esc(member.rank)}">${esc(member.rank_display || member.rank || '—')}</td><td>${person(member)}</td></tr>`,
          )
          .join('');
      const nested = childNodes
        .filter((n) => n.kind !== 'billet')
        .map((child) => formation(child, depth + 1))
        .join('');
      if ((state.query || state.status) && !rows && !nested) return '';
      const ancestry = parents(node);
      const heading = `<summary class="roster-formation-heading"><span class="roster-disclosure" aria-hidden="true">▸</span><span class="roster-formation-identity"><strong>${esc(node.name)}</strong><span>${esc(counts(node))}</span>${ancestry.length ? `<span class="formation-breadcrumb" aria-label="Parent formations">${ancestry.map((parent) => `<button type="button" data-board-action="parent" data-node="${parent.id}">${esc(parent.name)}</button>`).join('<span aria-hidden="true"> / </span>')}</span>` : ''}</span></summary>`;
      const table = rows
        ? `<div class="billet-table roster-formation-table"><table><thead><tr><th>Billet</th><th>Rank</th><th>Name</th></tr></thead><tbody>${rows}</tbody></table></div>`
        : !nested
          ? '<p class="roster-formation-empty">No members or billets assigned.</p>'
          : '';
      const open =
        state.query ||
        state.status ||
        (expanded.has(key(node.id)) ? expanded.get(key(node.id)) : depth < 2);
      return `<details class="roster-formation" id="roster-formation-${node.id}" data-formation="${node.id}" ${open ? 'open' : ''}>${heading}<div class="roster-formation-content">${table}${nested}</div></details>`;
    }
    const groups = state.group
      ? index.nodes.filter((n) => n.id === state.group)
      : children.get(null) || [];
    root.innerHTML = `<div class="unit-toolbar roster-disclosure-controls"><button type="button" data-board-action="expand">Expand all</button><button type="button" data-board-action="collapse">Collapse all</button></div><div class="roster-formations">${groups.map((node) => formation(node)).join('') || '<p class="unit-empty">No matching formations. Use All members for the flat roster.</p>'}</div>`;
    root.querySelectorAll('[data-formation]').forEach((region) => {
      region.ontoggle = () => {
        if (!state.query && !state.status)
          expanded.set(key(Number(region.dataset.formation)), region.open);
      };
    });
    root.onclick = (event) => {
      const button = event.target.closest('[data-board-action]');
      if (!button) return;
      const member = Number(button.dataset.member),
        node = Number(button.dataset.node);
      switch (button.dataset.boardAction) {
        case 'expand':
        case 'collapse':
          root.querySelectorAll('[data-formation]').forEach((region) => {
            region.open = button.dataset.boardAction === 'expand';
            expanded.set(key(Number(region.dataset.formation)), region.open);
          });
          break;
        case 'parent': {
          event.preventDefault();
          event.stopPropagation();
          const target = root.querySelector(`#roster-formation-${node}`);
          if (target) {
            let region = target;
            while (region && region !== root) {
              if (region.tagName === 'DETAILS') region.open = true;
              region = region.parentElement;
            }
            const heading = target.querySelector('summary');
            heading.focus();
            heading.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
          }
          break;
        }
        case 'record':
          actions.record(member);
          break;
        case 'assign':
          actions.assign(node);
          break;
      }
    };
  },
};
