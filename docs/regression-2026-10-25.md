# Local regression pass — 25 October 2026

The recorded runtime results below precede the subsequent formation-placement and Staff-created Member login changes. Those additions have syntax/static checks only so far; these results must not be read as coverage of the new workflows.

## Result

The targeted unit/SOP workflows pass in isolated application instances. The broad backend suite is still failing and requires follow-up before 1.0.

| Check | Result |
| --- | --- |
| Unit self-service and existing unit regression cases on Flask 3.1.2 / Werkzeug 3.1.9 | 19 passed |
| Self-service compatibility cases on Flask 2.2.5 / Werkzeug 2.3.8 | 11 passed |
| Existing Node frontend regressions | Passed |
| JSDOM navigation, attention strip, SOP upload/acknowledgement and shared-dialog checks | Passed |
| Initial broad Python discovery run | 235 run; 15 failures and 10 errors |

The broad result precedes the final additional attachment/targeting cases. Counts include duplicate discovery of `PanelTests` imported by other test modules. The broad suite has not been made green by this pass.

## Exercised workflows

- Member, Staff and Unit administrator navigation; role-specific pages; mobile menu state.
- Full-width fleet landing page, panel-users shortcut, derived disk/status alerts, action targets and clearing resolved alerts.
- Shared dialog save locking, error display and unsaved-change guards.
- Frontend PDF-only SOP submission, multipart payload, default Draft state and completion.
- PDF, Word and image backend uploads, size/type rejection, CSRF and download headers.
- Draft/published copies, version inspection, restoration as Draft, template copies with distinct attachment IDs.
- Draft attachment privacy while an older publication remains available; attachment access after publication.
- Cross-unit isolation, Member restrictions, unit administrator login creation and own-profile field filtering.
- Required-reading audiences, acknowledgement of the shown publication and rejection of stale publication tokens.
- RSVP isolation, invalidation after event edits, and unchanged attendance outcomes.
- Announcement privacy and staff document review reminders.
- Actual loopback HTTP server: login, cookie session, unit HTML and published SOP access, with another unit rejected.

## Product fix

Required-reading position matching treated a semicolon-separated position list as one name. It now matches each individual position, alongside primary billet and qualification targets. A regression case covers both positions in a multi-position record and its qualification assignment.

## Test maintenance

Updated obsolete assertions for the removed fleet sidebar, the current account editor, fixed unit roles and shared request/confirmation helpers. Member restrictions are exercised directly rather than modeling a read-only Staff role that no longer exists.

## Broad-suite follow-up

- Workshop preview cases raise `KeyError: size` with metadata fixtures lacking a size field. Reconcile optional metadata handling and the preview contract.
- Legacy preset cases fail against the consolidated preset payload/scope behavior. Reconcile compatibility expectations and endpoint behavior.
- Port validation cases report occupied ports in the restricted execution environment. Repeat them with socket access before classifying a product fault.
- Direct `start_server()` cases run without a Flask application context and fail on `g`; establish the helper's supported calling context.
- An RCON case exhausts its mocked packet sequence; reconcile the fixture with the receiver's current completion behavior.
- Two temporary-directory cleanups race background activity; provide fixture shutdown before deleting directories.
- Theme and launch-argument expectations still specify the old Tactical default and omit the approved `-noSound` default.

## Remaining live checks

No connected browser or production VM was available. JSDOM checks DOM behavior; real desktop/mobile rendering, native dialog behavior, theme contrast, systemd lifecycle, real game servers, Workshop downloads and production backup restoration remain unverified. Release worklist items remain open for these checks.
