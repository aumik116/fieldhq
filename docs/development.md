# Developing FIELDHQ

## Unit module boundaries

- `units.py`: unit access policy, rosters, account links, structure and startup wiring. Its established `text`, role and UUID imports remain available for compatibility.
- `unit_common.py`: shared actor names, role capabilities, resource validation/auditing and reference serialization. Role helpers do not replace the unit access checks at route boundaries.
- `unit_sops.py`: SOP/loadout schema and migration, document routes, publishing, revision history and attachments.
- `unit_resources.py`: awards, campaigns and measured roster analytics.
- `unit_members.py`: member self-service, required-reading acknowledgements, document reviews, announcements and RSVPs.
- `unit_events.py`: staff events and UUID attendance.
- `roster_tools.py`: qualification history, promotion reviews and bulk roster changes.

Unit startup registers resource schemas, event hooks, roster hooks, member self-service and SOP routes explicitly. Installers return the functions needed by their callers. SOP routes receive their required-reading function directly; roster tools receive the strength and event-roster functions directly. Do not restore implicit `api` assignments for these internal dependencies.

Keep all unit SQL scoped to its unit. Keep member responses explicit about which fields are public; staff notes and drafts must not enter those responses. Use the existing published-value snapshot for published documents, `publication_digest()` for version acknowledgements and `decode_reference()` for reader serialization.

## UI conventions

`static/unit-ux.js` provides the shared unit dialog operations:

- `prepare`: install a title, body, save label and visibility, then open/focus the dialog.
- `save`: disable Save while the action runs and consistently display failures.
- `close`: respect the registered busy/unsaved guards.

Callers retain their feature-specific save actions, draft signatures and refresh behavior. Register upload state in the draft signature where needed. `static/ui.js` remains the shared panel confirmation and mod-review utility used outside the unit workspace.

Unit and server navigation share sidebar styling; All Servers is a full-width landing page. Theme overrides are intentional. Remove obsolete rules instead of appending a competing override for an abandoned layout. Preserve CSS rule order when formatting or consolidating it.

## Source formatting

Formatting tools are development-only; the production installation needs neither Node nor Black. The checked-in Prettier configuration preserves HTML whitespace and leaves embedded template contents alone. Generated manuals and vendor assets are excluded.

```bash
npx prettier@3.6.2 --write static/unit-ux.js static/unit-resources.js static/unit-events.js static/unit-members.js static/units.js static/roster-tools.js static/servers.js static/user-editor.js static/panel.css units.html servers.html index.html
python3 -m black unit_common.py unit_sops.py units.py unit_resources.py unit_members.py unit_events.py roster_tools.py
```

New Python runtime modules must be added to `PANEL_PY_FILES` in `install.sh`, so fresh installations and updates deploy the same files. When shared JavaScript interfaces change, update the relevant script cache versions together.
