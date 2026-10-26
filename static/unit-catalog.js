// Focused rank and qualification setup. The existing catalog API remains authoritative.
window.UnitCatalog = (() => {
  const esc = escHtml;
  let view = 'ranks',
    selected = null,
    unit = null;
  const definitions = (catalog) =>
    (catalog.certificates || []).map((name) => ({
      name,
      abbreviation: '',
      description: '',
      archived: false,
      ...(catalog.qualification_details || []).find(
        (item) => item.name === name,
      ),
    }));
  const usedRanks = (detail, structure, rank) =>
    detail.roster.filter(
      (member) =>
        member.rank_track === structure && (!rank || member.rank === rank),
    );
  function render(root, detail, actions) {
    if (unit !== detail.unit.id) {
      unit = detail.unit.id;
      selected = null;
      view = 'ranks';
    }
    const catalog = detail.unit.catalog,
      structures = catalog.rank_structures || [],
      quals = definitions(catalog);
    selected = structures.some((item) => item.name === selected)
      ? selected
      : structures[0]?.name;
    const structure = structures.find((item) => item.name === selected);
    root.innerHTML = `<div class="section-tabs" role="group" aria-label="Rule setup"><button type="button" data-catalog-view="ranks" aria-pressed="${view === 'ranks'}">Rank structures</button><button type="button" data-catalog-view="qualifications" aria-pressed="${view === 'qualifications'}">Qualifications</button></div><p class="feature-note">1. Create qualifications → 2. Order ranks → 3. Set requirements → 4. Preview eligibility → Save. Promotions always require staff approval.</p>${
      view === 'ranks'
        ? `<div class="unit-toolbar">${structures.map((item) => `<button type="button" data-rank-view="${esc(item.name)}" aria-pressed="${item.name === selected}">${esc(item.name)}</button>`).join('')}${detail.can_staff ? '<button type="button" data-catalog-action="new-rank">New rank structure</button>' : ''}</div>${
            structure
              ? `<section class="unit-block"><div class="formation-heading"><h3>${esc(structure.name)}</h3><div class="formation-actions">${detail.can_staff ? `<button type="button" data-catalog-action="edit-rank">Edit ranks & requirements</button><button type="button" data-catalog-action="copy-rank">Duplicate structure</button>${!usedRanks(detail, structure.name).length ? '<button type="button" data-catalog-action="remove-rank">Remove structure</button>' : ''}` : ''}</div></div><ol class="rank-ladder">${
                  structure.ranks
                    .map((rank) => {
                      const previous = structure.ranks.filter(
                        (item) => item.next_rank === rank.name,
                      );
                      return `<li><strong>${esc(rank.name)}</strong>${rank.abbreviation ? ` <small>(${esc(rank.abbreviation)})</small>` : ''}${rank.paygrade ? ` <small>${esc(rank.paygrade)}</small>` : ''}<p>${previous.length ? `${esc(previous.map((item) => item.name).join(' / '))} → ${esc(rank.name)}: ${rank.days} days since last promotion${rank.certificates.length ? ' + ' + esc(rank.certificates.join(', ')) : ' · No qualification requirements'}` : 'Entry rank or manually assigned rank.'}</p><small>${rank.next_rank ? 'Next: ' + esc(rank.next_rank) : 'End of promotion path'}</small></li>`;
                    })
                    .join('') ||
                  '<li>No ranks yet. Open the editor to add the first rank.</li>'
                }</ol></section>`
              : '<p class="unit-empty">Create a structure such as Marine, Medical or Officer. Each has its own promotion rules.</p>'
          }`
        : `<div class="unit-toolbar"><input id="qualification-catalog-search" type="search" aria-label="Search qualifications" placeholder="Search qualification or abbreviation">${detail.can_staff ? '<button type="button" data-catalog-action="new-qualification">Add qualification</button>' : ''}</div><div id="qualification-catalog-list">${
            quals
              .map((qual) => {
                const holders = detail.roster.filter((member) =>
                  member.certificates.split(';').includes(qual.name),
                );
                const requirements = structures.flatMap((item) =>
                  item.ranks
                    .filter((rank) => rank.certificates.includes(qual.name))
                    .map((rank) => `${item.name} · ${rank.name}`),
                );
                return `<article class="unit-block qualification-definition" data-qualification-name="${esc(qual.name)}"><div class="formation-heading"><h3>${esc(qual.name)}${qual.abbreviation ? ' · ' + esc(qual.abbreviation) : ''}${qual.archived ? ' · Archived' : ''}</h3>${detail.can_staff ? `<button type="button" data-edit-qualification="${esc(qual.name)}">Edit details / ${qual.archived ? 'restore' : 'archive'}</button>` : ''}</div><p>${esc(qual.description || 'No description.')}</p><p class="feature-note">${holders.length} award records · ${requirements.length} rank requirements</p><details><summary>Who holds it / where it is required</summary><p>${esc(holders.map((member) => member.game_name + (member.archived ? ' (former)' : '')).join(', ') || 'No award records.')}</p><p>Required for: ${esc(requirements.join(', ') || 'No ranks.')}</p></details></article>`;
              })
              .join('') ||
            '<p class="unit-empty">Add qualifications first so you can select them in promotion requirements.</p>'
          }</div>`
    }`;
    root.querySelectorAll('[data-catalog-view]').forEach(
      (button) =>
        (button.onclick = () => {
          view = button.dataset.catalogView;
          render(root, detail, actions);
          root.querySelector(`[data-catalog-view="${view}"]`).focus();
        }),
    );
    root.querySelectorAll('[data-rank-view]').forEach(
      (button) =>
        (button.onclick = () => {
          selected = button.dataset.rankView;
          render(root, detail, actions);
          [...root.querySelectorAll('[data-rank-view]')]
            .find((item) => item.dataset.rankView === selected)
            ?.focus();
        }),
    );
    root
      .querySelectorAll('[data-edit-qualification]')
      .forEach(
        (button) =>
          (button.onclick = () =>
            actions.qualification(
              quals.find(
                (item) => item.name === button.dataset.editQualification,
              ),
            )),
      );
    root.querySelectorAll('[data-catalog-action]').forEach(
      (button) =>
        (button.onclick = () => {
          switch (button.dataset.catalogAction) {
            case 'new-rank':
              actions.structure();
              break;
            case 'edit-rank':
              actions.structure(structure);
              break;
            case 'copy-rank':
              actions.structure(structure, true);
              break;
            case 'new-qualification':
              actions.qualification();
              break;
            case 'remove-rank':
              actions.remove(structure);
              break;
          }
        }),
    );
    const search = root.querySelector('#qualification-catalog-search');
    if (search)
      search.oninput = () =>
        root
          .querySelectorAll('[data-qualification-name]')
          .forEach(
            (row) =>
              (row.hidden = !row.textContent
                .toLowerCase()
                .includes(search.value.trim().toLowerCase())),
          );
  }
  function qualification(options, existing = null) {
    const { detail, open, form, write, unitId, baseline } = options,
      catalog = detail.unit.catalog;
    open(
      existing ? 'Edit qualification' : 'Add qualification',
      `<label class="unit-field">Name<input name="qualification_name" required maxlength="80" ${existing ? 'readonly' : ''} value="${esc(existing?.name || '')}"></label><label class="unit-field">Abbreviation (optional)<input name="qualification_abbreviation" maxlength="20" value="${esc(existing?.abbreviation || '')}"></label><label class="unit-field">Description<textarea name="qualification_description" maxlength="1000" rows="4">${esc(existing?.description || '')}</textarea></label>${existing ? `<label><input type="checkbox" name="qualification_archived" ${existing.archived ? 'checked' : ''}> Archive this qualification</label><p class="feature-note">Archiving prevents new awards. Existing awards and promotion requirements remain valid. Uncheck to restore it. Existing names are kept stable; change the abbreviation or description instead.</p>` : ''}`,
      async () => {
        const data = new FormData(form),
          name = String(data.get('qualification_name')).trim();
        const item = {
          name,
          abbreviation: String(data.get('qualification_abbreviation')).trim(),
          description: String(data.get('qualification_description')).trim(),
          archived: data.has('qualification_archived'),
        };
        const details = definitions(catalog);
        if (existing)
          details[details.findIndex((qual) => qual.name === existing.name)] =
            item;
        else details.push(item);
        await write(`/api/units/${unitId}/catalog`, {
          catalog: {
            ...catalog,
            certificates: details.map((qual) => qual.name),
            qualification_details: details,
          },
          revision: detail.unit.revision,
        });
      },
    );
    if (existing) {
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'member-delete-button';
      remove.textContent = 'Delete qualification…';
      remove.onclick = async () => {
        remove.disabled = true;
        try {
          const result = await write(
            `/api/units/${unitId}/qualifications/delete`,
            { name: existing.name, revision: detail.unit.revision },
          );
          if (!remove.isConnected || !UnitUX.canLeave()) return;
          const impact = result.impact;
          open(
            'Delete ' + existing.name,
            `<p>This permanently removes the qualification and its active awards. Historical change records remain.</p><ul><li>${impact.members.length} member awards, including former members</li><li>${impact.ranks.length} promotion requirements</li><li>${impact.reading_audiences} required-reading audiences</li><li>${impact.references.length} document reference labels</li></ul>${impact.ranks.length ? '<p class="unit-warn">Removing promotion requirements can make members eligible sooner. Promotions still require staff approval.</p>' : ''}<details><summary>Show affected members and rules</summary><p>${esc(impact.members.map((member) => member.name + (member.former ? ' (former)' : '')).join(', ') || 'No member awards.')}</p><p>${esc(impact.ranks.map((rank) => rank.structure + ' · ' + rank.rank).join(', ') || 'No rank requirements.')}</p><p>${esc(impact.references.join(', ') || 'No document references.')}</p></details><label class="unit-field">Type ${esc(existing.name)} to confirm<input name="qualification_delete_name" required autocomplete="off"></label><p class="feature-note">Archive instead if you want to retain active awards and requirements.</p>`,
            async () => {
              await write(`/api/units/${unitId}/qualifications/delete`, {
                name: existing.name,
                revision: detail.unit.revision,
                confirmed: true,
                confirm_name: form.elements.qualification_delete_name.value,
              });
            },
          );
          form.querySelector('[type="submit"]').textContent =
            'Delete qualification';
        } catch (error) {
          const alert = form.querySelector('[role="alert"]');
          if (alert) alert.textContent = error.message;
        } finally {
          remove.disabled = false;
        }
      };
      form.querySelector('#unit-dialog-body').append(remove);
    }
    baseline();
  }
  function structure(options, existing = null, duplicate = false) {
    const { detail, open, form, write, unitId, baseline } = options,
      catalog = detail.unit.catalog,
      quals = definitions(catalog);
    const ranks = existing?.ranks || [],
      linear = ranks.every(
        (rank, i) => rank.next_rank === (ranks[i + 1]?.name || ''),
      );
    const locked =
      existing && !duplicate && usedRanks(detail, existing.name).length > 0;
    open(
      duplicate
        ? 'Duplicate rank structure'
        : existing
          ? 'Edit rank structure'
          : 'Create rank structure',
      `<label class="unit-field">Structure name<input name="setup_structure_name" required maxlength="80" value="${esc(existing ? existing.name + (duplicate ? ' copy' : '') : '')}" ${locked ? 'readonly' : ''}></label><p class="feature-note">Lowest rank first. Move ranks up/down to set the promotion order. A rank’s requirements apply when entering that rank. Example: Pfc → Cpl needs 45 days since the last promotion plus Leadership.</p>${!linear ? '<label class="unit-field">Existing promotion paths<select name="setup_progression"><option value="custom">Keep existing custom links</option><option value="ordered">Use displayed rank order</option></select></label><p class="feature-note">This structure uses custom links. They remain unchanged unless you choose displayed rank order.</p>' : '<input type="hidden" name="setup_progression" value="ordered">'}<div id="setup-rank-list"></div><button type="button" id="setup-add-rank">Add rank</button><section class="unit-block"><h3>Preview eligibility</h3><p class="feature-note">Use the unsaved rules below. This preview changes no roster records.</p><label class="unit-field">Member<select id="setup-preview-member" name="setup_preview_member"><option value="">Choose member</option>${detail.roster
        .filter((member) => !member.archived)
        .map(
          (member) =>
            `<option value="${member.id}">${esc(member.game_name)} · ${esc(member.rank || 'No rank')}</option>`,
        )
        .join(
          '',
        )}</select></label><label class="unit-field">Current rank for this preview<select id="setup-preview-rank" name="setup_preview_rank"></select></label><label class="unit-field">Last promotion date<input type="date" id="setup-preview-date" name="setup_preview_date"></label><button type="button" id="setup-preview">Explain eligibility</button><div id="setup-preview-result" role="status"></div></section>`,
      async () => {
        const next = collect();
        await write(`/api/units/${unitId}/catalog`, {
          catalog: next,
          revision: detail.unit.revision,
        });
        selected = form.elements.setup_structure_name.value.trim();
        view = 'ranks';
      },
    );
    const list = form.querySelector('#setup-rank-list');
    let nextId = 0,
      request = 0;
    function addRank(rank = {}) {
      const row = document.createElement('section');
      row.className = 'unit-block setup-rank';
      row.dataset.original = rank.name || '';
      row.dataset.next = rank.next_rank || '';
      const held =
        existing &&
        !duplicate &&
        usedRanks(detail, existing.name, rank.name).length > 0 &&
        !!rank.name;
      const rowId = nextId++;
      row.innerHTML = `<div class="formation-heading"><strong data-rank-heading>Rank</strong><div class="formation-actions"><button type="button" data-rank-up aria-label="Move rank up">↑</button><button type="button" data-rank-down aria-label="Move rank down">↓</button><button type="button" data-rank-remove ${held ? 'disabled' : ''}>Remove</button></div></div><label class="unit-field">Rank name<input name="setup_rank_name" required maxlength="80" value="${esc(rank.name || '')}" ${held ? 'readonly' : ''}></label>${held ? '<small class="feature-note">Assigned to roster records; its name is protected.</small>' : ''}<label class="unit-field">Rank abbreviation (shown on rosters)<input name="setup_rank_abbreviation" maxlength="20" value="${esc(rank.abbreviation || '')}" placeholder="e.g. Sgt"><small>Leave blank to show the full rank name.</small></label><details><summary>Edit requirements & optional paygrade</summary><label class="unit-field">Days since previous promotion to reach this rank<input name="setup_rank_days" type="number" min="0" max="36500" step="1" required value="${rank.days ?? 0}"></label><label class="unit-field">Paygrade label (optional)<input name="setup_rank_paygrade" maxlength="40" value="${esc(rank.paygrade || '')}"></label><label class="unit-field">Find qualification<input type="search" data-qual-search placeholder="Search qualifications"></label><div class="unit-checks" data-rank-qualifications>${
        quals
          .filter(
            (qual) =>
              !qual.archived || (rank.certificates || []).includes(qual.name),
          )
          .map(
            (qual) =>
              `<label><input name="setup_rank_qual_${rowId}" type="checkbox" value="${esc(qual.name)}" ${(rank.certificates || []).includes(qual.name) ? 'checked' : ''}>${esc(qual.name)}${qual.abbreviation ? ' (' + esc(qual.abbreviation) + ')' : ''}${qual.archived ? ' · Archived' : ''}</label>`,
          )
          .join('') ||
        '<p>Create qualifications in the Qualifications setup screen first.</p>'
      }</div></details><p class="feature-note" data-rank-explanation></p>`;
      row.querySelector('[data-rank-up]').onclick = () => {
        if (row.previousElementSibling)
          list.insertBefore(row, row.previousElementSibling);
        update();
      };
      row.querySelector('[data-rank-down]').onclick = () => {
        if (row.nextElementSibling)
          list.insertBefore(row.nextElementSibling, row);
        update();
      };
      row.querySelector('[data-rank-remove]').onclick = () => {
        row.remove();
        update();
      };
      row.querySelector('[data-qual-search]').oninput = (event) =>
        row
          .querySelectorAll('[data-rank-qualifications] label')
          .forEach(
            (label) =>
              (label.hidden = !label.textContent
                .toLowerCase()
                .includes(event.target.value.trim().toLowerCase())),
          );
      list.append(row);
      update();
    }
    function collect() {
      const rows = [...list.children],
        name = form.elements.setup_structure_name.value.trim();
      const next = {
        name,
        ranks: rows.map((row, i) => ({
          name: row.querySelector('[name="setup_rank_name"]').value.trim(),
          abbreviation: row
            .querySelector('[name="setup_rank_abbreviation"]')
            .value.trim(),
          paygrade: row
            .querySelector('[name="setup_rank_paygrade"]')
            .value.trim(),
          days: Number(row.querySelector('[name="setup_rank_days"]').value),
          next_rank:
            form.elements.setup_progression.value === 'ordered'
              ? rows[i + 1]
                  ?.querySelector('[name="setup_rank_name"]')
                  .value.trim() || ''
              : row.dataset.next
                ? rows
                    .find(
                      (candidate) =>
                        candidate.dataset.original === row.dataset.next,
                    )
                    ?.querySelector('[name="setup_rank_name"]')
                    .value.trim() || row.dataset.next
                : '',
          certificates: [
            ...row.querySelectorAll('[data-rank-qualifications] input:checked'),
          ].map((input) => input.value),
        })),
      };
      const structures = [...(catalog.rank_structures || [])];
      if (existing && !duplicate)
        structures[
          structures.findIndex((item) => item.name === existing.name)
        ] = next;
      else structures.push(next);
      return { ...catalog, rank_structures: structures };
    }
    function update() {
      request++;
      const rows = [...list.children],
        select = form.querySelector('#setup-preview-rank'),
        previous = select.value;
      select.innerHTML = rows
        .map((row) => {
          const name = row
            .querySelector('[name="setup_rank_name"]')
            .value.trim();
          return `<option value="${esc(name)}">${esc(name || 'Unnamed rank')}</option>`;
        })
        .join('');
      if ([...select.options].some((option) => option.value === previous))
        select.value = previous;
      rows.forEach((row, i) => {
        const name =
          row.querySelector('[name="setup_rank_name"]').value || 'Unnamed rank';
        row.querySelector('[data-rank-heading]').textContent =
          `${i + 1}. ${name}`;
        row.querySelector('[data-rank-up]').disabled = i === 0;
        row.querySelector('[data-rank-down]').disabled = i === rows.length - 1;
        const names = [
          ...row.querySelectorAll('[data-rank-qualifications] input:checked'),
        ].map((input) => input.value);
        row.querySelector('[data-rank-explanation]').textContent =
          i === 0
            ? 'First rank in the list. Direct roster assignments do not require promotion approval.'
            : `${row.querySelector('[name="setup_rank_days"]').value} days since last promotion${names.length ? ' + ' + names.join(', ') : ' · No qualifications required'}.`;
      });
      form.querySelector('#setup-preview-result').textContent = '';
    }
    (ranks.length ? ranks : [{}]).forEach(addRank);
    list.addEventListener('input', update);
    list.addEventListener('change', update);
    form.elements.setup_progression.onchange = update;
    form.querySelector('#setup-add-rank').onclick = () => addRank();
    form.querySelector('#setup-preview-member').onchange = () => {
      const member = detail.roster.find(
        (item) => item.id === Number(form.elements.setup_preview_member.value),
      );
      if (member) {
        form.elements.setup_preview_date.value = member.last_promo || '';
        const select = form.elements.setup_preview_rank;
        if ([...select.options].some((option) => option.value === member.rank))
          select.value = member.rank;
      }
    };
    const clearPreview = () => {
      request++;
      const result = form.querySelector('#setup-preview-result');
      if (result) result.textContent = '';
    };
    form.oninput = clearPreview;
    form.onchange = clearPreview;
    form.querySelector('#setup-preview').onclick = async () => {
      const button = form.querySelector('#setup-preview'),
        region = form.querySelector('#setup-preview-result'),
        serial = ++request;
      button.disabled = true;
      try {
        const result = await write(`/api/units/${unitId}/catalog/preview`, {
          catalog: collect(),
          member_id: Number(form.elements.setup_preview_member.value),
          rank_track: form.elements.setup_structure_name.value.trim(),
          rank: form.elements.setup_preview_rank.value,
          last_promo: form.elements.setup_preview_date.value,
        });
        if (serial !== request || !region.isConnected) return;
        const p = result.promotion;
        region.innerHTML = !result.target
          ? '<p>This rank has no next promotion configured.</p>'
          : `<h4>${esc(result.member.game_name)} → ${esc(p.next_rank)}</h4><p><strong>${p.eligible ? 'Eligible for staff review' : 'Not eligible yet'}</strong></p><ul><li>Required time: ${result.target.days} days · ${p.next_date ? 'Time requirement date: ' + esc(p.next_date) : 'Set the last promotion date'}</li><li>${p.missing.length ? 'Missing qualifications: ' + esc(p.missing.join(', ')) : 'All required qualifications held'}</li>${p.next_date && p.next_date > result.today ? '<li>Time requirement is not met.</li>' : ''}${result.member.archived ? '<li>Former members cannot be promoted.</li>' : ''}</ul><small>Preview only. Saving rules never promotes anyone automatically.</small>`;
      } catch (error) {
        if (serial === request && region.isConnected)
          region.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    };
    baseline();
  }
  return { render, qualification, structure };
})();
