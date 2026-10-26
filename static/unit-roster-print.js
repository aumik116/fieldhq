// Print only the unit roster fields already visible to this account.
window.UnitRosterPrint = {
  print(detail, options) {
    const esc = escHtml,
      members = detail.roster.filter((member) => !member.archived),
      nodes = detail.structure;
    const children = new Map(),
      occupants = new Map(),
      direct = new Map();
    for (const node of nodes) {
      if (!children.has(node.parent_id)) children.set(node.parent_id, []);
      children.get(node.parent_id).push(node);
    }
    for (const member of members) {
      if (member.billet_id) occupants.set(member.billet_id, member);
      else if (member.placement_id) {
        if (!direct.has(member.placement_id))
          direct.set(member.placement_id, []);
        direct.get(member.placement_id).push(member);
      }
    }
    const extras = (member) =>
      [
        options.callsigns && member.effective_callsign
          ? `Callsign: ${member.effective_callsign}`
          : '',
        options.qualifications && member.certificates
          ? `Qualifications: ${member.certificates
              .split(';')
              .map(
                (name) =>
                  name +
                  ((member.expired_certificates || []).includes(name)
                    ? ' (expired)'
                    : ''),
              )
              .join(', ')}`
          : '',
        options.status ? member.status.toUpperCase() : '',
      ]
        .filter(Boolean)
        .map((value) => `<small>${esc(value)}</small>`)
        .join('');
    const row = (billet, member) =>
      `<tr><td>${esc(billet || '—')}</td><td>${esc(member?.rank_display || member?.rank || '—')}</td><td>${member ? esc(member.game_name) + extras(member) : '<em>Open</em>'}</td></tr>`;
    const table = (rows) =>
      `<table><thead><tr><th>Billet</th><th>Rank</th><th>Name</th></tr></thead><tbody>${rows}</tbody></table>`;
    function formation(node, ancestors = []) {
      const kids = children.get(node.id) || [],
        paths = [...ancestors, node.name];
      const rows =
        kids
          .filter((item) => item.kind === 'billet')
          .map((slot) => row(slot.name, occupants.get(slot.id)))
          .join('') +
        (direct.get(node.id) || []).map((member) => row('', member)).join('');
      return `<section class="formation" style="margin-left:${ancestors.length * 10}px"><h2>${esc(paths.join(' / '))}</h2>${rows ? table(rows) : ''}${kids
        .filter((item) => item.kind !== 'billet')
        .map((item) => formation(item, paths))
        .join('')}</section>`;
    }
    let body;
    if (options.layout === 'flat')
      body = table(
        members
          .map((member) =>
            row(member.assignment_path || member.billet_path || '', member),
          )
          .join(''),
      );
    else {
      body = (children.get(null) || [])
        .filter((node) => node.kind !== 'billet')
        .map((node) => formation(node))
        .join('');
      const unassigned = members.filter(
        (member) => !member.billet_id && !member.placement_id,
      );
      if (unassigned.length)
        body += `<h2>Unassigned members</h2>${table(unassigned.map((member) => row('', member)).join(''))}`;
    }
    document.getElementById('unit-roster-print-frame')?.remove();
    const frame = document.createElement('iframe');
    frame.id = 'unit-roster-print-frame';
    frame.title = 'Printable unit roster';
    frame.setAttribute('aria-hidden', 'true');
    frame.setAttribute('sandbox', 'allow-same-origin allow-modals');
    frame.style.cssText =
      'position:fixed;left:-10000px;top:0;width:1100px;height:800px;border:0';
    frame.onload = () => {
      frame.contentWindow.onafterprint = () => frame.remove();
      frame.contentWindow.focus();
      frame.contentWindow.print();
    };
    frame.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(detail.unit.name)} roster</title><style>@page{margin:15mm}body{font:11px Arial,sans-serif;color:#111}h1{font-size:22px}h2{font-size:14px;margin:18px 0 7px;break-after:avoid}table{width:100%;border-collapse:collapse;margin:6px 0 14px}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #ccc;padding:7px}th:first-child{width:30%}th:nth-child(2){width:12%}thead{display:table-header-group}tr{break-inside:avoid}small{display:block;font-size:10px;margin-top:4px}p{color:#444}</style></head><body><h1>${esc(detail.unit.name)} — Roster</h1><p>${members.length} current members · ${esc(new Date().toLocaleString())}</p>${body || '<p>No members or formations.</p>'}</body></html>`;
    document.body.append(frame);
  },
};
