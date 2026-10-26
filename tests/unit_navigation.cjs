// DOM-level checks; JSDOM does not verify browser layout or native focus trapping.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const root = path.join(__dirname, '..');
const source = (name) =>
  fs.readFileSync(path.join(root, 'static', name), 'utf8');
const tick = () => new Promise((resolve) => setTimeout(resolve, 10));

async function workspace(role) {
  const dom = new JSDOM(
    fs.readFileSync(path.join(root, 'units.html'), 'utf8'),
    {
      url: 'https://panel.test/units',
      runScripts: 'outside-only',
      pretendToBeVisual: true,
    },
  );
  const win = dom.window,
    errors = [];
  win.addEventListener('error', (e) => errors.push(e.error || e.message));
  // Layout is not modeled here; disable scroll-hint animation scheduling.
  win.requestAnimationFrame = () => 0;
  win.cancelAnimationFrame = () => {};
  win.HTMLElement.prototype.scrollIntoView = function () {};
  win.HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  win.HTMLDialogElement.prototype.close = function () {
    this.open = false;
    this.dispatchEvent(new win.Event('close'));
  };
  win.confirm = () => true;
  win.URL.createObjectURL = () => 'blob:test-upload';
  win.URL.revokeObjectURL = () => {};
  win.Headers = Headers;
  win.Request = Request;
  const unit = {
    id: 1,
    name: 'Alpha',
    revision: 1,
    catalog: { certificates: [], positions: [], rank_structures: [] },
    branding: {},
  };
  const staff = role !== 'member',
    admin = role === 'admin';
  const listing = {
    units: [{ id: 1, name: 'Alpha', role, servers: [] }],
    servers: [],
    panel_admin: false,
    hosting_access: false,
    user_id: 2,
  };
  const detail = {
    unit,
    role,
    structure: [],
    roster: [],
    staff: [],
    accounts: [],
    can_edit: staff,
    can_staff: admin,
    can_delete: admin,
    can_settings: false,
  };
  const home = {
    reading: [],
    announcements: [],
    announcement_history: [],
    events: [],
    reviews: [],
    review_due: 0,
    can_manage: staff,
    can_events: staff,
    profile_linked: false,
    revision: 1,
    today: '2026-10-25',
  };
  const documentItem = {
    id: 5,
    kind: 'sop',
    title: 'Procedure',
    category: 'General',
    body: '# Purpose\nRead this version',
    folder: '',
    status: 'published',
    slots: [],
    related: '[]',
    url: '',
    image_url: '',
    archived: 0,
    updated_at: 100,
    updated_by: 'staff',
  };
  home.reading = [
    {
      id: 5,
      title: 'Procedure',
      publication: 'version-one',
      acknowledged_at: null,
      due: '',
    },
  ];
  const calls = [],
    uploads = [];
  win.fetch = async (input, options = {}) => {
    const url = new URL(String(input), win.location.href);
    calls.push(url.pathname);
    let data;
    if (url.pathname === '/api/csrf') data = { csrf: 'test-token' };
    else if (
      url.pathname === '/api/units/1/library' &&
      options.method === 'POST'
    ) {
      uploads.push(options.body);
      data = { ok: true, id: 9 };
    } else if (url.pathname === '/api/units/1/reading/5/acknowledge') {
      assert.equal(JSON.parse(options.body).publication, 'version-one');
      home.reading[0].acknowledged_at = 100;
      data = { ok: true };
    } else if (url.pathname === '/api/units/1/library')
      data = {
        items: [{ ...documentItem, excerpt: 'Read this version' }],
        next_offset: null,
        categories: ['General'],
        folders: [{ folder: '', count: 1 }],
        documents: [{ id: 5, title: 'Procedure', folder: '' }],
        templates: [],
        events: [],
        member: !staff,
        permissions: { references: staff },
        revision: 1,
      };
    else if (url.pathname === '/api/units/1/library/5')
      data = {
        item: documentItem,
        files: [],
        events: [],
        related: [],
        history: [],
        revision: 1,
        permissions: { references: staff },
        published_view: !staff || url.searchParams.has('published'),
        acknowledgement: { ...home.reading[0] },
      };
    else if (url.pathname === '/api/me')
      data = {
        username: 'user',
        permissions: ['view'],
        panel_permissions: ['view'],
      };
    else if (url.pathname === '/api/units') data = listing;
    else if (url.pathname === '/api/units/1') data = detail;
    else if (url.pathname === '/api/units/1/member-home') data = home;
    else if (url.pathname === '/api/units/1/my-profile')
      data = {
        member: null,
        attendance: [],
        qualifications: [],
        positions: [],
      };
    else throw new Error('Unexpected request: ' + url.pathname);
    return { ok: true, status: 200, json: async () => structuredClone(data) };
  };
  for (const name of [
    'api.js',
    'ui.js',
    'unit-ux.js',
    'unit-resources.js',
    'unit-members.js',
    'unit-structure.js',
    'units.js',
  ])
    win.eval(source(name));
  for (
    let i = 0;
    i < 30 && win.document.getElementById('unit-workspace').hidden;
    i++
  )
    await tick();
  await tick();
  assert.equal(
    win.document.getElementById('unit-workspace').hidden,
    false,
    win.document.getElementById('units-feedback').textContent,
  );
  assert.equal(errors.length, 0, errors.map(String).join('\n'));
  return { dom, win, calls, errors, uploads };
}

async function fleetLanding() {
  const dom = new JSDOM(
    fs.readFileSync(path.join(root, 'servers.html'), 'utf8'),
    {
      url: 'https://panel.test/servers',
      runScripts: 'outside-only',
      pretendToBeVisual: true,
    },
  );
  const win = dom.window,
    doc = win.document;
  let diskFree = 10,
    unavailable = false,
    storageClicks = 0;
  await new Promise((resolve) => {
    if (doc.readyState === 'loading')
      doc.addEventListener('DOMContentLoaded', resolve, { once: true });
    else resolve();
  });
  win.Headers = Headers;
  win.Request = Request;
  win.fetch = async (input) => {
    const pathname = new URL(String(input), win.location.href).pathname;
    let data;
    if (pathname === '/api/me')
      data = {
        username: 'admin',
        panel_permissions: ['users', 'admin_config'],
      };
    else if (pathname === '/api/servers')
      data = {
        servers: [
          { id: 'alpha', name: 'Alpha', state: 'ready', permissions: ['view'] },
        ],
      };
    else if (pathname === '/api/units') data = { units: [] };
    else if (pathname === '/api/host-metrics')
      data = {
        cpu_host: 10,
        ram_total: 16000,
        ram_used: 1000,
        disk_total: 100,
        disk_free: diskFree,
      };
    else if (pathname === '/api/status')
      return {
        ok: !unavailable,
        status: unavailable ? 503 : 200,
        json: async () =>
          unavailable
            ? { error: 'Status query unavailable' }
            : { running: false, server_name: 'Alpha', scenario_id: 'test' },
      };
    else if (pathname === '/api/scenario-preview')
      data = { status: 'unavailable' };
    else throw new Error('Unexpected fleet request: ' + pathname);
    return { ok: true, status: 200, json: async () => data };
  };
  try {
    doc
      .getElementById('overview-storage')
      .addEventListener('click', () => storageClicks++);
    for (const name of ['api.js', 'servers.js']) win.eval(source(name));
    doc.dispatchEvent(new win.Event('DOMContentLoaded'));
    for (
      let i = 0;
      i < 30 &&
      !doc
        .getElementById('overview-feedback')
        .textContent.startsWith('Updated');
      i++
    )
      await tick();
    const strip = doc.getElementById('overview-alerts');
    assert.equal(doc.getElementById('fleet-panel-users').hidden, false);
    assert.equal(doc.getElementById('fleet-sidebar'), null);
    assert.equal(
      strip.hidden,
      false,
      doc.getElementById('overview-feedback').textContent,
    );
    assert.match(strip.textContent, /disk space below 20%/);
    strip.querySelector('button').click();
    assert.equal(storageClicks, 1);
    diskFree = 50;
    doc.getElementById('overview-refresh').click();
    await tick();
    await tick();
    assert.equal(strip.hidden, true);
    assert.equal(doc.getElementById('overview-alert-count').textContent, '0');
    unavailable = true;
    doc.getElementById('overview-refresh').click();
    await tick();
    await tick();
    assert.equal(strip.hidden, false);
    assert.match(strip.textContent, /Status query unavailable/);
    assert.equal(
      strip.querySelector('a').getAttribute('href'),
      '/?server=alpha',
    );
    console.log(
      'Fleet attention derives real status/disk alerts, hides when clear and opens the matching action',
    );
  } finally {
    win.close();
  }
}

(async () => {
  await fleetLanding();
  for (const role of ['member', 'staff', 'admin']) {
    const { dom, win, calls, errors, uploads } = await workspace(role),
      doc = win.document;
    try {
      const visible = [...doc.querySelectorAll('[data-unit-tab]')]
        .filter((b) => !b.hidden)
        .map((b) => b.dataset.unitTab);
      if (role === 'member') {
        assert.deepEqual(visible, ['home', 'profile', 'references']);
        assert.equal(
          doc.querySelector('[aria-selected="true"]').dataset.unitTab,
          'home',
        );
        assert.match(
          doc.getElementById('member-home-content').textContent,
          /Required reading/,
        );
        doc.querySelector('[data-member-sop]').click();
        await tick();
        await tick();
        assert.equal(doc.getElementById('resource-dialog').open, true);
        doc.getElementById('reference-acknowledge').click();
        await tick();
        await tick();
        assert.equal(
          doc.getElementById('reference-acknowledge').textContent,
          'Acknowledged this version',
        );
        doc.getElementById('resource-close').click();
        doc.getElementById('unit-tab-profile').click();
        await tick();
        assert.match(
          doc.getElementById('member-profile-content').textContent,
          /no linked roster member/,
        );
        assert(
          !calls.some((url) => /roster-tools|attendance|operations/.test(url)),
        );
      } else {
        assert(
          visible.includes('roster') &&
            visible.includes('events') &&
            visible.includes('references'),
        );
        assert.equal(visible.includes('staff'), role === 'admin');
        assert.equal(visible.includes('customization'), role === 'admin');
        doc.getElementById('unit-tab-home').click();
        await tick();
        assert.match(
          doc.getElementById('member-home-content').textContent,
          /SOP review reminders/,
        );
        doc.getElementById('unit-tab-references').click();
        await tick();
        doc.getElementById('reference-new').click();
        assert.equal(doc.getElementById('resource-dialog').open, true);
        doc.getElementById('resource-form').elements.title.value =
          'PDF only SOP';
        const input = doc.getElementById('sop-files');
        Object.defineProperty(input, 'files', {
          value: [
            new win.File(['%PDF-1.4 example'], 'manual.pdf', {
              type: 'application/pdf',
            }),
          ],
          configurable: true,
        });
        input.dispatchEvent(new win.Event('change'));
        assert.match(
          doc.getElementById('sop-pending-files').textContent,
          /manual.pdf/,
        );
        doc
          .getElementById('resource-form')
          .dispatchEvent(
            new win.Event('submit', { cancelable: true, bubbles: true }),
          );
        await tick();
        await tick();
        assert.equal(uploads.length, 1);
        assert.equal(JSON.parse(uploads[0].get('data')).status, 'draft');
        assert.equal(
          [...uploads[0].values()].filter((value) => value instanceof win.File)
            .length,
          1,
        );
        assert.equal(doc.getElementById('resource-dialog').open, false);
      }
      doc.getElementById('unit-nav-toggle').click();
      assert.equal(
        doc.getElementById('unit-nav-toggle').getAttribute('aria-expanded'),
        'true',
      );
      doc.dispatchEvent(new win.KeyboardEvent('keydown', { key: 'Escape' }));
      assert.equal(
        doc.getElementById('unit-nav-toggle').getAttribute('aria-expanded'),
        'false',
      );
      assert.equal(errors.length, 0, errors.map(String).join('\n'));
      console.log('Unit sidebar, member pages and mobile toggle:', role);
    } finally {
      dom.window.close();
    }
  }
  const { dom, win } = await workspace('member');
  try {
    const dialog = win.document.getElementById('resource-dialog'),
      body = win.document.getElementById('resource-body');
    win.UnitUX.prepare(dialog, {
      title: 'Example',
      body,
      content: '<label>Name<input name="example"></label>',
    });
    assert.equal(dialog.open, true);
    assert.equal(
      win.document.getElementById('resource-title').textContent,
      'Example',
    );
    const save = win.document.getElementById('resource-save');
    let complete;
    const pending = win.UnitUX.save(
      dialog,
      () =>
        new Promise((resolve) => {
          complete = resolve;
        }),
      () => {},
    );
    assert.equal(save.disabled, true);
    complete();
    await pending;
    assert.equal(save.disabled, false);
    await win.UnitUX.save(
      dialog,
      async () => {
        throw new Error('Upload failed');
      },
      () => {},
    );
    assert.equal(
      win.document.getElementById('resource-error').textContent,
      'Upload failed',
    );
    let dirty = true;
    win.UnitUX.registerDraft({
      dirty: () => dialog.open && dirty,
      discard: () => {
        dirty = false;
      },
    });
    win.confirm = () => false;
    assert.equal(win.UnitUX.close(dialog), false);
    assert.equal(dialog.open, true);
    win.confirm = () => true;
    assert.equal(win.UnitUX.close(dialog), true);
    assert.equal(dialog.open, false);
    console.log(
      'Shared dialogs preserve save locking, errors and unsaved-change guards',
    );
  } finally {
    dom.window.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
