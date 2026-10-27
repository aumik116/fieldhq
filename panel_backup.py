"""Owner-only, consistent panel-data downloads; game installations stay separate."""

from contextlib import closing
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from flask import abort, g, jsonify, send_file

RECOVERY_GUIDE = """FIELDHQ PANEL-DATA BACKUP

Contains account password hashes, private unit records/documents, panel settings,
the session signing key and available server configuration files. KEEP PRIVATE.

Game installations, Workshop files, profiles/world saves, logs, host services and
proxy configuration are excluded. Back up those separately.

The database is a consistent SQLite snapshot, including committed WAL data.
Configuration files are copied individually afterward, not as a host snapshot.
Check manifest.json for missing files, database_path and server_config_paths.

RECOVERY
1. Keep a backup of the current installation. On a new host, install a matching
   FIELDHQ release and initialize its empty database before stopping the panel.
2. Stop arma-panel. Extract this ZIP into a private temporary directory.
   Do not extract over the running installation.
3. Review config.env, database_path and server_config_paths for the target host.
   Preserve or adjust the registered instance paths before starting servers.
4. Run with appropriate host administration permissions:
   python3 PANEL_DIRECTORY/update_recovery.py restore-database EXTRACTED_DIRECTORY ACTUAL_DATABASE_PATH
   This restores into an existing database and retains the replaced database.
5. Restore config.env and .panel-secret to the panel directory, and available
   server-configs JSON files to their reviewed server_config_paths destinations.
   Preserve service-user ownership and private permissions. Restore game/profile
   backups separately, including the registered instance folders.
6. Start arma-panel, then run:
   python3 PANEL_DIRECTORY/update_recovery.py ready PANEL_DIRECTORY
   Check unit access, server configuration and game readiness before use.

Restoring the signing key may reinstate unexpired sessions from the snapshot.
Rotate it if recovery should sign everyone out. This archive is not a VM image.
"""


def install(api, owner_id, database):
    api.PANEL_WIDE_ENDPOINTS.add("panel_backup_download")

    @api.app.get("/api/panel/backup")
    def panel_backup_download():
        if g.user["id"] != owner_id:
            abort(
                403,
                description="Only the panel owner can download a complete panel backup",
            )
        output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        try:
            with tempfile.TemporaryDirectory(prefix="fieldhq-backup-") as directory:
                snapshot = Path(directory) / "panel-data.sqlite3"
                with closing(
                    sqlite3.connect(
                        Path(database).resolve().as_uri() + "?mode=ro", uri=True
                    )
                ) as live, closing(sqlite3.connect(snapshot)) as saved:
                    live.backup(saved)
                    if saved.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                        raise ValueError(
                            "Database integrity check failed; backup was not created"
                        )
                    registrations = saved.execute(
                        "SELECT id FROM server_instances ORDER BY id"
                    ).fetchall()
                manifest = dict(
                    format="FIELDHQ panel-data backup",
                    version=1,
                    created_utc=datetime.now(timezone.utc).isoformat(),
                    database_path=str(Path(database).resolve()),
                    files=["panel-data.sqlite3"],
                    missing=[],
                    server_config_paths={},
                    excluded=[
                        "Game installations",
                        "Workshop downloads",
                        "Profiles and world saves",
                        "Log files",
                        "External secrets and integrations",
                        "Host services and operating-system files",
                    ],
                )
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(snapshot, "panel-data.sqlite3")

                    def include(path, name):
                        path = Path(path)
                        if path.is_symlink():
                            raise ValueError(
                                "A configured backup file is a symbolic link; arrange a host backup for that file"
                            )
                        if not path.is_file():
                            manifest["missing"].append(name)
                            return
                        archive.write(path, name)
                        manifest["files"].append(name)

                    for name in ("config.env", ".panel-secret"):
                        include(Path(api._BASE_DIR) / name, name)
                    for (server_id,) in registrations:
                        # Registry IDs are validated; directory roots stay on this installation.
                        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", server_id):
                            raise ValueError("Invalid saved server identity")
                        configuration = (
                            api.server_registry.root / server_id / "config.json"
                        )
                        if not configuration.resolve().is_relative_to(
                            api.server_registry.root
                        ):
                            raise ValueError(
                                "Server configuration points outside its managed root"
                            )
                        name = f"server-configs/{server_id}.json"
                        manifest["server_config_paths"][name] = str(configuration)
                        include(configuration, name)
                    if not api.manager_mode:
                        manifest["server_config_paths"][
                            "server-configs/existing-server.json"
                        ] = str(api.SERVER_CONFIG)
                        include(
                            api.SERVER_CONFIG, "server-configs/existing-server.json"
                        )
                    archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                    archive.writestr(
                        "README.txt",
                        RECOVERY_GUIDE,
                    )
            api.audit_event(
                g.user["username"],
                "panel_backup_download",
                "success",
                {"files": len(manifest["files"])},
            )
            output.seek(0)
            response = send_file(
                output,
                mimetype="application/zip",
                as_attachment=True,
                download_name="fieldhq-panel-backup-"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                + ".zip",
            )
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        except (OSError, sqlite3.Error, ValueError):
            output.close()
            api.app.logger.exception("Panel backup failed")
            return (
                jsonify(
                    ok=False,
                    error="Panel backup could not be prepared. Check the panel log; no live data was changed.",
                ),
                500,
            )
