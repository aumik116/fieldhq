# FIELDHQ

**Self-hosted Arma Reforger server management and unit administration.**

FIELDHQ brings hosting operations and personnel records into one web panel. Run multiple Reforger servers on one Ubuntu host, and manage separate units with their own rosters, events, attendance, qualifications and promotion rules.

The project grew from [Mateusz Gołębiewski's Arma Reforger panel](https://github.com/mateuszgolebiewski-code/arma-reforger-panel). FIELDHQ keeps that history and attribution while developing its own interface and workflows. See [credits and project history](ATTRIBUTION.md).

## Two workspaces

### Server management

- **All servers:** fleet counters, server search/filtering, resource charts and visible server actions.
- **Server dashboard:** players/AI/vehicles, CPU, memory, host network traffic, simulation FPS, console and storage.
- **Creation and cloning:** separate installations, configuration, ports and saves; reusable local game downloads.
- **Workshop mods:** browsing, dependencies, version pins, bulk removal, downloaded-file inventory and list comparisons.
- **Addition queue:** review pending additions and size estimates before saving. Latest is the default, with a choice when an accessible running server has a matching pin.
- **Automatic local reuse:** independent mod copies using copy-on-write where supported, with normal copies/downloads as fallback.
- **Presets:** mods only, scenario + mods, or a full supported gameplay setup, with a change review.
- **Player tools:** live roster, recorded identities, observed sessions, moderation and announcements.
- **Operations:** scheduled controls, warned restarts, software updates, configuration backups, files and persistence tools.
- **Storage:** measured usage, free-space counters and cleanup of recognized retained server folders.

### Unit management

- Independent units, linked servers and staff assignments.
- Flat rosters or groups/sections/billets, with open-slot counts and one primary billet per member.
- Member records, staff notes, game names, Discord handles, recorded UUIDs and optional linked panel accounts.
- Active, Reserve and LOA statuses, joined dates, archiving and CSV export.
- Qualifications with dates/issuers, separate rank structures and promotion eligibility notices. Promotions require staff approval.
- Timezone-aware events, recurring occurrences, UUID-based event attendance, corrections and finalization.
- SOPs/loadouts, awards, campaigns, personnel timelines and recorded analytics.
- Unit icons, banners and descriptions.

Roster members do not need panel logins. Unit records remain separate even when the same person belongs to several units.

## Manuals and in-panel Help

| Guide | Read online | Download |
| --- | --- | --- |
| Server management | [Markdown](docs/server-management-manual.md) | [PDF](docs/server-management-manual.pdf) |
| Unit staff | [Markdown](docs/unit-staff-manual.md) | [PDF](docs/unit-staff-manual.pdf) |
| Full manual | [Markdown](docs/user-manual.md) | [PDF](docs/user-manual.pdf) |
| Installation, networking and recovery | [Operations guide](docs/operations.md) | — |

Choose **Help** in the panel header for guidance on the current server tab or unit page. All three manuals are available at `/help`, with a contents sidebar, section highlighting, text search and PDF downloads.

## Install

Use **Ubuntu 24.04, x86_64**, a sudo account and sufficient storage for each server's game files, mods and saves. The installer prepares the panel, dependencies, SteamCMD and server services.

Clone FIELDHQ into a new checkout for a fresh installation:

```bash
git clone https://github.com/aumik116/fieldhq.git fieldhq
cd fieldhq
sudo bash install.sh
```

1. Choose the service user, initial panel password and panel TCP port. Defaults are `arma` and `8888`.
2. Open `http://YOUR_VM_IP:8888` and sign in as **admin** using the chosen password.
3. Choose **All servers → New server**, review the settings and select **Create and start server**.
4. Follow installation/startup output, then confirm the mission loads and players can join.

The initial installer sets up the panel. Game software is downloaded when you create a server. `--panel-only` is an alias for this panel-first flow.

Creation can copy an accessible server's settings and mod selections. Credentials, game administrator assignments and saves are excluded. Blank custom ports use automatic allocation. A public IPv4 address advertises an endpoint; it does not configure firewall rules or NAT.

## Update an existing installation

Run from your existing checkout; there is no need to move installed servers or rename their folders:

```bash
git fetch origin
git switch main
git pull --ff-only
sudo bash install.sh --update
```

Updates preserve accounts, settings and registered servers, including supported legacy installations. The panel service restarts; game servers are not deliberately restarted by the panel update. Wait for provisioning and software jobs to finish first.

Updates create recovery snapshots under `/var/backups/arma-panel/`. Failed updates attempt to restore panel files and service settings. Automatic rollback does not rewind the live database or game saves. See [backup and recovery](docs/operations.md#backup-and-recovery).

The main development branch is **`main`**; it includes the former multi-server work.

### Switch an existing production checkout to FIELDHQ

Keep your current checkout and installed paths. After `aumik116/fieldhq` has been
published with the preserved history, follow the [production migration guide](docs/migrate-to-fieldhq.md).
Do not run the fresh installer or create replacement server instances just to switch repositories.

## Access and roles

**Hosting access** is assigned separately for each server, or explicitly for all servers. Server roles remain Viewer, Operator, Manager and Administrator. Panel administration controls accounts and panel-wide setup; the original owner remains protected.

**Unit access has only two roles:**

| Unit role | Access within assigned units |
| --- | --- |
| Staff | Rosters, notes, primary assignments, qualifications, promotion reviews, events, attendance, references, awards and campaigns |
| Unit administrator | All Staff functions, plus staff access, rank rules/catalogs, structure, branding and permanent member deletion |

There are no individual unit permission checkboxes. Existing Staff assignments receive the standard Staff role on upgrade. Unit membership, server linking and roster/account linking do not grant hosting access.

Accounts use the same login page. Unit-only staff land in the unit workspace. Panel administrators create login accounts; unit administrators can assign existing accounts to their units.

## Appearance

The eight themes are **Slate** (default), **Field Desk**, **Operations**, **Tactical**, **Original**, **Field**, **Forest** and **Light**. All share the same page layout and features. Original adds square corners and firmer borders to its classic amber palette. Field uses dark olive navigation and light parchment content. Former Ocean preferences move to Slate.

Theme preferences are saved per account. Unit branding is configured separately under **Administration → Customization**.

## Operational limits

- Hosting currently supports **Arma Reforger on one local host**. Remote nodes, Arma 3 and DayZ hosting are not implemented.
- The panel does not configure UFW, router forwarding or NAT. Use an HTTPS reverse proxy for remote panel access. Keep RCON on loopback/private networking; do not expose it publicly.
- Broadcasts and scheduled player warnings need working admin RCON and Server Admin Tools `#message` support. Failed/missed required warnings skip scheduled disruptive operations.
- The Linux panel service must remain running for schedules, player-history collection and automatic attendance; the browser need not remain open.
- Attendance counts a linked UUID observed during a tracked event. Sampling can miss brief connections. Collector gaps remain visible and missing evidence does not automatically mark someone absent.
- Player-session times are observed estimates, not exact connection logs. Older first/last-seen data cannot reconstruct past sessions.
- Fleet chart history covers up to 30 minutes while the page is open and resets on reload. Storage scans are bounded and cached; logical file sizes can differ from physical disk use with copy-on-write.
- Configuration backups are not full server, save or database backups. Persistence save selection/named backups and fresh-install/Steam/systemd behavior still need real-server validation before relying on them in production.
- Recruiting, Discord account integration, shared-server reservations and joint-unit attendance workflows are not implemented. Server notification webhooks are a separate existing feature.

## Service checks and owner recovery

The existing service names are retained for compatibility:

```bash
sudo systemctl status arma-panel.service
sudo journalctl -u arma-panel.service -n 50 --no-pager
sudo systemctl status arma-server@training.service
```

Replace `training` with your server ID. Supported unmanaged installations use `arma-server.service`.

To reset the owner's password from an updated checkout on the host:

```bash
sudo bash install.sh --reset-owner-password
```

This requires local sudo access and invalidates existing owner sessions. See the [operations guide](docs/operations.md) for troubleshooting and recovery.

## Development and documentation

This is a Flask/Python application with browser JavaScript and CSS. Existing automated checks are documented in the [operations guide](docs/operations.md); they do not establish Steam download success, systemd startup or public connectivity.

Markdown in `docs/` is the manual source. The server-management manual is derived from the full manual's hosting chapters to keep shared guidance consistent. Regenerate in-panel HTML and PDFs with:

```bash
python3 scripts/build-manuals.py
```

The documentation builder needs Pandoc, ReportLab and DejaVu fonts in the development environment. Commit the generated HTML/PDF files. Deployed panels do not require those build tools; the installer copies the manuals and includes them in recovery snapshots.

## License and attribution

FIELDHQ is distributed under the [MIT License](LICENSE). Upstream authorship and contribution history are retained; rebranding does not remove them. See [ATTRIBUTION.md](ATTRIBUTION.md) for upstream and bundled-asset credits.
