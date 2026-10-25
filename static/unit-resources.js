// Unit references, award decisions, campaign credit and analytics.
(() => {
  const el=id=>document.getElementById(id), esc=escHtml;
  const dialog=el('resource-dialog'), form=el('resource-form');
  const read=async url=>readJson(await fetch(url)), write=async(url,data)=>readJson(await postJson(url,data));
  let context, referenceData, awardData, campaignData, kind='sop', nextReference=null, nextAward=null,selectedFolder='';
  let saving=false, handler=null, baseline='', epoch=0, referenceRequest=0, awardRequest=0, analyticsRequest=0, campaignRequest=0, modalRequest=0;
  const browserZone=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
  const localDay=(value=new Date())=>`${value.getFullYear()}-${String(value.getMonth()+1).padStart(2,'0')}-${String(value.getDate()).padStart(2,'0')}`;
  const start=new Date();start.setDate(start.getDate()-89);
  el('analytics-start').value=localDay(start);el('analytics-end').value=localDay();el('analytics-zone').value=browserZone;
  const base=()=>`/api/units/${context.unitId}`;
  const message=text=>{el('units-feedback').textContent=text;};
  const dateTime=seconds=>new Date(seconds*1000).toLocaleString();
  const image=(url,name,className='resource-image')=>url?`<img class="${className}" src="${esc(url)}" alt="${esc(name)}" loading="lazy" referrerpolicy="no-referrer">`:'';
  const link=url=>url?`<a class="manager-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open reference link ↗</a>`:'';
  const field=(label,name,value='',type='text')=>`<label class="unit-field">${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}"></label>`;
  const textArea=(label,name,value='',max=4000)=>`<label class="unit-field wide">${esc(label)}<textarea name="${name}" maxlength="${max}">${esc(value)}</textarea></label>`;
  let editorFiles=[];
  const signature=()=>JSON.stringify({fields:[...new FormData(form)],files:editorFiles.map(f=>f.token)});
  const clearEditorFiles=()=>{editorFiles.forEach(f=>URL.revokeObjectURL(f.url));editorFiles=[];};
  dialog.addEventListener('close',()=>{if(!dialog.open)clearEditorFiles();});
  UnitUX.registerDraft({dirty:()=>dialog.open&&signature()!==baseline,busy:()=>dialog.open&&saving,discard:()=>dialog.close()});
  function close(){if(!UnitUX.canLeave())return;dialog.close();modalRequest++;}
  el('resource-close').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  function open(title,html,save=null,button='Save changes'){
    modalRequest++;
    clearEditorFiles();
    if(dialog.open)dialog.close();el('resource-title').textContent=title;el('resource-body').innerHTML=html;el('resource-error').textContent='';
    handler=save;el('resource-save').hidden=!save;el('resource-save').textContent=button;dialog.showModal();baseline=signature();
    UnitUX.open(dialog);
  }
  form.onsubmit=async e=>{e.preventDefault();if(saving||!handler)return;saving=true;el('resource-save').disabled=true;
    try{await handler();dialog.close();document.dispatchEvent(new Event('unit-access-changed'));}
    catch(error){el('resource-error').textContent=error.message;}
    finally{saving=false;el('resource-save').disabled=false;}
  };
  function members(root){root.querySelectorAll('[data-resource-member]').forEach(b=>b.onclick=()=>document.dispatchEvent(new CustomEvent('unit-open-member',{detail:Number(b.dataset.resourceMember)})));}

  async function loadReferences(append=false){
    if(!context)return;const current=epoch, request=++referenceRequest;
    const query=new URLSearchParams({kind,folder:selectedFolder,status:el('reference-publication').value,q:el('reference-search').value,category:el('reference-category').value,sort:el('reference-sort').value,archived:el('reference-archived').value,offset:append?nextReference||0:0});
    const data=await read(`${base()}/library?${query}`);if(current!==epoch||request!==referenceRequest)return;referenceData=data;
    const selected=el('reference-category').value;el('reference-category').replaceChildren(new Option('All categories',''));
    data.categories.forEach(c=>el('reference-category').add(new Option(c,c)));el('reference-category').value=selected;
    el('reference-new').hidden=!data.permissions.references;el('reference-new').textContent=kind==='sop'?'New SOP':'New loadout';
    el('reference-publication-label').hidden=data.member;el('reference-archived').closest('label').hidden=data.member;
    renderFolders(data);
    const html=data.items.map(item=>`<article class="unit-block resource-card">${kind==='loadout'?image(item.image_url,item.title):''}<small>${esc(item.folder||'Root')} · ${esc(item.status)}${item.status==='draft'&&item.has_published?' (published copy remains available)':''} · ${esc(item.category)}${item.role?' · '+esc(item.role):''}</small><h3>${esc(item.title)}</h3><p>${esc(item.excerpt)}</p><small>Updated ${esc(dateTime(item.updated_at))} · ${esc(item.updated_by)}</small><button type="button" data-reference="${item.id}">Open ${kind==='sop'?'SOP':'loadout'}</button></article>`).join('');
    if(append)el('reference-grid').insertAdjacentHTML('beforeend',html);else el('reference-grid').innerHTML=html||'<p class="unit-empty">No references match. Staff with reference permissions can add one.</p>';
    nextReference=data.next_offset;el('reference-more').hidden=nextReference===null;
    el('reference-grid').querySelectorAll('[data-reference]').forEach(b=>b.onclick=()=>showReference(Number(b.dataset.reference)));
  }
  function renderFolders(data){
    const root=el('reference-folders');root.hidden=kind!=='sop';if(root.hidden)return;
    const paths=new Set();data.folders.forEach(f=>{const parts=f.folder.split('/');parts.forEach((_,i)=>{const path=parts.slice(0,i+1).join('/');if(path)paths.add(path);});});
    const pages=path=>data.documents.filter(d=>(d.folder||'')===path).map(d=>`<button type="button" data-sop-page="${d.id}">${esc(d.title)}</button>`).join('');
    function branches(parent=''){
      return [...paths].filter(path=>path.includes('/')?path.slice(0,path.lastIndexOf('/'))===parent:parent==='').sort((a,b)=>a.localeCompare(b)).map(path=>`<details ${selectedFolder===path||selectedFolder.startsWith(path+'/')?'open':''}><summary>${esc(path.split('/').at(-1))}</summary><button type="button" data-sop-folder="${esc(path)}" aria-current="${selectedFolder===path?'page':'false'}">View folder</button>${pages(path)}${branches(path)}</details>`).join('');
    }
    root.innerHTML=`<strong>Folders & pages</strong><button type="button" data-sop-folder="" aria-current="${!selectedFolder?'page':'false'}">All documents</button>${pages('')}${branches()}`;
    root.querySelectorAll('[data-sop-folder]').forEach(b=>b.onclick=()=>{selectedFolder=b.dataset.sopFolder;loadReferences().catch(e=>message(e.message));});
    root.querySelectorAll('[data-sop-page]').forEach(b=>b.onclick=()=>showReference(Number(b.dataset.sopPage)));
  }
  function referenceComparison(previous,current,files=[],currentFiles=[]){
    const oldLines=previous.body.split('\n'),newLines=current.body.split('\n');
    const metadata=['title','category','folder','url','related'].filter(key=>(previous[key]||'')!==(current[key]||''));
    return `<details class="unit-block"><summary>Compare with current document</summary>${metadata.map(key=>`<p><strong>${esc(key)}</strong><br>Revision: ${esc(previous[key]||'—')}<br>Current: ${esc(current[key]||'—')}</p>`).join('')}<p><strong>Attachments in this revision:</strong> ${esc(files.map(f=>f.filename).join(', ')||'None')}<br><strong>Attachments in current draft:</strong> ${esc(currentFiles.map(f=>f.filename).join(', ')||'None')}</p><p class="feature-note">Lines are compared at the same line number. Highlighted rows differ. The first 2,000 lines are shown; download text for longer documents.</p><div class="unit-table"><table class="sop-comparison"><thead><tr><th>Line</th><th>This revision</th><th>Current working copy</th></tr></thead><tbody>${Array.from({length:Math.min(2000,Math.max(oldLines.length,newLines.length))},(_,i)=>`<tr class="${oldLines[i]===newLines[i]?'':'sop-line-changed'}"><td>${i+1}</td><td>${esc(oldLines[i]??'')}</td><td>${esc(newLines[i]??'')}</td></tr>`).join('')}</tbody></table></div></details>`;
  }
  function referenceInline(value,files=[]){
    const pattern=/!\[([^\]\n]*)\]\(attachment:([a-f0-9]{32})\)|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*/g;
    let result='',start=0;
    for(const match of value.matchAll(pattern)){
      result+=esc(value.slice(start,match.index));start=match.index+match[0].length;
      if(match[2]){
        const file=files.find(f=>f.token===match[2]);
        result+=file?.mime.startsWith('image/')?`<img class="sop-inline-image" src="${esc(file.url||`${base()}/library/files/${file.token}`)}" alt="${esc(match[1])}" loading="lazy">`:esc(match[0]);
      }else if(match[4]){
        result+=`<a href="${esc(match[4])}" target="_blank" rel="noopener noreferrer">${esc(match[3])}</a>`;
      }else if(match[5])result+=`<strong>${esc(match[5])}</strong>`;
      else result+=`<em>${esc(match[6])}</em>`;
    }
    return result+esc(value.slice(start));
  }
  function referenceContent(item,files=[]){
    if(item.kind!=='sop')return item.body?`<div class="reference-prose">${esc(item.body)}</div>`:'';
    const headings=[];
    let listing=false;
    let content=item.body.split('\n').map(line=>{
      if(/^[-*]\s+/.test(line)){const prefix=listing?'':'<ul>';listing=true;return prefix+`<li>${referenceInline(line.slice(2),files)}</li>`;}
      const prefix=listing?'</ul>':'';listing=false;
      const match=line.match(/^(#{1,3})\s+(.+)$/);
      if(!match)return prefix+referenceInline(line,files);
      const id=`sop-section-${headings.length}`;
      headings.push({id,title:match[2],level:match[1].length});
      return prefix+`<h${match[1].length+1} id="${id}" tabindex="-1">${esc(match[2])}</h${match[1].length+1}>`;
    }).join('\n');
    if(listing)content+='</ul>';
    return `<div class="sop-reader">${headings.length?`<nav aria-label="Document sections"><strong>Contents</strong>${headings.map(h=>`<a href="#${h.id}" data-sop-section="${h.id}" class="sop-level-${h.level}">${esc(h.title)}</a>`).join('')}</nav>`:''}<article class="reference-prose">${content}</article></div>`;
  }
  function wireReference(item){
    form.querySelectorAll('[data-sop-section]').forEach(a=>a.onclick=e=>{e.preventDefault();const heading=el(a.dataset.sopSection);heading.scrollIntoView({block:'start'});heading.focus({preventScroll:true});});
    el('reference-download')?.addEventListener('click',()=>{
      const blob=new Blob([`${item.title}\n${item.category}\nUpdated ${dateTime(item.updated_at)} · ${item.updated_by}\n\n${item.body}\n${item.url||''}\n`],{type:'text/plain;charset=utf-8'});
      const address=URL.createObjectURL(blob),a=document.createElement('a');
      a.href=address;a.download=(item.title.replace(/[^a-z0-9 _-]/gi,'').trim()||'SOP')+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(address),1000);
    });
  }
  async function showReference(id,versionId=null,published=false){
    if(saving)return;const current=epoch, request=++modalRequest, unitBase=base();
    try{const data=await read(`${unitBase}/library/${id}${versionId?`/versions/${versionId}`:published?'?published=1':''}`);if(current!==epoch||request!==modalRequest)return;
      const item=data.item;
      open(item.title,`${versionId?`<p class="unit-warn">Historical revision · ${esc(dateTime(data.created_at))} · ${esc(data.actor)}</p><button type="button" id="reference-current">Back to current document</button>`:''}${versionId&&data.current?referenceComparison(item,data.current,data.files||[],data.current_files||[]):''}${image(item.image_url,item.title)}<p class="feature-note">${esc(item.folder||'Root')} · ${esc(item.status||'published')} · ${esc(item.category)}${item.role?' · '+esc(item.role):''}${item.archived?' · Archived':''} · Updated ${esc(dateTime(item.updated_at))} · ${esc(item.updated_by)}</p>${referenceContent(item,data.files||[])}${item.slots.length?`<div class="unit-table loadout-table"><table><thead><tr><th>Slot</th><th>Standard item</th><th>Alternatives</th><th>Notes</th></tr></thead><tbody>${item.slots.map(s=>`<tr><td>${esc(s.slot)}</td><td>${esc(s.standard)}</td><td>${esc(s.alternatives)}</td><td>${esc(s.notes)}</td></tr>`).join('')}</tbody></table></div>`:''}${link(item.url)}${data.files?.length?`<section class="unit-block"><h3>Attachments</h3>${data.files.map(f=>`<p><a href="${base()}/library/files/${f.token}" target="_blank" rel="noopener noreferrer">${esc(f.filename)}</a> <small>${(f.size/1024/1024).toFixed(2)} MB${f.mime.startsWith('image/')?' · Image':' · Download'}</small></p>`).join('')}</section>`:''}<div class="unit-toolbar">${item.kind==='sop'?'<button type="button" id="reference-download">Download text</button>':''}${data.permissions?.references&&!versionId&&!data.published_view?'<button type="button" id="reference-edit">Edit reference</button>':''}${data.permissions?.references&&!versionId&&item.kind==='sop'?'<button type="button" id="reference-rules">Reading & review</button>':''}${data.acknowledgement?`<button type="button" id="reference-acknowledge" ${data.acknowledgement.acknowledged_at?'disabled':''}>${data.acknowledgement.acknowledged_at?'Acknowledged this version':'I have read this version'}</button>`:''}${data.permissions?.references&&versionId?'<button type="button" id="reference-restore">Restore as draft</button>':''}${data.permissions?.references&&!versionId&&item.status==='template'?'<button type="button" id="reference-from-template">Create SOP from template</button>':''}</div>${data.related?.length?`<section class="unit-block"><h3>Related guidance</h3>${data.related.map(r=>r.kind==='sop'?`<button type="button" data-related-sop="${r.id}">${esc(r.title)}</button>`:`<p>${esc(r.kind)} · ${esc(r.title)}</p>`).join('')}</section>`:''}${data.history?.length?`<details class="unit-block"><summary>Revision history · latest 50</summary>${data.history.map(h=>`<p><strong>${esc(h.actor)}</strong> · ${esc(h.action)}<small>${esc(dateTime(h.created_at))}</small><button type="button" data-reference-version="${h.id}">View revision</button></p>`).join('')}</details>`:''}`);
      wireReference(item);
      el('reference-rules')?.addEventListener('click',()=>referenceRules(id));
      el('reference-acknowledge')?.addEventListener('click',async()=>{
        const button=el('reference-acknowledge');button.disabled=true;
        try{await write(`${unitBase}/reading/${id}/acknowledge`,{publication:data.acknowledgement.publication});button.textContent='Acknowledged this version';document.dispatchEvent(new Event('unit-member-change'));}catch(error){button.disabled=false;el('resource-error').textContent=error.message;}
      });
      el('reference-edit')?.addEventListener('click',()=>referenceEditor(item,data.revision,data.files||[],data.events||[]));
      form.querySelectorAll('[data-related-sop]').forEach(b=>b.onclick=()=>showReference(Number(b.dataset.relatedSop)));
      el('reference-from-template')?.addEventListener('click',()=>referenceEditor({...item,id:undefined,template_id:item.id,status:'draft',archived:0,title:item.title+' copy'},data.revision,data.files||[],data.events||[]));
      el('reference-restore')?.addEventListener('click',()=>open('Restore revision as draft','<p>This replaces the working copy with this revision. The current published copy remains available to members until staff publish again.</p>',async()=>{await write(`${unitBase}/library/${id}/versions/${versionId}/restore`,{revision:data.revision});},'Restore draft'));
      el('reference-current')?.addEventListener('click',()=>showReference(id));
      form.querySelectorAll('[data-reference-version]').forEach(b=>b.onclick=()=>showReference(id,Number(b.dataset.referenceVersion)));
    }catch(error){message(error.message);}
  }
  async function referenceRules(id){
    if(saving)return;const current=epoch,request=++modalRequest,unitBase=base();
    try{const data=await read(`${unitBase}/library/${id}/rules`);if(current!==epoch||request!==modalRequest)return;
      const rules=data.rules||{},targets=JSON.parse(rules.targets||'[]'),catalog=context.detail.unit.catalog;
      const positions=[...new Set([...(catalog.positions||[]),...context.detail.structure.filter(n=>n.kind==='billet').map(n=>n.name)])].sort();
      const audience=(label,kind,items)=>`<label class="unit-field">${label}<select name="audience_${kind}" multiple size="5">${items.map(name=>`<option value="${esc(name)}" ${targets.some(t=>t.kind===kind&&t.name===name)?'selected':''}>${esc(name)}</option>`).join('')}</select></label>`;
      open('Required reading & document review',`<p class="feature-note">Audiences are combined: anyone matching at least one is assigned the current published version. Republish an SOP to require a fresh acknowledgement. Staff can use the progress list below to follow up.</p><label><input type="checkbox" name="everyone" ${targets.some(t=>t.kind==='all')?'checked':''}> Required for every login assigned to this unit</label><div class="unit-form-grid">${audience('Positions / primary billets','position',positions)}${audience('Qualifications','qualification',catalog.certificates||[])}${field('Reading deadline (optional)','reading_due',rules.reading_due||'','date')}<label class="unit-field">Document owner<select name="owner_id"><option value="">Unassigned</option>${data.owners.map(o=>`<option value="${o.id}" ${rules.owner_id===o.id?'selected':''}>${esc(o.name)}</option>`).join('')}</select></label>${field('Last reviewed','reviewed_on',rules.reviewed_on||'','date')}${field('Next review reminder','review_on',rules.review_on||'','date')}</div><p class="feature-note">Review dates appear in staff’s My unit reminders. They do not unpublish documents. Clear the audiences to stop requiring this reading.</p><details class="unit-block" open><summary>Current published version acknowledgements (${data.progress.filter(p=>p.acknowledged_at).length}/${data.progress.length})</summary>${data.progress.map(p=>`<p><strong>${esc(p.name)}</strong> · ${p.acknowledged_at?'Acknowledged '+esc(dateTime(p.acknowledged_at)):'Awaiting acknowledgement'}</p>`).join('')||'<p>No accounts currently match a published reading assignment.</p>'}</details>`,async()=>{
        const values=Object.fromEntries(new FormData(form));const selected=['position','qualification'].flatMap(kind=>[...form.elements['audience_'+kind].selectedOptions].map(o=>({kind,name:o.value})));
        if(values.everyone)selected.unshift({kind:'all'});
        await write(`${unitBase}/library/${id}/rules`,{targets:selected,reading_due:values.reading_due,owner_id:values.owner_id?Number(values.owner_id):null,reviewed_on:values.reviewed_on,review_on:values.review_on,revision:data.revision});
      });baseline=signature();
    }catch(error){message(error.message);}
  }
  function referenceEditor(item=null,revision=referenceData?.revision,files=[],events=referenceData?.events||[]){
    if(saving)return;const itemKind=item?.kind||kind;
    const related=JSON.parse(item?.related||'[]');
    const choices=(name,items,type)=>`<label class="unit-field">${esc(name)}<select name="related_${type}" multiple size="4">${items.map(target=>{const id=typeof target==='string'?target:target.id,title=typeof target==='string'?target:target.title||target.name;return `<option value="${esc(id)}" ${related.some(r=>r.kind===type&&(r.id===id||r.name===id))?'selected':''}>${esc(title)}</option>`;}).join('')}</select></label>`;
    open(item?.id?'Edit '+item.title:itemKind==='sop'?'New SOP':'New loadout',`<div class="unit-form-grid">${field('Title','title',item?.title||'')}${field('Category','category',item?.category||'General')}${field('Folder path (optional)','folder',item?.folder??selectedFolder)}<label class="unit-field">Save as<select name="status">${['draft','published',...(itemKind==='sop'?['template']:[])].map(s=>`<option value="${s}" ${(item?.status==='template'?'template':itemKind==='sop'?'draft':item?.status||'published')===s?'selected':''}>${s==='draft'?'Draft — staff only':s==='published'?'Published — visible to members':'Reusable template — staff only'}</option>`).join('')}</select></label>${itemKind==='loadout'?field('Role / position','role',item?.role||''):''}${field('Reference link (optional)','url',item?.url||'','url')}${itemKind==='loadout'?field('Image URL (optional)','image_url',item?.image_url||'','url'):''}${textArea(itemKind==='sop'?'Write SOP':'Description / guidance','body',item?.body||'',itemKind==='sop'?100000:20000)}</div>${itemKind==='sop'?`<div id="sop-editor-tools" class="unit-toolbar" role="group" aria-label="Document formatting"><button type="button" data-sop-format="heading">Heading</button><button type="button" data-sop-format="bold">Bold</button><button type="button" data-sop-format="italic">Italic</button><button type="button" data-sop-format="list">List</button><button type="button" data-sop-format="link">Link</button><button type="button" id="sop-attach">Add images / documents</button><button type="button" id="sop-preview-toggle" aria-pressed="false">Preview</button></div><input type="file" id="sop-files" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.webp" multiple hidden><p class="feature-note">Select text, then use the formatting buttons. Images are inserted at the cursor. PDF and Word files are downloadable attachments. Images: up to 4 MB; documents: up to 20 MB each. Up to 10 uploads / 50 MB per save.</p><div id="sop-pending-files"></div><div id="sop-preview" class="unit-block" hidden></div>${files.length?`<details class="unit-block"><summary>Saved attachments (${files.length})</summary>${files.map(f=>`<p>${esc(f.filename)}${f.mime.startsWith('image/')?` <button type="button" data-sop-insert="${f.token}">Insert image</button>`:''}</p>`).join('')}<small>Saved files are retained for document history.</small></details>`:''}`:''}${itemKind==='sop'?`<details class="unit-block"><summary>Related SOPs, qualifications, positions and events</summary><p class="feature-note">Hold Ctrl / Command to select multiple items. Members see published related SOPs and qualification / position labels; event details remain staff-only.</p><div class="unit-form-grid">${choices('SOPs',(referenceData?.documents||[]).filter(d=>d.id!==item?.id),'sop')}${choices('Qualifications',context.detail.unit.catalog.certificates||[],'qualification')}${choices('Positions',context.detail.unit.catalog.positions||[],'position')}${choices('Events',events,'event')}</div></details>`:''}${itemKind==='loadout'?'<h3>Kit slots</h3><div id="loadout-slot-rows"></div><button type="button" id="loadout-add-slot">Add slot</button><p class="feature-note">For example: Helmet, Primary weapon, Vest, Backpack or Medical supplies.</p>':''}${item?`<label><input type="checkbox" name="archived" ${item.archived?'checked':''}> Archive this reference (can be restored)</label>`:''}`,async()=>{
      const values=Object.fromEntries(new FormData(form));const slots=[...form.querySelectorAll('[data-loadout-slot]')].map(row=>Object.fromEntries(['slot','standard','alternatives','notes'].map(key=>[key,row.querySelector(`[name="slot_${key}"]`).value])));
      const data={kind:itemKind,title:values.title,category:values.category,role:values.role||'',body:values.body,url:values.url,image_url:values.image_url||'',slots,folder:values.folder,status:values.status,related:['sop','qualification','position','event'].flatMap(type=>[...(form.querySelector(`[name="related_${type}"]`)?.selectedOptions||[])].map(o=>['sop','event'].includes(type)?{kind:type,id:Number(o.value)}:{kind:type,name:o.value})),archived:!!values.archived,revision,...(item?.id?{id:item.id}:{}),...(item?.template_id?{template_id:item.template_id}:{})};
      if(editorFiles.length){
        const payload=new FormData();payload.set('data',JSON.stringify(data));editorFiles.forEach(f=>payload.append(f.token,f.file));
        await readJson(await postForm(`${base()}/library`,payload));
      }else await write(`${base()}/library`,data);
    });
    form.elements.title.required=true;form.elements.title.maxLength=120;form.elements.category.required=true;form.elements.category.maxLength=80;
    function addSlot(slot={}){const row=document.createElement('div');row.className='loadout-slot-editor';row.dataset.loadoutSlot='';row.innerHTML=field('Slot','slot_slot',slot.slot||'')+field('Standard item','slot_standard',slot.standard||'')+textArea('Alternatives','slot_alternatives',slot.alternatives||'',2000)+textArea('Notes','slot_notes',slot.notes||'',2000)+'<button type="button">Remove slot</button>';row.querySelector('[name="slot_slot"]').required=true;row.querySelector('button').onclick=()=>row.remove();el('loadout-slot-rows').append(row);}
    if(itemKind==='loadout'){(item?.slots||[]).forEach(addSlot);el('loadout-add-slot').onclick=()=>addSlot();}
    if(itemKind==='sop'){setupSopEditor(files);setupTemplates(item,revision);form.elements.status.closest('label').insertAdjacentHTML('beforeend','<small>Drafts are staff-only. Choose Published when ready to update the member copy.</small>');}
    baseline=signature();
  }

  function setupTemplates(item,revision){
    if(item?.id)return;
    const builtins={procedure:'# Purpose\nDescribe when this procedure applies.\n\n# Responsibilities\n- Responsible position\n\n# Procedure\n- First step\n\n# References\nAdd related guidance.',communications:'# Purpose\n\n# Callsigns and channels\n- Primary net\n- Alternate net\n\n# Radio procedure\n\n# Lost communications',training:'# Training objective\n\n# Prerequisites\n\n# Equipment\n\n# Lesson plan\n\n# Evaluation criteria',medical:'# Scope\n\n# Required equipment\n\n# Assessment\n\n# Treatment procedure\n\n# Evacuation and handover'};
    const holder=document.createElement('label');holder.className='unit-field';holder.innerHTML=`Start from a template<select id="sop-template-choice"><option value="">Blank / current content</option><optgroup label="Built-in outlines">${Object.keys(builtins).map(key=>`<option value="builtin:${key}">${esc(key)}</option>`).join('')}</optgroup><optgroup label="Unit templates">${(referenceData?.templates||[]).map(t=>`<option value="${t.id}">${esc(t.title)}</option>`).join('')}</optgroup></select>`;
    el('resource-body').prepend(holder);
    el('sop-template-choice').onchange=async()=>{
      const choice=el('sop-template-choice').value;if(!choice)return;
      if(!UnitUX.canLeave()){el('sop-template-choice').value='';return;}
      if(choice.startsWith('builtin:')){form.elements.body.value=builtins[choice.slice(8)];form.elements.body.dispatchEvent(new Event('input'));return;}
      const current=epoch,request=++modalRequest;
      try{const data=await read(`${base()}/library/${Number(choice)}`);if(current!==epoch||request!==modalRequest)return;referenceEditor({...data.item,id:undefined,template_id:data.item.id,title:data.item.title+' copy',status:'draft',archived:0},data.revision,data.files||[],data.events||[]);}catch(error){el('resource-error').textContent=error.message;}
    };
  }
  function setupSopEditor(files){
    const body=form.elements.body,preview=el('sop-preview');
    el('sop-editor-tools').classList.add('wide');body.closest('label').before(el('sop-editor-tools'));
    function render(){preview.innerHTML=referenceContent({kind:'sop',body:body.value},[...files,...editorFiles]);preview.querySelectorAll('[data-sop-section]').forEach(a=>a.onclick=e=>{e.preventDefault();preview.querySelector(`[id="${a.dataset.sopSection}"]`)?.scrollIntoView({block:'nearest'});});}
    function insert(text){body.setRangeText(text,body.selectionStart,body.selectionEnd,'end');body.focus();body.dispatchEvent(new Event('input'));}
    const insertImage=file=>insert(`![${file.filename.replace(/[\]\n]/g,'')}](attachment:${file.token})`);
    form.querySelectorAll('[data-sop-format]').forEach(button=>button.onclick=()=>{
      if(saving)return;const selected=body.value.slice(body.selectionStart,body.selectionEnd),type=button.dataset.sopFormat;
      insert(type==='heading'?`\n# ${selected||'Section heading'}\n`:type==='bold'?`**${selected||'Bold text'}**`:type==='italic'?`*${selected||'Italic text'}*`:type==='list'?`\n${(selected||'List item').split('\n').map(line=>'- '+line).join('\n')}\n`:`[${selected||'Link text'}](https://example.com)`);
    });
    el('sop-preview-toggle').onclick=()=>{preview.hidden=!preview.hidden;el('sop-preview-toggle').setAttribute('aria-pressed',String(!preview.hidden));if(!preview.hidden)render();};
    body.addEventListener('input',()=>{if(!preview.hidden)render();});
    form.querySelectorAll('[data-sop-insert]').forEach(button=>button.onclick=()=>insertImage(files.find(f=>f.token===button.dataset.sopInsert)));
    el('sop-attach').onclick=()=>{if(!saving)el('sop-files').click();};
    function pending(){
      el('sop-pending-files').innerHTML=editorFiles.map(f=>`<p>${esc(f.filename)} · ${(f.file.size/1024/1024).toFixed(2)} MB <button type="button" data-sop-remove="${f.token}">Remove upload</button></p>`).join('');
      el('sop-pending-files').querySelectorAll('[data-sop-remove]').forEach(button=>button.onclick=()=>{
        if(saving)return;const file=editorFiles.find(f=>f.token===button.dataset.sopRemove);
        body.value=body.value.replace(new RegExp('!\\[[^\\]\\n]*\\]\\(attachment:'+file.token+'\\)','g'),'');
        URL.revokeObjectURL(file.url);editorFiles=editorFiles.filter(f=>f!==file);pending();if(!preview.hidden)render();
      });
    }
    el('sop-files').onchange=()=>{
      if(saving)return;const chosen=[...el('sop-files').files];el('sop-files').value='';
      if(editorFiles.length+chosen.length>10||[...editorFiles.map(f=>f.file),...chosen].reduce((sum,f)=>sum+f.size,0)>50*1024*1024){el('resource-error').textContent='Keep each save to 10 files and 50 MB total.';return;}
      for(const file of chosen){
        const extension=file.name.split('.').at(-1).toLowerCase(),isImage=['png','jpg','jpeg','webp'].includes(extension);
        if(!['pdf','doc','docx','png','jpg','jpeg','webp'].includes(extension)||!file.size||file.size>(isImage?4:20)*1024*1024){el('resource-error').textContent='Use PDF, Word, PNG, JPEG or WebP files within the size limits.';continue;}
        const entry={token:crypto.randomUUID().replaceAll('-',''),filename:file.name,mime:isImage?'image/'+extension:file.type,file,url:URL.createObjectURL(file)};
        editorFiles.push(entry);if(isImage)insertImage(entry);
      }
      pending();if(!preview.hidden)render();
    };
  }

  function grantCard(grant,allowRevoke=false){return `<article class="unit-block award-grant">${image(grant.image_url,grant.award_name,'award-image')}<div><strong>${esc(grant.award_name)}</strong>${grant.game_name?`<button type="button" class="member-record-link" data-resource-member="${grant.member_id}">${esc(grant.game_name)}</button>`:''}<small>${esc(grant.awarded_on)} · Issued by ${esc(grant.issuer)}${grant.campaign_id?' · Campaign #'+grant.campaign_id:''}</small><p class="reference-prose">${esc(grant.citation)}</p>${grant.state==='revoked'?`<p class="unit-warn">Revoked by ${esc(grant.revoked_by)} · ${esc(dateTime(grant.revoked_on))}</p><p>${esc(grant.revoke_reason)}</p>`:allowRevoke?`<button type="button" data-revoke-award="${grant.id}">Revoke…</button>`:''}</div></article>`;}
  async function loadAwards(append=false){
    if(!context)return;const current=epoch, request=++awardRequest,query=new URLSearchParams();if(el('award-member').value)query.set('member_id',el('award-member').value);if(append&&nextAward)query.set('before',nextAward);
    const data=await read(`${base()}/awards?${query}`);if(current!==epoch||request!==awardRequest)return;awardData=data;
    const selected=el('award-member').value;el('award-member').replaceChildren(new Option('All members',''));data.members.forEach(m=>el('award-member').add(new Option(m.game_name+(m.archived?' · Former':''),m.id)));el('award-member').value=selected;
    el('award-new').hidden=!data.permissions.awards;el('award-issue').hidden=!data.permissions.awards;
    el('award-catalog').innerHTML=data.catalog.map(a=>`<article class="unit-block resource-card">${image(a.image_url,a.name,'award-image')}<h3>${esc(a.name)}</h3><p class="reference-prose">${esc(a.description)}</p>${a.archived?'<small>Archived</small>':''}${data.permissions.awards?`<button type="button" data-award-catalog="${a.id}">Edit award</button>`:''}</article>`).join('')||'<p class="unit-empty">No awards defined.</p>';
    const html=data.grants.map(a=>grantCard(a,data.permissions.awards)).join('');if(append)el('award-history').insertAdjacentHTML('beforeend',html);else el('award-history').innerHTML=html||'<p>No awards issued for this selection.</p>';
    nextAward=data.next_before;el('award-more').hidden=nextAward===null;members(el('award-history'));
    el('award-catalog').querySelectorAll('[data-award-catalog]').forEach(b=>b.onclick=()=>awardEditor(data.catalog.find(a=>a.id===Number(b.dataset.awardCatalog))));
    el('award-history').querySelectorAll('[data-revoke-award]').forEach(b=>b.onclick=()=>revokeAward(Number(b.dataset.revokeAward)));
  }
  function awardEditor(award=null){
    if(saving||!awardData)return;const revision=awardData.revision;
    open(award?'Edit award':'Create award',`${field('Award name','name',award?.name||'')}${textArea('Description','description',award?.description||'')}${field('Image URL (optional)','image_url',award?.image_url||'','url')}${award?`<label><input type="checkbox" name="archived" ${award.archived?'checked':''}> Archive (issued awards retain their names and images)</label>`:''}`,async()=>{const values=Object.fromEntries(new FormData(form));await write(`${base()}/awards/catalog`,{...values,archived:!!values.archived,revision,...(award?{id:award.id}:{})});});form.elements.name.required=true;form.elements.name.maxLength=120;baseline=signature();
  }
  async function issueAward(memberId=null,awardId=null,campaign=null){
    if(saving)return;const current=epoch, request=++modalRequest;
    try{const data=await read(`${base()}/awards`);if(current!==epoch||request!==modalRequest)return;
      const catalog=data.catalog.filter(a=>!a.archived);if(!catalog.length){message('Create an active award in the catalog first.');return;}
      if(!data.members.length){message('Add a roster member before issuing an award.');return;}
      if(memberId&&!data.members.some(m=>m.id===memberId)){message('This roster member no longer exists. Refresh the unit.');return;}
      if(awardId&&!catalog.some(a=>a.id===awardId)){message('The campaign award is archived or unavailable. Update the campaign or restore its award.');return;}
      open(campaign?'Approve campaign award':'Issue award',`<label class="unit-field">Member<select name="member_id" ${memberId?'disabled':''}>${data.members.map(m=>`<option value="${m.id}" ${m.id===memberId?'selected':''}>${esc(m.game_name)}${m.archived?' · Former member':''}</option>`).join('')}</select></label><label class="unit-field">Award<select name="award_id" ${campaign?'disabled':''}>${catalog.map(a=>`<option value="${a.id}" ${a.id===awardId?'selected':''}>${esc(a.name)}</option>`).join('')}</select></label>${field('Award date','awarded_on',data.today,'date')}${textArea('Citation / reason','citation',campaign?'Participation in '+campaign.name:'')}${campaign?`<p>Campaign: ${esc(campaign.name)}. Eligibility and finalized attendance are rechecked when you confirm.</p>`:'<label><input type="checkbox" name="additional"> Allow an additional award if the member already holds this medal</label>'}<label class="bulk-confirm"><input type="checkbox" name="confirmed" required> I approve issuing this award and citation.</label>`,async()=>{await write(`${base()}/awards/grant`,{member_id:Number(form.elements.member_id.value),award_id:Number(form.elements.award_id.value),awarded_on:form.elements.awarded_on.value,citation:form.elements.citation.value,additional:new FormData(form).has('additional'),campaign_id:campaign?.id??null,revision:data.revision});},'Confirm award');
      form.elements.citation.required=true;form.elements.awarded_on.required=true;form.elements.awarded_on.max=data.today;baseline=signature();
    }catch(error){message(error.message);}
  }
  function revokeAward(id){if(saving)return;const revision=awardData.revision;open('Revoke award','<p>The award and its original citation remain in the member’s history.</p>'+textArea('Reason','reason'),async()=>{await write(`${base()}/awards/${id}/revoke`,{revision,reason:form.elements.reason.value});},'Confirm revocation');form.elements.reason.required=true;form.elements.reason.maxLength=1000;baseline=signature();}

  async function loadCampaigns(){
    if(!context)return;const current=epoch,request=++campaignRequest;const data=await read(`${base()}/campaigns`);if(current!==epoch||request!==campaignRequest)return;campaignData=data;
    el('campaign-new').hidden=!data.permissions.campaigns;const state=el('campaign-state').value;
    el('campaign-list').innerHTML=data.campaigns.filter(c=>state==='all'||c.state===state).map(c=>`<article class="unit-block resource-card"><small>${esc(c.state)} · ${c.threshold}% participation threshold</small><h3>${esc(c.name)}</h3><p>${esc(c.description)}</p><small>${c.mode==='range'?esc(c.starts_on+' – '+c.ends_on+' · '+c.timezone):JSON.parse(c.event_ids).length+' selected events'}</small><button type="button" data-campaign="${c.id}">Open campaign</button></article>`).join('')||'<p class="unit-empty">No campaigns in this view.</p>';
    el('campaign-list').querySelectorAll('[data-campaign]').forEach(b=>b.onclick=()=>showCampaign(Number(b.dataset.campaign)));
  }
  function campaignEditor(campaign=null,revision=campaignData?.revision){
    if(saving||!campaignData)return;const selected=new Set(campaign?JSON.parse(campaign.event_ids):[]), events=[...campaignData.events];
    const missing=[...selected].filter(id=>!events.some(e=>e.id===id));
    open(campaign?'Edit campaign':'New campaign',`${field('Campaign name','name',campaign?.name||'')}${textArea('Description','description',campaign?.description||'')}<div class="unit-form-grid"><label class="unit-field">Grouping<select name="mode"><option value="range" ${campaign?.mode==='manual'?'':'selected'}>Date window</option><option value="manual" ${campaign?.mode==='manual'?'selected':''}>Selected events</option></select></label><label class="unit-field">State<select name="state">${['active','completed','archived'].map(s=>`<option ${campaign?.state===s?'selected':''}>${s}</option>`).join('')}</select></label>${field('Window start (inclusive)','starts_on',campaign?.starts_on||localDay(),'date')}${field('Window end (inclusive)','ends_on',campaign?.ends_on||localDay(),'date')}${field('Window timezone','timezone',campaign?.timezone||browserZone)}${field('Participation needed (%)','threshold',campaign?.threshold??50,'number')}<label class="unit-field wide">Campaign award (optional)<select name="award_id"><option value="">No linked award</option>${campaignData.awards.map(a=>`<option value="${a.id}" ${campaign?.award_id===a.id?'selected':''}>${esc(a.name)}${a.archived?' · Archived':''}</option>`).join('')}</select></label></div><details class="unit-block" id="campaign-event-choice"><summary>Select events (latest 1000 available)</summary><input type="search" id="campaign-event-search" aria-label="Search campaign events" placeholder="Search event names"><div class="campaign-event-list">${events.map(e=>`<label data-event-choice><input type="checkbox" name="campaign_events" value="${e.id}" ${selected.has(e.id)?'checked':''}><span>${esc(e.name)}<small>${esc(dateTime(e.starts))} · ${esc(e.state)}${e.tracked?'':' · No attendance'}</small></span></label>`).join('')}${missing.map(id=>`<label data-event-choice><input type="checkbox" name="campaign_events" value="${id}" checked>Previously selected event #${id}</label>`).join('')}</div></details><p class="feature-note">Only this unit’s events are included. Unknown participation is unconfirmed, Reserve events count toward campaign participation, and LOA and Excused events are exempt. Finish and finalize the campaign’s tracked events before issuing awards. Editing a campaign recalculates readiness; issued medals remain until staff revoke them.</p>`,async()=>{
      const values=Object.fromEntries(new FormData(form));await write(`${base()}/campaigns`,{name:values.name,description:values.description,mode:values.mode,state:values.state,starts_on:values.starts_on,ends_on:values.ends_on,timezone:values.timezone,threshold:Number(values.threshold),award_id:values.award_id?Number(values.award_id):null,event_ids:values.mode==='manual'?[...form.querySelectorAll('[name="campaign_events"]:checked')].map(i=>Number(i.value)):[],revision,...(campaign?{id:campaign.id}:{})});
    });form.elements.name.required=true;form.elements.name.maxLength=120;form.elements.threshold.min=1;form.elements.threshold.max=100;form.elements.threshold.required=true;
    function mode(){const range=form.elements.mode.value==='range';for(const name of ['starts_on','ends_on']){form.elements[name].disabled=!range;form.elements[name].required=range;}el('campaign-event-choice').hidden=range;}
    form.elements.mode.onchange=mode;el('campaign-event-search').oninput=()=>{const query=el('campaign-event-search').value.toLowerCase();form.querySelectorAll('[data-event-choice]').forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(query));};mode();baseline=signature();
  }
  async function showCampaign(id){
    if(saving)return;const current=epoch,request=++modalRequest;
    try{const data=await read(`${base()}/campaigns/${id}`);if(current!==epoch||request!==modalRequest)return;const c=data.campaign,r=data.results;
      const canIssue=data.permissions.awards&&c.state==='completed'&&c.award_id&&r.pending===0&&r.window_closed;
      open(c.name,`<p class="reference-prose">${esc(c.description)}</p><div class="unit-summary"><span>State <strong>${esc(c.state)}</strong></span><span>Events <strong>${r.events.length}</strong></span><span>Finalized <strong>${r.finalized}</strong></span><span>Pending <strong>${r.pending}</strong></span><span>Threshold <strong>${c.threshold}%</strong></span></div>${data.permissions.campaigns?'<button type="button" id="campaign-edit">Edit campaign</button>':''}<p class="feature-note">Campaign progress uses confirmed Present / eligible finalized events. Unknown outcomes are unconfirmed and stay visible; LOA and Excused events are exempt. Finalize pending attendance and complete the campaign before approving awards.${r.window_closed?'':' The campaign date window is still open.'}</p><div class="unit-table campaign-results"><table><thead><tr><th>Member</th><th>Confirmed participation</th><th>Unconfirmed / excused</th><th>Award readiness</th></tr></thead><tbody>${r.members.map(m=>`<tr><td>${m.has_record?`<button type="button" class="member-record-link" data-campaign-member="${m.member_id}">${esc(m.game_name)}</button>`:esc(m.game_name)+' · Deleted record'}</td><td>${m.credited_present}/${m.counted} · ${m.rate===null?'—':m.rate+'%'}</td><td>${m.unknown} unknown · ${m.excused} excused</td><td>${m.awarded?'Award recorded':m.eligible?'Threshold met':'Below threshold'}${canIssue&&m.eligible&&m.has_record&&!m.awarded?`<button type="button" data-campaign-grant="${m.member_id}">Review award</button>`:''}</td></tr>`).join('')||'<tr><td colspan="4">No finalized participation records yet.</td></tr>'}</tbody></table></div><details class="unit-block"><summary>Campaign events</summary>${r.events.map(e=>`<p><strong>${esc(e.name)}</strong><small>${esc(dateTime(e.starts))} · ${esc(e.state)}${e.tracked?'':' · No attendance'}</small></p>`).join('')||'<p>No matching events.</p>'}</details>`);
      el('campaign-edit')?.addEventListener('click',()=>campaignEditor(c,data.revision));
      form.querySelectorAll('[data-campaign-grant]').forEach(b=>b.onclick=()=>issueAward(Number(b.dataset.campaignGrant),c.award_id,c));
      form.querySelectorAll('[data-campaign-member]').forEach(b=>b.onclick=()=>{dialog.close();document.dispatchEvent(new CustomEvent('unit-open-member',{detail:Number(b.dataset.campaignMember)}));});
    }catch(error){message(error.message);}
  }

  async function loadAnalytics(){
    if(!context)return;const current=epoch,request=++analyticsRequest;
    const query=new URLSearchParams({start:el('analytics-start').value,end:el('analytics-end').value,timezone:el('analytics-zone').value});
    const data=await read(`${base()}/analytics?${query}`);if(current!==epoch||request!==analyticsRequest)return;
    const measured=data.strength.filter(d=>d.total!==null), peak=Math.max(0,...measured.map(d=>d.total)),max=Math.max(1,peak);
    const points=measured.map((d,i)=>`${20+i/Math.max(1,measured.length-1)*760},${180-d.total/max*150}`).join(' ');
    const dots=measured.map((d,i)=>`<circle cx="${20+i/Math.max(1,measured.length-1)*760}" cy="${180-d.total/max*150}" r="3" fill="var(--accent)"><title>${d.day}: ${d.total} members</title></circle>`).join('');
    const last=measured.at(-1),moves=data.movements;
    el('unit-analytics-content').innerHTML=`<div class="unit-summary"><span>Roster at period end <strong>${last?.total??'—'}</strong></span><span>Added <strong>${moves.added||0}</strong></span><span>Archived <strong>${moves.archived||0}</strong></span><span>Removed <strong>${moves.removed||0}</strong></span><span>Restored <strong>${moves.restored||0}</strong></span><span>Cohort retention <strong>${data.retention===null?'—':data.retention+'%'}</strong></span></div><p class="feature-note">Strength tracking began ${data.tracking_since?esc(dateTime(data.tracking_since)):'with this feature'}. Earlier dates have no inferred strength. Retention means ${data.retained} of ${data.cohort} members present at the measured starting point remained on the roster at period end; returning members count as retained. Additions/removals describe panel roster changes, not inferred real-world enlistment dates.</p><div class="unit-dashboard-grid"><section class="unit-block"><h2>Recorded unit strength</h2>${measured.length?`<svg class="strength-chart" viewBox="0 0 800 210" role="img" aria-label="Unit strength trend from ${esc(measured[0].day)} to ${esc(last.day)}, ending at ${last.total} members"><line x1="20" y1="180" x2="780" y2="180" stroke="currentColor" opacity=".3"/><polyline fill="none" stroke="var(--accent)" stroke-width="3" points="${points}"/>${dots}<text x="20" y="18" fill="currentColor">Peak: ${peak} members</text><text x="20" y="205" fill="currentColor">${esc(measured[0].day)}</text><text x="650" y="205" fill="currentColor">${esc(last.day)}</text></svg>`:'<p>No strength history in this period.</p>'}<details><summary>Daily strength data</summary><div class="unit-table analytics-table"><table><thead><tr><th>Date</th><th>Active</th><th>Reserve</th><th>LOA</th><th>Total</th></tr></thead><tbody>${data.strength.map(d=>`<tr><td>${d.day}</td><td>${d.active??'—'}</td><td>${d.reserve??'—'}</td><td>${d.loa??'—'}</td><td>${d.total??'—'}</td></tr>`).join('')}</tbody></table></div></details></section><section class="unit-block"><h2>Finalized attendance trend</h2><p class="feature-note">Rates count expected, finalized Present/Absent decisions. Unknown and Excused are excluded. Present totals also show optional participation.</p>${data.turnout.map(e=>`<div class="turnout-row"><strong>${esc(e.name)}</strong><small>${esc(new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeZone:data.timezone}).format(new Date(e.starts*1000)))} · ${e.present} present · ${e.unknown} unknown</small><progress max="100" value="${e.rate??0}" aria-label="${esc(e.name)} attendance rate"></progress><span>${e.rate===null?'No counted decisions':e.rate+'%'} · ${e.counted} counted</span></div>`).join('')||'<p>No finalized attendance in this period.</p>'}</section><section class="unit-block"><h2>Current rank distribution</h2>${data.ranks.map(r=>`<p>${esc([r.rank_track,r.rank].filter(Boolean).join(' · ')||'No rank assigned')} <strong>${r.n}</strong></p>`).join('')||'<p>No current roster members.</p>'}</section></div>`;
  }
  async function refresh(){
    if(!context)return;
    const tab=document.querySelector('[data-unit-tab][aria-selected="true"]')?.dataset.unitTab;
    const actions={references:[loadReferences,'reference-grid'],awards:[loadAwards,'award-history'],campaigns:[loadCampaigns,'campaign-list'],analytics:[loadAnalytics,'unit-analytics-content']};
    const action=actions[tab];if(!action)return;
    const current=epoch,region=el(action[1]);region.setAttribute('aria-busy','true');
    try{await action[0]();}catch(error){if(current===epoch)UnitUX.error(region,error,refresh);}finally{if(current===epoch)region.setAttribute('aria-busy','false');}
  }
  document.addEventListener('unit-section-changed',()=>refresh());
  document.addEventListener('unit-loaded',e=>{epoch++;modalRequest++;if(dialog.open&&!saving)dialog.close();const changed=context?.unitId!==e.detail.unitId;context=e.detail;nextAward=null;nextReference=null;referenceData=awardData=campaignData=null;for(const id of ['reference-new','award-new','award-issue','campaign-new'])el(id).hidden=true;if(changed){selectedFolder='';el('reference-publication').value='';el('reference-archived').value='0';el('reference-category').replaceChildren(new Option('All categories',''));el('award-member').replaceChildren(new Option('All members',''));for(const id of ['reference-grid','award-catalog','award-history','campaign-list','unit-analytics-content'])el(id).textContent='Loading…';}refresh();});
  document.addEventListener('unit-open-reference',async e=>{try{await loadReferences();await showReference(e.detail.id,null,!!e.detail.published);}catch(error){message(error.message);}});
  document.addEventListener('unit-issue-award',e=>issueAward(e.detail));
  el('reference-sops').onclick=()=>{kind='sop';selectedFolder='';el('reference-publication').value='';el('reference-sops').setAttribute('aria-pressed','true');el('reference-loadouts').setAttribute('aria-pressed','false');el('reference-category').value='';loadReferences().catch(e=>UnitUX.error(el('reference-grid'),e,loadReferences));};
  el('reference-loadouts').onclick=()=>{kind='loadout';selectedFolder='';el('reference-publication').value='';el('reference-sops').setAttribute('aria-pressed','false');el('reference-loadouts').setAttribute('aria-pressed','true');el('reference-category').value='';loadReferences().catch(e=>UnitUX.error(el('reference-grid'),e,loadReferences));};
  let searchTimer;el('reference-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadReferences().catch(e=>UnitUX.error(el('reference-grid'),e,loadReferences)),250);};
  for(const id of ['reference-category','reference-archived','reference-sort','reference-publication'])el(id).onchange=()=>loadReferences().catch(e=>UnitUX.error(el('reference-grid'),e,loadReferences));
  el('reference-more').onclick=()=>loadReferences(true).catch(e=>UnitUX.error(el('reference-grid'),e,()=>loadReferences(true)));el('reference-new').onclick=()=>referenceEditor();
  el('award-new').onclick=()=>awardEditor();el('award-issue').onclick=()=>issueAward();el('award-member').onchange=()=>loadAwards().catch(e=>UnitUX.error(el('award-history'),e,loadAwards));el('awards-refresh').onclick=()=>loadAwards().catch(e=>UnitUX.error(el('award-history'),e,loadAwards));el('award-more').onclick=()=>loadAwards(true).catch(e=>UnitUX.error(el('award-history'),e,()=>loadAwards(true)));
  el('campaign-new').onclick=()=>campaignEditor();el('campaign-state').onchange=()=>loadCampaigns().catch(e=>UnitUX.error(el('campaign-list'),e,loadCampaigns));el('campaign-refresh').onclick=()=>loadCampaigns().catch(e=>UnitUX.error(el('campaign-list'),e,loadCampaigns));
  el('analytics-refresh').onclick=()=>loadAnalytics().catch(e=>UnitUX.error(el('unit-analytics-content'),e,loadAnalytics));
})();
