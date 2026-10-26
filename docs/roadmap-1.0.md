# FIELDHQ 1.0 worklist

Saved 25 October 2026. This list records the revised release priorities; it is not a claim that verification has been completed. UI consistency is the immediate task before taking on more additions.

## Before calling it 1.0

- [ ] Verify production workflows: fresh installation, updating, server creation, starting, stopping and removal.
- [ ] Verify backup restoration: panel accounts, units, configurations and saves.
- [ ] Verify unit isolation: members and staff cannot access another unit’s records or files.
- [ ] Verify member permissions: profiles, reading, RSVPs, uploads and published-versus-draft access.
- [ ] Finish account recovery: scoped password resets and mandatory password changes after resets.
- [ ] Provide reliable job visibility: consistent progress, errors and results for long operations.
- [ ] Make preflight failures actionable: explain why a server cannot start and where to fix it.
- [ ] Establish crash recovery behavior: prevent restart loops and show what happened; assess systemd’s existing behavior first.
- [ ] Improve player detection reliability: distinguish empty servers, unavailable queries and stale readings.
- [ ] Finish persistence and save recovery: understandable selection, backup and restoration.
- [ ] Make errors consistent: useful messages instead of generic HTTP failures, preserving entered data.
- [ ] Complete UI consistency: navigation, dialogs, buttons, spacing, loading states, mobile layouts and theme readability.
- [ ] Reconcile documentation with shipped behavior.
- [ ] Identify releases: actual installed version/commit and a clear changelog.

## Useful additions after those are solid

- [ ] Attachment management: replace/remove current attachments and manage retained storage.
- [ ] Reading compliance dashboard: outstanding acknowledgements by member and assignment.
- [ ] Event change notices: cancellations, rescheduling and invalidated RSVPs.
- [ ] Disk capacity warnings before downloads or storage exhaustion.
- [ ] Maintenance mode: pause scheduled actions and identify intentionally unavailable servers.
- [ ] Unit activity view using existing audit history.
- [ ] Connection information card: joining instructions and required mods.
- [ ] First-use checklist for administrators.

## Defer beyond 1.0

- Qualification expiry and renewal workflows.
- Member correction requests.
- Search across every unit resource.
- Long-term performance history.
- Additional game support.
- Further role customization.

## Consolidation decisions

Extend existing jobs, preflight checks, notifications, scheduling, configuration previews, scenario/mod handling, moderation and audit history. Combine backups and guided restoration into one recovery workflow. Combine password resets and forced password changes into one account recovery feature.

## Immediate navigation direction

- Server workspaces and unit workspaces should share sidebar styling and interaction patterns.
- All Servers should be a full-width landing page for authorized server/panel administrators, without a server workspace sidebar.
- Keep role-based access and unit isolation intact.
- Approved design: all permitted unit pages remain visible beneath sidebar headings. All Servers keeps its counters, table and charts. Hosting / Units remain in the top bar, with Help and account controls on the right.
- Attention strip: real server errors, unavailable status and disk free below 20%, each with an action. Hide it when clear. Restart-needed and active-job indicators require reliable data before being added.

## Local regression progress

The [25 October local regression report](regression-2026-10-25.md) records passing targeted backend, compatibility, DOM and HTTP checks, one repaired reading-audience bug, and unresolved broad-suite failures. Reconcile those failures and complete browser/production verification before marking the release checks complete.
