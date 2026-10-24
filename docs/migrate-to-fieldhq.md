# Switch an existing production panel to FIELDHQ

This switches the **repository used for future panel updates**. Keep the existing
checkout, service user, installation directories, configuration and server instances.
Use the update mode; do not run a fresh installation.

## Before starting

The new `https://github.com/aumik116/fieldhq` repository must exist and contain the
preserved project history on `main`. Creating an empty repository alone is not enough.

Take a VM snapshot or your usual database/configuration/save backup first. Wait for
server provisioning, Master update and other software jobs to finish. The installer
will restart the panel service; it does not deliberately restart the game servers.

## 1. Inspect your existing checkout

Run these commands from the same checkout where you normally pull panel updates:

```bash
pwd
git status --short --branch
git remote -v
```

If Git reports modified or untracked files, stop and review them before pulling.
Do not use a hard reset or delete local configuration to get past an update error.

## 2. Point the checkout at FIELDHQ

Once the new repository is published:

```bash
git remote set-url origin https://github.com/aumik116/fieldhq.git
git fetch origin
git switch main
git branch --set-upstream-to=origin/main main
git pull --ff-only
```

The checkout folder can keep its old name. The new repository preserves ancestry,
so an unchanged checkout should fast-forward. If fetching or fast-forwarding fails,
stop before running the installer and inspect the message. Do not force-pull or
replace the working tree to resolve it.

## 3. Update the installed panel

```bash
sudo bash install.sh --update
```

The installer copies FIELDHQ's panel files and manuals, keeps the existing settings
and database, and restarts the panel service. Existing users, units, roster records,
server registrations and save directories stay in place. Installer recovery snapshots
remain under `/var/backups/arma-panel/`; they do not replace your full VM/save backup.

## 4. Confirm the panel is available

```bash
sudo systemctl status arma-panel.service
sudo journalctl -u arma-panel.service -n 50 --no-pager
```

Then open your usual panel address and check:

- You can sign in and see your expected servers and units.
- Existing game servers have the expected running/stopped state.
- Rosters and event records are present.
- Help opens the three manuals and PDF downloads.

The panel URL, reverse-proxy rules, service names, game ports and server paths do
not need changing just because the repository changed.

## If the new remote is unavailable

Restore the old repository address for Git operations:

```bash
git remote set-url origin https://github.com/aumik116/arma-reforger-panel-aumik-edition.git
```

Changing a remote URL does not roll back installed code or rewind the database.
For an installation failure, follow the existing [backup and recovery guide](operations.md#backup-and-recovery)
and preserve the installer's reported snapshot path.
