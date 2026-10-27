"""Unit-scoped staff permissions and rosters; server controls remain explicit grants."""

from contextlib import contextmanager
import csv
import hashlib
import hmac
from datetime import date, timedelta
import io
import json
import sqlite3
import time

from flask import abort, g, jsonify, redirect, request, send_file, send_from_directory

from unit_common import (
    CAPABILITIES,
    STAFF_CAPABILITIES as STAFF_CAPABILITIES,
    UUID as UUID,
    actor,
    effective_certificates,
    roster_status,
    text,
    unit_role_capabilities,
)

FIELDS = (
    "game_name",
    "discord",
    "identity",
    "status",
    "rank",
    "section",
    "position",
    "joined_on",
    "loa_until",
    "loa_from",
    "callsign",
    "notes",
    "last_promo",
    "certificates",
    "rank_track",
)


def rank_structures_catalog(catalog):
    """Preserve existing rank rules when upgrading the former shared-paygrade catalog."""
    if "rank_structures" in catalog:
        return catalog
    result = dict(catalog)
    old_grades = result.pop("paygrades", [])
    old_ranks = result.pop("ranks", [])
    if (
        not isinstance(old_grades, list)
        or not isinstance(old_ranks, list)
        or len(old_grades) > 50
        or len(old_ranks) > 100
    ):
        raise ValueError("Choose valid existing ranks and paygrades")
    grades = {}
    for grade in old_grades:
        if (
            not isinstance(grade, dict)
            or type(grade.get("days")) is not int
            or not 0 <= grade["days"] <= 36500
        ):
            raise ValueError("Choose valid existing paygrade requirements")
        name = text(grade.get("name"), "Paygrade", 40, True)
        requirements = grade.get("certificates", [])
        if not isinstance(requirements, list) or any(
            not isinstance(c, str) for c in requirements
        ):
            raise ValueError("Choose valid existing qualification requirements")
        grades[name] = grade
    ranks = []
    for rank in old_ranks:
        if not isinstance(rank, dict):
            raise ValueError("Choose valid existing ranks")
        name = text(rank.get("name"), "Rank", 80, True)
        grade_name = text(rank.get("paygrade", ""), "Paygrade", 40)
        if grade_name not in grades:
            raise ValueError("Existing ranks must reference defined paygrades")
        grade = grades[grade_name]
        requirements = rank.get("certificates", [])
        if not isinstance(requirements, list) or any(
            not isinstance(c, str) for c in requirements
        ):
            raise ValueError("Choose valid existing qualification requirements")
        ranks.append(
            dict(
                name=name,
                paygrade=grade_name,
                days=grade["days"],
                next_rank=rank.get("next_rank", ""),
                certificates=sorted(
                    set(grade.get("certificates", [])) | set(requirements)
                ),
            )
        )
    result["rank_structures"] = (
        [dict(name="Existing ranks", ranks=ranks)] if ranks else []
    )
    return result


def install(api):
    database = api.server_registry.database

    @contextmanager
    def db():
        conn = sqlite3.connect(database, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                tag TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS unit_branding (
                unit_id INTEGER PRIMARY KEY, description TEXT NOT NULL DEFAULT '',
                icon BLOB, icon_type TEXT, banner BLOB, banner_type TEXT);
            CREATE TABLE IF NOT EXISTS unit_servers (
                unit_id INTEGER NOT NULL, server_id TEXT NOT NULL,
                PRIMARY KEY(unit_id,server_id));
            CREATE TABLE IF NOT EXISTS unit_staff (
                unit_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('member','staff','admin')),
                capabilities TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(unit_id,user_id));
            CREATE TABLE IF NOT EXISTS unit_roster (
                id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL,
                game_name TEXT NOT NULL, discord TEXT NOT NULL DEFAULT '', identity TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active', rank TEXT NOT NULL DEFAULT '',
                section TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '',
                joined_on TEXT NOT NULL DEFAULT '', loa_until TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS unit_roster_identity ON unit_roster(unit_id,identity) WHERE identity!='';
            CREATE INDEX IF NOT EXISTS unit_roster_unit ON unit_roster(unit_id,archived);
            CREATE TABLE IF NOT EXISTS unit_structure (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                parent_id INTEGER, kind TEXT NOT NULL CHECK(kind IN ('group','section','billet')),
                name TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS unit_structure_parent ON unit_structure(unit_id,parent_id,sort_order);
            CREATE TABLE IF NOT EXISTS unit_member_placements (
                unit_id INTEGER NOT NULL, member_id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_member_placements_parent ON unit_member_placements(unit_id,parent_id);
            CREATE TABLE IF NOT EXISTS unit_primary_slots (
                unit_id INTEGER NOT NULL, member_id INTEGER PRIMARY KEY,
                billet_id INTEGER NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS unit_account_suspensions (unit_id INTEGER NOT NULL,user_id INTEGER NOT NULL,PRIMARY KEY(unit_id,user_id));
            CREATE TABLE IF NOT EXISTS unit_roster_deleted_ids (id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS unit_member_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL, author_id INTEGER NOT NULL,
                author_name TEXT NOT NULL, created_at REAL NOT NULL, note TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_member_notes_member ON unit_member_notes(unit_id,member_id,id);

        """)
        note_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(unit_member_notes)")
        }
        for name, declaration in [
            ("edited_at", "REAL"),
            ("edited_by", "TEXT NOT NULL DEFAULT ''"),
            ("version", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            if name not in note_columns:
                conn.execute(
                    f"ALTER TABLE unit_member_notes ADD COLUMN {name} {declaration}"
                )
        if (
            "'member'"
            not in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='unit_staff'"
            ).fetchone()[0]
        ):
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE unit_staff_member_upgrade (unit_id INTEGER NOT NULL,user_id INTEGER NOT NULL,role TEXT NOT NULL CHECK(role IN ('member','staff','admin')),capabilities TEXT NOT NULL DEFAULT '[]',PRIMARY KEY(unit_id,user_id))"
            )
            conn.execute(
                "INSERT INTO unit_staff_member_upgrade SELECT * FROM unit_staff"
            )
            conn.execute("DROP TABLE unit_staff")
            conn.execute("ALTER TABLE unit_staff_member_upgrade RENAME TO unit_staff")
        for table, column, definition in [
            ("units", "catalog", "TEXT NOT NULL DEFAULT '{}'"),
            ("unit_roster", "last_promo", "TEXT NOT NULL DEFAULT ''"),
            ("unit_roster", "certificates", "TEXT NOT NULL DEFAULT ''"),
            ("unit_roster", "panel_user_id", "INTEGER"),
            ("unit_roster", "rank_track", "TEXT NOT NULL DEFAULT ''"),
            ("unit_roster", "loa_from", "TEXT NOT NULL DEFAULT ''"),
            ("unit_roster", "callsign", "TEXT NOT NULL DEFAULT ''"),
        ]:
            if column not in {
                r["name"] for r in conn.execute(f"PRAGMA table_info({table})")
            }:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        for unit in conn.execute("SELECT id,catalog FROM units").fetchall():
            old = json.loads(unit["catalog"])
            if "rank_structures" not in old:
                catalog = rank_structures_catalog(old)
                conn.execute(
                    "UPDATE units SET catalog=?,revision=revision+1 WHERE id=?",
                    (json.dumps(catalog), unit["id"]),
                )
                if catalog["rank_structures"]:
                    conn.execute(
                        "UPDATE unit_roster SET rank_track='Existing ranks' WHERE unit_id=? AND rank!='' AND rank_track=''",
                        (unit["id"],),
                    )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS unit_roster_panel_user ON unit_roster(unit_id,panel_user_id) WHERE panel_user_id IS NOT NULL"
        )
        # Normalize legacy checkbox grants; role is now the sole authority.
        for role in ("staff", "admin"):
            normalized = json.dumps(unit_role_capabilities(role))
            changed = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT unit_id FROM unit_staff WHERE role=? AND capabilities!=?",
                    (role, normalized),
                )
            ]
            conn.execute(
                "UPDATE unit_staff SET capabilities=? WHERE role=? AND capabilities!=?",
                (normalized, role, normalized),
            )
            for unit_id in changed:
                conn.execute(
                    "UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,)
                )
        owner_id = conn.execute(
            "SELECT user_id FROM panel_owner WHERE singleton=1"
        ).fetchone()[0]

    def panel_admin():
        return g.user["id"] == owner_id or bool(g.user["panel_admin"])

    def hosting_access(conn):
        return (
            panel_admin()
            or bool(g.user["access_all"])
            or bool(
                conn.execute(
                    "SELECT 1 FROM user_server_roles WHERE user_id=? LIMIT 1",
                    (g.user["id"],),
                ).fetchone()
            )
        )

    def unit_only_user():
        with db() as conn:
            return not hosting_access(conn) and bool(
                conn.execute(
                    "SELECT 1 FROM unit_staff WHERE user_id=? LIMIT 1", (g.user["id"],)
                ).fetchone()
            )

    api.unit_only_user = unit_only_user

    def access(conn, unit_id, capability=None):
        unit = conn.execute("SELECT * FROM units WHERE id=?", (unit_id,)).fetchone()
        if not unit:
            abort(404, description="Unit not found")
        if panel_admin():
            return unit
        membership = conn.execute(
            "SELECT * FROM unit_staff WHERE unit_id=? AND user_id=?",
            (unit_id, g.user["id"]),
        ).fetchone()
        if (
            not membership
            or conn.execute(
                "SELECT 1 FROM unit_account_suspensions WHERE unit_id=? AND user_id=?",
                (unit_id, g.user["id"]),
            ).fetchone()
        ):
            abort(404, description="Unit not found")
        if membership["role"] == "member" and request.endpoint not in {
            "unit_detail",
            "unit_collab_state",
            "unit_branding_image",
            "unit_library",
            "unit_reference",
            "unit_reference_file",
            "unit_member_home",
            "unit_self_profile",
            "unit_reading_acknowledge",
            "unit_rsvp_save",
        }:
            abort(
                403,
                description="This page is for unit staff. Use My unit, My profile or published resources.",
            )
        if capability and capability not in unit_role_capabilities(membership["role"]):
            abort(403, description="Your unit role does not allow this change")
        return unit

    def revision(conn, unit_id, data):
        if type(data.get("revision")) is not int:
            raise ValueError("Reload the unit before saving")
        if not conn.execute(
            "UPDATE units SET revision=revision+1 WHERE id=? AND revision=?",
            (unit_id, data["revision"]),
        ).rowcount:
            abort(
                409,
                description="This unit changed. Reload it before saving your changes.",
            )

    def validate_staff(role):
        if role not in ("member", "staff", "admin"):
            raise ValueError("Choose Member, Staff or Unit administrator")

    def protect_admin(conn, unit_id, user_id, new_role):
        previous = conn.execute(
            "SELECT role FROM unit_staff WHERE unit_id=? AND user_id=?",
            (unit_id, user_id),
        ).fetchone()
        if user_id == owner_id and g.user["id"] != owner_id:
            abort(403, description="Only the Owner can change their unit membership")
        if previous and previous["role"] == "admin" and new_role != "admin":
            remaining = conn.execute(
                "SELECT count(*) FROM unit_staff s JOIN users u ON u.id=s.user_id WHERE s.unit_id=? AND s.role='admin' AND u.enabled=1 AND s.user_id!=?",
                (unit_id, user_id),
            ).fetchone()[0]
            if not remaining:
                raise ValueError("Keep at least one enabled unit administrator")

    def save_user_units(conn, user_id, assignments, revisions=None):
        """Called inside the existing account-save transaction, before commit."""
        if not isinstance(assignments, list) or len(assignments) > 100:
            raise ValueError("Choose valid unit memberships")
        desired = {}
        for item in assignments:
            if not isinstance(item, dict) or type(item.get("unit_id")) is not int:
                raise ValueError("Choose valid unit memberships")
            unit_id = item["unit_id"]
            if unit_id in desired:
                raise ValueError("A unit can only be assigned once")
            access(conn, unit_id, "staff")
            validate_staff(item.get("role"))
            desired[unit_id] = item
        existing = {
            r["unit_id"]
            for r in conn.execute(
                "SELECT unit_id FROM unit_staff WHERE user_id=?", (user_id,)
            )
        }
        for unit_id in existing | desired.keys():
            if revisions is not None:
                current = conn.execute(
                    "SELECT revision FROM units WHERE id=?", (unit_id,)
                ).fetchone()
                if (
                    not isinstance(revisions, dict)
                    or not current
                    or revisions.get(str(unit_id)) != current["revision"]
                ):
                    abort(
                        409,
                        description="Unit membership changed. Reopen the account editor.",
                    )
            item = desired.get(unit_id)
            protect_admin(conn, unit_id, user_id, item["role"] if item else None)
            conn.execute(
                "DELETE FROM unit_staff WHERE unit_id=? AND user_id=?",
                (unit_id, user_id),
            )
            if item:
                conn.execute(
                    "INSERT INTO unit_staff VALUES(?,?,?,?)",
                    (
                        unit_id,
                        user_id,
                        item["role"],
                        json.dumps(unit_role_capabilities(item["role"])),
                    ),
                )
            conn.execute("UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,))

    def protect_account(conn, user_id):
        if conn.execute("SELECT enabled FROM users WHERE id=?", (user_id,)).fetchone()[
            "enabled"
        ]:
            return
        for row in conn.execute(
            "SELECT unit_id FROM unit_staff WHERE user_id=? AND role='admin'",
            (user_id,),
        ):
            protect_admin(conn, row["unit_id"], user_id, None)

    api.save_user_units = save_user_units
    api.protect_unit_account = protect_account

    endpoints = {
        "units_list",
        "units_save",
        "unit_detail",
        "unit_roster_save",
        "unit_staff_save",
        "unit_identities",
        "unit_roster_export",
        "unit_health",
        "units_page",
        "panel_users_page",
        "unit_catalog_save",
        "unit_catalog_preview",
        "unit_position_rename",
        "unit_member_record",
        "unit_member_note_save",
        "unit_member_note_delete",
        "unit_member_note_edit",
        "unit_member_login_create",
        "unit_roster_delete",
        "unit_structure_save",
        "unit_structure_delete",
        "unit_structure_order",
        "unit_primary_assign",
        "unit_placement_save",
        "unit_branding_save",
        "unit_branding_image",
    }
    api.PANEL_WIDE_ENDPOINTS.update(endpoints)
    from panel_features import MUTATIONS

    MUTATIONS["unit_member_note_edit"] = "view"
    MUTATIONS["unit_member_note_delete"] = "view"
    MUTATIONS["unit_staff_save"] = "view"
    MUTATIONS["unit_member_login_create"] = "view"
    MUTATIONS["unit_placement_save"] = "view"
    MUTATIONS["unit_primary_assign"] = "view"
    MUTATIONS["unit_branding_save"] = "view"

    @api.app.errorhandler(400)
    @api.app.errorhandler(403)
    @api.app.errorhandler(404)
    @api.app.errorhandler(409)
    @api.app.errorhandler(413)
    def unit_error(error):
        if request.endpoint in endpoints or request.endpoint == "users_save":
            return jsonify(ok=False, error=error.description), error.code
        return error

    @api.app.get("/units")
    def units_page():
        if request.args.get("admin") == "users" or "users" in request.args:
            return redirect("/admin/users")
        return send_from_directory(api._BASE_DIR, "units.html")

    @api.app.get("/admin/users")
    def panel_users_page():
        if not panel_admin():
            abort(
                403, description="Only panel administrators can manage panel accounts"
            )
        return send_from_directory(api._BASE_DIR, "users.html")

    @api.app.get("/api/units")
    def units_list():
        with db() as conn:
            rows = (
                conn.execute("SELECT * FROM units ORDER BY name").fetchall()
                if panel_admin()
                else conn.execute(
                    "SELECT u.* FROM units u JOIN unit_staff s ON s.unit_id=u.id WHERE s.user_id=? AND NOT EXISTS (SELECT 1 FROM unit_account_suspensions x WHERE x.unit_id=s.unit_id AND x.user_id=s.user_id) ORDER BY u.name",
                    (g.user["id"],),
                ).fetchall()
            )
            result = []
            for row in rows:
                member = conn.execute(
                    "SELECT role,capabilities FROM unit_staff WHERE unit_id=? AND user_id=?",
                    (row["id"], g.user["id"]),
                ).fetchone()
                visible_row = dict(row)
                if not panel_admin() and member["role"] == "member":
                    visible_row = {key: row[key] for key in ("id", "name", "revision")}
                result.append(
                    dict(
                        visible_row,
                        role="admin" if panel_admin() else member["role"],
                        capabilities=(
                            list(CAPABILITIES)
                            if panel_admin() or member["role"] == "admin"
                            else list(unit_role_capabilities(member["role"]))
                        ),
                        servers=(
                            []
                            if not panel_admin() and member["role"] == "member"
                            else [
                                r["server_id"]
                                for r in conn.execute(
                                    "SELECT server_id FROM unit_servers WHERE unit_id=?",
                                    (row["id"],),
                                )
                            ]
                        ),
                    )
                )
            # Only disclose server names linked to visible units, plus explicit server grants.
            visible = {s for row in result for s in row["servers"]}
            servers = [
                dict(id=s.id, name=s.name)
                for s in api.server_registry.list()
                if panel_admin()
                or s.id in visible
                or api.server_permissions(g.user, s.id)
            ]
            if not api.manager_mode and (
                panel_admin() or "" in visible or api.server_permissions(g.user, "")
            ):
                servers.insert(0, dict(id="", name="Existing server"))
            has_hosting_access = hosting_access(conn)
        return jsonify(
            units=result,
            servers=servers,
            panel_admin=panel_admin(),
            hosting_access=has_hosting_access,
            user_id=g.user["id"],
        )

    @api.app.post("/api/units")
    def units_save():
        if not panel_admin():
            abort(
                403,
                description="Only panel administrators can create or edit units and server links",
            )
        data = request.get_json()
        try:
            name = text(data.get("name"), "Unit name", 80, True)
            tag = text(data.get("tag", ""), "Unit tag", 16)
            links = data.get("servers", [])
            known = {s.id for s in api.server_registry.list()} | (
                set() if api.manager_mode else {""}
            )
            if not isinstance(links, list) or any(
                not isinstance(s, str) or s not in known for s in links
            ):
                raise ValueError("Choose existing servers")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                unit_id = data.get("id")
                if unit_id is None:
                    unit_id = conn.execute(
                        "INSERT INTO units(name,tag) VALUES(?,?)", (name, tag)
                    ).lastrowid
                    conn.execute(
                        "INSERT INTO unit_staff(unit_id,user_id,role) VALUES(?,?,'admin')",
                        (unit_id, g.user["id"]),
                    )
                    record_strength(conn, unit_id, baseline=True)
                else:
                    if type(unit_id) is not int:
                        raise ValueError("Choose a valid unit")
                    access(conn, unit_id)
                    revision(conn, unit_id, data)
                    conn.execute(
                        "UPDATE units SET name=?,tag=? WHERE id=?", (name, tag, unit_id)
                    )
                for event in conn.execute(
                    "SELECT server_id FROM unit_events WHERE unit_id=? AND ends>? AND state='scheduled'",
                    (unit_id, time.time()),
                ):
                    if event["server_id"] not in links:
                        raise ValueError(
                            "Move or cancel upcoming/active events before unlinking their server"
                        )
                conn.execute("DELETE FROM unit_servers WHERE unit_id=?", (unit_id,))
                conn.executemany(
                    "INSERT INTO unit_servers VALUES(?,?)",
                    [(unit_id, s) for s in set(links)],
                )
            g.audit_details = dict(unit_id=unit_id, name=name, servers=links)
            return jsonify(ok=True, id=unit_id)
        except (ValueError, sqlite3.IntegrityError) as exc:
            return (
                jsonify(
                    ok=False,
                    error=(
                        "Unit name is already in use"
                        if isinstance(exc, sqlite3.IntegrityError)
                        else str(exc)
                    ),
                ),
                400,
            )

    def catalog_values(raw):
        if not isinstance(raw, dict):
            raise ValueError("Choose valid rank and qualification settings")
        certificates = raw.get("certificates", [])
        if not isinstance(certificates, list) or len(certificates) > 100:
            raise ValueError("Keep at most 100 qualifications")
        certificates = [text(c, "Qualification", 80, True) for c in certificates]
        if len(set(c.casefold() for c in certificates)) != len(certificates) or any(
            ";" in c for c in certificates
        ):
            raise ValueError("Use unique qualification names without semicolons")
        details = raw.get("qualification_details", [])
        if not isinstance(details, list) or len(details) > 100:
            raise ValueError("Keep at most 100 qualification descriptions")
        detail_by_name = {}
        for entry in details:
            if not isinstance(entry, dict):
                raise ValueError("Choose valid qualification details")
            name = text(entry.get("name"), "Qualification", 80, True)
            if name not in certificates or name in detail_by_name:
                raise ValueError(
                    "Qualification details must match unique catalog names"
                )
            if type(entry.get("archived", False)) is not bool:
                raise ValueError("Archived must be true or false")
            if type(entry.get("renewal_required", False)) is not bool:
                raise ValueError("Choose whether renewal is required")
            detail_by_name[name] = dict(
                name=name,
                abbreviation=text(entry.get("abbreviation", ""), "Abbreviation", 20),
                description=text(entry.get("description", ""), "Description", 1000),
                archived=entry.get("archived", False),
                renewal_required=entry.get("renewal_required", False),
            )
        qualification_details = [
            detail_by_name.get(
                name,
                dict(
                    name=name,
                    abbreviation="",
                    description="",
                    archived=False,
                    renewal_required=False,
                ),
            )
            for name in certificates
        ]
        positions = raw.get("positions", [])
        if not isinstance(positions, list) or len(positions) > 100:
            raise ValueError("Keep at most 100 positions")
        positions = [text(p, "Position", 80, True) for p in positions]
        if len(set(p.casefold() for p in positions)) != len(positions) or any(
            ";" in p for p in positions
        ):
            raise ValueError("Use unique position names without semicolons")

        def requirements(values):
            if not isinstance(values, list) or any(
                c not in certificates for c in values
            ):
                raise ValueError("Select qualifications from this unit’s catalog")
            return sorted(set(values))

        raw = rank_structures_catalog(raw)
        structures = raw.get("rank_structures", [])
        if not isinstance(structures, list) or len(structures) > 20:
            raise ValueError("Keep at most 20 rank structures per unit")
        result = []
        total = 0
        for structure in structures:
            if not isinstance(structure, dict):
                raise ValueError("Choose valid rank structures")
            structure_name = text(
                structure.get("name"), "Rank structure name", 80, True
            )
            entries = structure.get("ranks", [])
            if not isinstance(entries, list):
                raise ValueError("Choose valid ranks for each structure")
            total += len(entries)
            if total > 200:
                raise ValueError("Keep at most 200 ranks across the unit’s structures")
            ranks = []
            for item in entries:
                if (
                    not isinstance(item, dict)
                    or type(item.get("days", 0)) is not int
                    or not 0 <= item.get("days", 0) <= 36500
                ):
                    raise ValueError("Advancement time must be 0–36500 whole days")
                ranks.append(
                    dict(
                        name=text(item.get("name"), "Rank", 80, True),
                        abbreviation=text(
                            item.get("abbreviation", ""), "Rank abbreviation", 20
                        ),
                        paygrade=text(item.get("paygrade", ""), "Paygrade label", 40),
                        days=item.get("days", 0),
                        next_rank=text(item.get("next_rank", ""), "Next rank", 80),
                        certificates=requirements(item.get("certificates", [])),
                    )
                )
            by_name = {rank["name"]: rank for rank in ranks}
            if len({rank["name"].casefold() for rank in ranks}) != len(ranks):
                raise ValueError("Rank names must be unique within their structure")
            for rank in ranks:
                seen = {rank["name"]}
                target = rank["next_rank"]
                while target:
                    if target not in by_name or target in seen:
                        raise ValueError(
                            "Next ranks must exist in the same structure and cannot form a cycle"
                        )
                    seen.add(target)
                    target = by_name[target]["next_rank"]
            result.append(dict(name=structure_name, ranks=ranks))
        if len({s["name"].casefold() for s in result}) != len(result):
            raise ValueError("Rank structure names must be unique")
        return dict(
            certificates=certificates,
            positions=positions,
            rank_structures=result,
            qualification_details=qualification_details,
        )

    @api.app.post("/api/units/<int:unit_id>/catalog")
    def unit_catalog_save(unit_id):
        data = request.get_json()
        try:
            catalog = catalog_values(data.get("catalog"))
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                if "catalog_base" in data:
                    base = catalog_values(data["catalog_base"])
                    current = catalog_values(
                        json.loads(
                            conn.execute(
                                "SELECT catalog FROM units WHERE id=?", (unit_id,)
                            ).fetchone()[0]
                        )
                    )
                    merged = {}
                    for field in current:
                        key = lambda item: (
                            item["name"] if isinstance(item, dict) else item
                        )
                        old = {key(item): item for item in base[field]}
                        proposed = {key(item): item for item in catalog[field]}
                        live = {key(item): item for item in current[field]}
                        for name in dict.fromkeys([*old, *proposed]):
                            if old.get(name) == proposed.get(name):
                                continue
                            if live.get(name) != old.get(name) and live.get(
                                name
                            ) != proposed.get(name):
                                abort(
                                    409,
                                    description=f"{name} was changed by another editor. Your draft is preserved. Copy your draft before reopening this item.",
                                )
                            if name in proposed:
                                live[name] = proposed[name]
                            else:
                                live.pop(name, None)
                        merged[field] = list(live.values())
                    catalog = catalog_values(merged)
                    conn.execute(
                        "UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,)
                    )
                else:
                    revision(conn, unit_id, data)
                if "qualification_details" not in data.get("catalog", {}):
                    previous = json.loads(
                        conn.execute(
                            "SELECT catalog FROM units WHERE id=?", (unit_id,)
                        ).fetchone()[0]
                    )
                    old_details = {
                        entry["name"]: entry
                        for entry in previous.get("qualification_details", [])
                    }
                    catalog["qualification_details"] = [
                        old_details.get(entry["name"], entry)
                        for entry in catalog["qualification_details"]
                    ]
                previous_ranks = {
                    (track["name"], rank["name"]): rank
                    for track in json.loads(
                        conn.execute(
                            "SELECT catalog FROM units WHERE id=?", (unit_id,)
                        ).fetchone()[0]
                    ).get("rank_structures", [])
                    for rank in track["ranks"]
                }
                raw_ranks = {
                    (track.get("name"), rank.get("name")): rank
                    for track in data["catalog"].get("rank_structures", [])
                    for rank in track.get("ranks", [])
                }
                for track in catalog["rank_structures"]:
                    for rank in track["ranks"]:
                        key = (track["name"], rank["name"])
                        if (
                            key in previous_ranks
                            and "abbreviation" not in raw_ranks.get(key, {})
                        ):
                            rank["abbreviation"] = previous_ranks[key].get(
                                "abbreviation", ""
                            )
                used = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT rank,rank_track,certificates,position FROM unit_roster WHERE unit_id=?",
                        (unit_id,),
                    )
                ]
                names = {
                    (structure["name"], rank["name"])
                    for structure in catalog["rank_structures"]
                    for rank in structure["ranks"]
                }
                tracks = {structure["name"] for structure in catalog["rank_structures"]}
                for row in used:
                    if (
                        row["rank_track"]
                        and row["rank_track"] not in tracks
                        or row["rank"]
                        and (row["rank_track"], row["rank"]) not in names
                        or any(
                            c not in catalog["certificates"]
                            for c in row["certificates"].split(";")
                            if c
                        )
                    ):
                        raise ValueError(
                            "A rank structure, rank or qualification is used by a roster record. Update those records before removing or renaming it."
                        )
                conn.execute(
                    "UPDATE units SET catalog=? WHERE id=?",
                    (json.dumps(catalog), unit_id),
                )
            g.audit_details = dict(
                unit_id=unit_id, change="rank and qualification catalog"
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/catalog/preview")
    def unit_catalog_preview(unit_id):
        try:
            data = request.get_json()
            with db() as conn:
                access(conn, unit_id, "staff")
                catalog = catalog_values(data.get("catalog"))
                key = data.get("member_id")
                if type(key) is not int or not 1 <= key <= 9223372036854775807:
                    raise ValueError("Choose a roster member")
                member = dict(find_member(conn, unit_id, key))
                member["rank_track"] = text(
                    data.get("rank_track", member["rank_track"]), "Rank structure", 80
                )
                member["rank"] = text(
                    data.get("rank", member["rank"]), "Current rank", 80
                )
                member["last_promo"] = text(
                    data.get("last_promo", member["last_promo"]),
                    "Last promotion date",
                    10,
                )
                if member["last_promo"]:
                    member["last_promo"] = date.fromisoformat(
                        member["last_promo"]
                    ).isoformat()
                    if member["last_promo"] > date.today().isoformat():
                        raise ValueError("Last promotion date cannot be in the future")
                structure = next(
                    (
                        item
                        for item in catalog["rank_structures"]
                        if item["name"] == member["rank_track"]
                    ),
                    None,
                )
                current = (
                    next(
                        (
                            rank
                            for rank in structure["ranks"]
                            if rank["name"] == member["rank"]
                        ),
                        None,
                    )
                    if structure
                    else None
                )
                if current is None:
                    raise ValueError("Choose a current rank in this structure")
                target = next(
                    (
                        rank
                        for rank in structure["ranks"]
                        if rank["name"] == current["next_rank"]
                    ),
                    None,
                )
                member["active_certificates"] = effective_certificates(
                    conn, unit_id, member
                )
                result = promotion(member, catalog)
            return jsonify(
                ok=True,
                member=dict(
                    game_name=member["game_name"], archived=bool(member["archived"])
                ),
                promotion=result,
                target=target,
                today=date.today().isoformat(),
                held=[value for value in member["certificates"].split(";") if value],
            )
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/positions/rename")
    def unit_position_rename(unit_id):
        data = request.get_json()
        try:
            old = text(data.get("old"), "Existing position", 80, True)
            new = text(data.get("name"), "Position name", 80, True)
            if ";" in new:
                raise ValueError("Position names cannot contain semicolons")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                unit = access(conn, unit_id, "staff")
                revision(conn, unit_id, data)
                catalog = json.loads(unit["catalog"])
                positions = catalog.get("positions", [])
                if old not in positions or any(
                    p.casefold() == new.casefold() for p in positions if p != old
                ):
                    raise ValueError(
                        "Choose an existing position and a unique new name"
                    )
                catalog["positions"] = [new if p == old else p for p in positions]
                conn.execute(
                    "UPDATE unit_structure SET name=? WHERE unit_id=? AND kind='billet' AND name=?",
                    (new, unit_id, old),
                )
                conn.execute(
                    "UPDATE units SET catalog=? WHERE id=?",
                    (json.dumps(catalog), unit_id),
                )
                for member in conn.execute(
                    "SELECT id,position FROM unit_roster WHERE unit_id=?", (unit_id,)
                ).fetchall():
                    assigned = member["position"].split(";")
                    if old in assigned:
                        conn.execute(
                            "UPDATE unit_roster SET position=?,updated_at=? WHERE id=?",
                            (
                                ";".join(new if p == old else p for p in assigned),
                                time.time(),
                                member["id"],
                            ),
                        )
            g.audit_details = dict(unit_id=unit_id, old_position=old, new_position=new)
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def promotion(member, catalog, on=None):
        member = dict(member)
        structure = next(
            (
                s
                for s in catalog.get("rank_structures", [])
                if s["name"] == member["rank_track"]
            ),
            {},
        )
        ranks = {r["name"]: r for r in structure.get("ranks", [])}
        current = ranks.get(member["rank"], {})
        target = ranks.get(current.get("next_rank"))
        if not target:
            return dict(next_rank="", next_date="", missing=[], eligible=False)
        held = set(member.get("active_certificates", member["certificates"].split(";")))
        missing = sorted(set(target["certificates"]) - held)
        due = (
            (
                date.fromisoformat(member["last_promo"])
                + timedelta(days=target["days"])
            ).isoformat()
            if member["last_promo"]
            else ""
        )
        return dict(
            next_rank=target["name"],
            next_date=due,
            missing=missing,
            eligible=bool(
                due
                and due <= (on or date.today().isoformat())
                and not missing
                and not member["archived"]
            ),
        )

    def structure_rows(conn, unit_id):
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM unit_structure WHERE unit_id=? ORDER BY sort_order,id",
                (unit_id,),
            )
        ]

    def structure_node(conn, unit_id, node_id, kind=None):
        if type(node_id) is not int or not 1 <= node_id <= 9223372036854775807:
            raise ValueError("Choose a valid structure item")
        node = conn.execute(
            "SELECT * FROM unit_structure WHERE unit_id=? AND id=?", (unit_id, node_id)
        ).fetchone()
        if not node or kind and node["kind"] != kind:
            abort(404, description="Structure item not found in this unit")
        return node

    def decorate_slots(conn, unit_id, members, structure=None):
        structure = (
            structure if structure is not None else structure_rows(conn, unit_id)
        )
        catalog = json.loads(
            conn.execute("SELECT catalog FROM units WHERE id=?", (unit_id,)).fetchone()[
                "catalog"
            ]
        )
        abbreviations = {
            (track["name"], rank["name"]): rank.get("abbreviation", "")
            for track in catalog.get("rank_structures", [])
            for rank in track["ranks"]
        }
        history = {
            row["member_id"]: row["version"]
            for row in conn.execute(
                "SELECT member_id,max(id) AS version FROM unit_roster_history WHERE unit_id=? GROUP BY member_id",
                (unit_id,),
            )
        }
        by_id = {row["id"]: row for row in structure}
        slots = {
            row["member_id"]: row["billet_id"]
            for row in conn.execute(
                "SELECT * FROM unit_primary_slots WHERE unit_id=?", (unit_id,)
            )
        }
        placements = {
            row["member_id"]: row["parent_id"]
            for row in conn.execute(
                "SELECT * FROM unit_member_placements WHERE unit_id=?", (unit_id,)
            )
        }

        def path(node):
            parts = []
            seen = set()
            while node and node["id"] not in seen:
                seen.add(node["id"])
                parts.insert(0, node["name"])
                node = by_id.get(node["parent_id"])
            return " / ".join(parts)

        expiries = {}
        for row in conn.execute(
            "SELECT member_id,certificate,expires_on FROM unit_qualification_awards WHERE unit_id=? AND expires_on!=''",
            (unit_id,),
        ):
            expiries.setdefault(row["member_id"], {})[row["certificate"]] = row[
                "expires_on"
            ]
        for member in members:
            member["qualification_expiries"] = expiries.get(member["id"], {})
            renewing = {
                entry["name"]
                for entry in catalog.get("qualification_details", [])
                if entry.get("renewal_required")
            }
            member["qualification_expiries"] = {
                name: value
                for name, value in member["qualification_expiries"].items()
                if name in renewing
            }
            member["expired_certificates"] = [
                name
                for name, expiry in member["qualification_expiries"].items()
                if expiry < date.today().isoformat()
            ]
            member["active_certificates"] = effective_certificates(
                conn, unit_id, member
            )
            payload = {field: member[field] for field in FIELDS}
            # Catalog selections are validated against current rules on save.
            # Editing rules must not invalidate an unchanged member record.
            payload.update(
                id=member["id"],
                unit_id=unit_id,
                archived=member["archived"],
                panel_user_id=member["panel_user_id"],
                updated_at=member["updated_at"],
                history=history.get(member["id"], 0),
                billet=slots.get(member["id"]),
                placement=placements.get(member["id"]),
            )
            member["edit_token"] = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest()
            member["rank_abbreviation"] = abbreviations.get(
                (member["rank_track"], member["rank"]), ""
            )
            member["rank_display"] = member["rank_abbreviation"] or member["rank"]
            member["scheduled_status"] = member["status"]
            member["status"] = roster_status(member)
            slot = by_id.get(slots.get(member["id"]))
            placement = by_id.get(placements.get(member["id"])) if not slot else None
            formation = by_id.get(slot["parent_id"]) if slot else placement
            member.update(
                billet_id=slot["id"] if slot else None,
                billet_name=slot["name"] if slot else "",
                billet_callsign=slot["callsign"] if slot else "",
                effective_callsign=member.get("callsign", "")
                or (slot["callsign"] if slot else ""),
                billet_path=path(slot),
                placement_id=placement["id"] if placement else None,
                placement_path=path(placement),
                assignment_path=path(slot or placement),
                formation_id=formation["id"] if formation else None,
                formation_path=path(formation),
            )

    def member_revision(conn, unit_id, data, member_id):
        expected = data.get("member_token")
        if expected is None:
            revision(conn, unit_id, data)
            return
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError("Reopen the member record before saving")
        member = dict(find_member(conn, unit_id, member_id))
        decorate_slots(conn, unit_id, [member])
        if not hmac.compare_digest(expected, member["edit_token"]):
            abort(
                409,
                description="This member changed while you were editing. Your changes were not saved. Reopen the record and review the latest version.",
            )
        conn.execute("UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,))

    def assign_slot(conn, unit_id, member_id, billet_id):
        member = find_member(conn, unit_id, member_id)
        if billet_id is not None:
            structure_node(conn, unit_id, billet_id, "billet")
            if member["archived"]:
                raise ValueError(
                    "Restore this member before assigning a primary billet"
                )
            occupied = conn.execute(
                "SELECT member_id FROM unit_primary_slots WHERE unit_id=? AND billet_id=?",
                (unit_id, billet_id),
            ).fetchone()
            if occupied and occupied["member_id"] != member_id:
                abort(
                    409,
                    description="This billet is already filled. Unassign its current member first.",
                )
        conn.execute(
            "DELETE FROM unit_member_placements WHERE unit_id=? AND member_id=?",
            (unit_id, member_id),
        )
        conn.execute(
            "DELETE FROM unit_primary_slots WHERE unit_id=? AND member_id=?",
            (unit_id, member_id),
        )
        if billet_id is not None:
            conn.execute(
                "INSERT INTO unit_primary_slots VALUES(?,?,?)",
                (unit_id, member_id, billet_id),
            )

    def assign_placement(conn, unit_id, member_id, parent_id):
        member = find_member(conn, unit_id, member_id)
        if parent_id is not None:
            target = structure_node(conn, unit_id, parent_id)
            if target["kind"] == "billet":
                raise ValueError("Choose a formation rather than a billet")
            if member["archived"]:
                raise ValueError("Restore this member before assigning a formation")
        conn.execute(
            "DELETE FROM unit_primary_slots WHERE unit_id=? AND member_id=?",
            (unit_id, member_id),
        )
        conn.execute(
            "DELETE FROM unit_member_placements WHERE unit_id=? AND member_id=?",
            (unit_id, member_id),
        )
        if parent_id is not None:
            conn.execute(
                "INSERT INTO unit_member_placements VALUES(?,?,?)",
                (unit_id, member_id, parent_id),
            )

    @api.app.post("/api/units/<int:unit_id>/placement")
    def unit_placement_save(unit_id):
        try:
            data = request.get_json()
            ids = data.get("member_ids", [])
            if (
                not isinstance(ids, list)
                or not 1 <= len(ids) <= 500
                or any(type(key) is not int for key in ids)
                or len(set(ids)) != len(ids)
            ):
                raise ValueError("Choose 1–500 distinct roster members")
            reason = text(data.get("reason", ""), "Assignment reason", 1000)
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "roster")
                revision(conn, unit_id, data)
                for member_id in ids:
                    before = roster_state(conn, unit_id, member_id)
                    assign_placement(conn, unit_id, member_id, data.get("parent_id"))
                    record_roster_change(
                        conn,
                        unit_id,
                        member_id,
                        before,
                        dict(history_reason=reason or "Direct formation placement"),
                    )
                sync_event_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                member_ids=ids,
                parent_id=data.get("parent_id"),
                change="formation placement",
            )
            return jsonify(ok=True, moved=len(ids))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/structure")
    def unit_structure_save(unit_id):
        data = request.get_json()
        try:
            kind = data.get("kind")
            name = text(data.get("name"), "Name", 80, True)
            if kind not in ("group", "section", "billet"):
                raise ValueError("Choose a group, section or billet")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                revision(conn, unit_id, data)
                identity = data.get("id")
                old = (
                    structure_node(conn, unit_id, identity)
                    if identity is not None
                    else None
                )
                previous_states = (
                    {
                        r[0]: roster_state(conn, unit_id, r[0])
                        for r in conn.execute(
                            "SELECT member_id FROM unit_primary_slots WHERE unit_id=? UNION SELECT member_id FROM unit_member_placements WHERE unit_id=?",
                            (unit_id, unit_id),
                        ).fetchall()
                    }
                    if old
                    else {}
                )
                if old and old["kind"] != kind:
                    raise ValueError("The item type cannot be changed")
                parent = data.get("parent_id")
                if kind == "group":
                    if parent is not None:
                        raise ValueError("Groups must be at the top level")
                else:
                    target = structure_node(conn, unit_id, parent)
                    if target["kind"] not in (("group", "section")):
                        raise ValueError("Choose a group or section as the parent")
                    ancestors = []
                    while target:
                        if target["id"] == identity:
                            raise ValueError(
                                "An item cannot be moved inside itself or its children"
                            )
                        ancestors.append(target["id"])
                        target = (
                            structure_node(conn, unit_id, target["parent_id"])
                            if target["parent_id"] is not None
                            else None
                        )
                    # Keep the editable hierarchy shallow enough to read and navigate.
                    descendants = (
                        conn.execute(
                            "WITH RECURSIVE tree(id,depth) AS (SELECT id,0 FROM unit_structure WHERE id=? AND unit_id=? UNION ALL SELECT n.id,t.depth+1 FROM unit_structure n JOIN tree t ON n.parent_id=t.id WHERE n.unit_id=?) SELECT COALESCE(MAX(depth),0) FROM tree",
                            (identity, unit_id, unit_id),
                        ).fetchone()[0]
                        if old
                        else 0
                    )
                    if len(ancestors) + descendants > 6:
                        raise ValueError("Use at most six levels below a group")
                if old:
                    order = (
                        old["sort_order"]
                        if old["parent_id"] == parent
                        else conn.execute(
                            "SELECT COALESCE(MAX(sort_order),-1)+1 FROM unit_structure WHERE unit_id=? AND parent_id IS ?",
                            (unit_id, parent),
                        ).fetchone()[0]
                    )
                    conn.execute(
                        "UPDATE unit_structure SET name=?,parent_id=?,sort_order=? WHERE id=? AND unit_id=?",
                        (name, parent, order, identity, unit_id),
                    )
                else:
                    if (
                        conn.execute(
                            "SELECT count(*) FROM unit_structure WHERE unit_id=?",
                            (unit_id,),
                        ).fetchone()[0]
                        >= 2000
                    ):
                        raise ValueError("Keep at most 2000 structure items per unit")
                    order = conn.execute(
                        "SELECT COALESCE(MAX(sort_order),-1)+1 FROM unit_structure WHERE unit_id=? AND parent_id IS ?",
                        (unit_id, parent),
                    ).fetchone()[0]
                    identity = conn.execute(
                        "INSERT INTO unit_structure(unit_id,parent_id,kind,name,sort_order) VALUES(?,?,?,?,?)",
                        (unit_id, parent, kind, name, order),
                    ).lastrowid
                if kind == "billet":
                    type_id = data.get(
                        "billet_type_id", old["billet_type_id"] if old else None
                    )
                    if type_id is not None:
                        if type(type_id) is not int:
                            raise ValueError("Choose a saved billet type")
                        definition = conn.execute(
                            "SELECT name FROM unit_billet_types WHERE unit_id=? AND id=?",
                            (unit_id, type_id),
                        ).fetchone()
                        if not definition:
                            raise ValueError(
                                "Choose a saved billet type from this unit"
                            )
                        name = definition["name"]
                    callsign = text(
                        data.get("callsign", old["callsign"] if old else ""),
                        "Billet callsign",
                        60,
                    )
                    conn.execute(
                        "UPDATE unit_structure SET billet_type_id=?,callsign=?,name=? WHERE unit_id=? AND id=?",
                        (type_id, callsign, name, unit_id, identity),
                    )
                for member_id, before in previous_states.items():
                    record_roster_change(
                        conn,
                        unit_id,
                        member_id,
                        before,
                        dict(history_reason="Roster structure renamed or moved"),
                    )
                sync_event_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                structure_id=identity,
                kind=kind,
                name=name,
                parent_id=parent,
                before=dict(old) if old else None,
            )
            return jsonify(ok=True, id=identity)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/structure/<int:node_id>/delete")
    def unit_structure_delete(unit_id, node_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                revision(conn, unit_id, data)
                node = structure_node(conn, unit_id, node_id)
                if data.get("confirm_name") != node["name"]:
                    raise ValueError("Type the item’s name exactly to confirm removal")
                ids = [
                    row[0]
                    for row in conn.execute(
                        "WITH RECURSIVE tree(id) AS (SELECT id FROM unit_structure WHERE unit_id=? AND id=? UNION ALL SELECT n.id FROM unit_structure n JOIN tree t ON n.parent_id=t.id WHERE n.unit_id=?) SELECT id FROM tree",
                        (unit_id, node_id, unit_id),
                    )
                ]
                for event in conn.execute(
                    "SELECT name,formation_ids FROM unit_events WHERE unit_id=? AND starts>? AND state='scheduled'",
                    (unit_id, time.time()),
                ):
                    if set(json.loads(event["formation_ids"])) & set(ids):
                        raise ValueError(
                            "Update the formation audience for "
                            + event["name"]
                            + " before removing this formation"
                        )
                marks = ",".join("?" for _ in ids)
                released = [
                    row[0]
                    for row in conn.execute(
                        f"SELECT member_id FROM unit_primary_slots WHERE unit_id=? AND billet_id IN ({marks}) UNION SELECT member_id FROM unit_member_placements WHERE unit_id=? AND parent_id IN ({marks})",
                        (unit_id, *ids, unit_id, *ids),
                    )
                ]
                previous_states = {
                    member_id: roster_state(conn, unit_id, member_id)
                    for member_id in released
                }
                conn.execute(
                    f"DELETE FROM unit_primary_slots WHERE unit_id=? AND billet_id IN ({marks})",
                    (unit_id, *ids),
                )
                conn.execute(
                    f"DELETE FROM unit_member_placements WHERE unit_id=? AND parent_id IN ({marks})",
                    (unit_id, *ids),
                )
                conn.execute(
                    f"UPDATE unit_temporary_assignments SET cancelled=1 WHERE unit_id=? AND billet_id IN ({marks})",
                    (unit_id, *ids),
                )
                conn.execute(
                    f"DELETE FROM unit_structure WHERE unit_id=? AND id IN ({marks})",
                    (unit_id, *ids),
                )
                for member_id, before in previous_states.items():
                    record_roster_change(
                        conn,
                        unit_id,
                        member_id,
                        before,
                        dict(
                            history_reason="Roster structure removed: " + node["name"]
                        ),
                    )
                sync_event_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                removed_structure=ids,
                released_members=released,
                name=node["name"],
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/structure/<int:node_id>/order")
    def unit_structure_order(unit_id, node_id):
        data = request.get_json()
        if data.get("direction") not in ("up", "down"):
            return jsonify(ok=False, error="Choose up or down"), 400
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                revision(conn, unit_id, data)
                node = structure_node(conn, unit_id, node_id)
                siblings = [
                    row[0]
                    for row in conn.execute(
                        "SELECT id FROM unit_structure WHERE unit_id=? AND parent_id IS ? ORDER BY sort_order,id",
                        (unit_id, node["parent_id"]),
                    )
                ]
                index = siblings.index(node_id)
                target = index + (-1 if data["direction"] == "up" else 1)
                if 0 <= target < len(siblings):
                    siblings[index], siblings[target] = (
                        siblings[target],
                        siblings[index],
                    )
                conn.executemany(
                    "UPDATE unit_structure SET sort_order=? WHERE id=? AND unit_id=?",
                    [(i, key, unit_id) for i, key in enumerate(siblings)],
                )
            g.audit_details = dict(
                unit_id=unit_id, structure_id=node_id, direction=data["direction"]
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/assignment")
    def unit_primary_assign(unit_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "roster")
                revision(conn, unit_id, data)
                billet = data.get("billet_id")
                member = data.get("member_id")
                structure_node(conn, unit_id, billet, "billet")
                if member is not None and type(member) is not int:
                    raise ValueError("Choose a roster member")
                occupant_row = conn.execute(
                    "SELECT member_id FROM unit_primary_slots WHERE unit_id=? AND billet_id=?",
                    (unit_id, billet),
                ).fetchone()
                occupant = occupant_row["member_id"] if occupant_row else None
                if "expected_occupant" in data and (
                    data["expected_occupant"] is not None
                    and type(data["expected_occupant"]) is not int
                    or data["expected_occupant"] != occupant
                ):
                    abort(
                        409, description="This billet changed. Reopen the assignment."
                    )
                strategy = data.get("conflict", "error")
                if strategy not in ("error", "replace", "swap"):
                    raise ValueError("Choose a valid assignment action")
                reason = text(data.get("reason", ""), "Assignment reason", 1000)
                conflict = (
                    member is not None and occupant is not None and occupant != member
                )
                source = None
                source_placement = None
                if member is not None:
                    incoming = find_member(conn, unit_id, member)
                    if incoming["archived"]:
                        raise ValueError(
                            "Restore this member before assigning a billet"
                        )
                    previous = conn.execute(
                        "SELECT billet_id FROM unit_primary_slots WHERE unit_id=? AND member_id=?",
                        (unit_id, member),
                    ).fetchone()
                    source = previous["billet_id"] if previous else None
                    direct = conn.execute(
                        "SELECT parent_id FROM unit_member_placements WHERE unit_id=? AND member_id=?",
                        (unit_id, member),
                    ).fetchone()
                    source_placement = direct["parent_id"] if direct else None
                if conflict:
                    if strategy == "error":
                        abort(
                            409,
                            description="This billet is filled. Choose Swap or Move current member to Unassigned.",
                        )
                    if data.get("confirmed") is not True:
                        raise ValueError("Confirm how the current member will be moved")
                    if (
                        strategy == "swap"
                        and source is None
                        and source_placement is None
                    ):
                        raise ValueError(
                            "A swap needs the incoming member to have a primary placement"
                        )
                affected = {key for key in (member, occupant) if key is not None}
                before = {key: roster_state(conn, unit_id, key) for key in affected}
                if member is None:
                    conn.execute(
                        "DELETE FROM unit_primary_slots WHERE unit_id=? AND billet_id=?",
                        (unit_id, billet),
                    )
                else:
                    if conflict:
                        conn.execute(
                            "DELETE FROM unit_primary_slots WHERE unit_id=? AND member_id IN (?,?)",
                            (unit_id, member, occupant),
                        )
                    assign_slot(conn, unit_id, member, billet)
                    if conflict and strategy == "swap":
                        if source is not None:
                            assign_slot(conn, unit_id, occupant, source)
                        else:
                            assign_placement(conn, unit_id, occupant, source_placement)
                for key in affected:
                    record_roster_change(
                        conn,
                        unit_id,
                        key,
                        before[key],
                        dict(
                            history_reason=reason
                            or "Primary billet assignment"
                            + (" · " + strategy if conflict else "")
                        ),
                    )
                sync_event_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                billet_id=billet,
                member_id=member,
                displaced_member=occupant if conflict else None,
                action=(
                    strategy
                    if conflict
                    else "assign" if member is not None else "unassign"
                ),
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def branding(conn, unit_id):
        row = conn.execute(
            "SELECT * FROM unit_branding WHERE unit_id=?",
            (unit_id,),
        ).fetchone()
        values = dict(row) if row else {}
        token = hashlib.sha256(
            json.dumps(
                {
                    key: (
                        hashlib.sha256(value).hexdigest()
                        if isinstance(value, bytes)
                        else value
                    )
                    for key, value in values.items()
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return dict(
            description=values.get("description", ""),
            icon=bool(values.get("icon")),
            banner=bool(values.get("banner")),
            token=token,
        )

    @api.app.get("/api/units/<int:unit_id>/branding/<kind>")
    def unit_branding_image(unit_id, kind):
        if kind not in ("icon", "banner"):
            abort(404)
        with db() as conn:
            access(conn, unit_id)
            row = conn.execute(
                f"SELECT {kind}, {kind}_type FROM unit_branding WHERE unit_id=?",
                (unit_id,),
            ).fetchone()
            if not row or not row[kind]:
                abort(404, description="No image uploaded")
        response = send_file(
            io.BytesIO(row[kind]), mimetype=row[kind + "_type"], max_age=0
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @api.app.post("/api/units/<int:unit_id>/branding")
    def unit_branding_save(unit_id):
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                try:
                    version = int(request.form.get("revision", ""))
                except ValueError:
                    raise ValueError("Reload the unit before saving")
                token = request.form.get("branding_token")
                if token:
                    if not hmac.compare_digest(token, branding(conn, unit_id)["token"]):
                        abort(
                            409,
                            description="Branding was changed by another editor. Your selected images and crop are preserved. Review the latest branding before replacing it.",
                        )
                    conn.execute(
                        "UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,)
                    )
                else:
                    revision(conn, unit_id, dict(revision=version))
                description = text(
                    request.form.get("description", ""), "Description", 160
                )
                images = {}
                for kind in ("icon", "banner"):
                    upload = request.files.get(kind)
                    if upload and upload.filename:
                        data = upload.stream.read(4 * 1024 * 1024 + 1)
                        if len(data) > 4 * 1024 * 1024:
                            raise ValueError("Each image must be 4 MB or smaller")
                        mime = (
                            "image/png"
                            if data.startswith(b"\x89PNG\r\n\x1a\n")
                            else (
                                "image/jpeg"
                                if data.startswith(b"\xff\xd8\xff")
                                else (
                                    "image/webp"
                                    if data[:4] == b"RIFF" and data[8:12] == b"WEBP"
                                    else None
                                )
                            )
                        )
                        if not mime:
                            raise ValueError("Upload PNG, JPEG or WebP images")
                        images[kind] = (data, mime)
                    elif request.form.get("remove_" + kind) == "on":
                        images[kind] = (None, None)
                conn.execute(
                    "INSERT OR IGNORE INTO unit_branding(unit_id) VALUES(?)", (unit_id,)
                )
                conn.execute(
                    "UPDATE unit_branding SET description=? WHERE unit_id=?",
                    (description, unit_id),
                )
                for kind, (data, mime) in images.items():
                    conn.execute(
                        f"UPDATE unit_branding SET {kind}=?,{kind}_type=? WHERE unit_id=?",
                        (data, mime, unit_id),
                    )
            g.audit_details = dict(
                unit_id=unit_id, branding=list(images), description_changed=True
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.get("/api/units/<int:unit_id>")
    def unit_detail(unit_id):
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            unit = access(conn, unit_id)
            expired = conn.execute(
                "SELECT id FROM unit_roster WHERE unit_id=? AND status='loa' AND loa_until!='' AND loa_until<? AND archived=0",
                (unit_id, date.today().isoformat()),
            ).fetchall()
            for row in expired:
                before = roster_state(conn, unit_id, row["id"])
                conn.execute(
                    "UPDATE unit_roster SET status='active',updated_at=? WHERE unit_id=? AND id=?",
                    (time.time(), unit_id, row["id"]),
                )
                record_roster_change(
                    conn,
                    unit_id,
                    row["id"],
                    before,
                    dict(history_reason="LOA ended; returned to Active"),
                )
            if expired:
                conn.execute(
                    "UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,)
                )
                sync_event_roster(conn, unit_id)
                unit = access(conn, unit_id)
            roster = [
                dict(r)
                for r in conn.execute(
                    "SELECT r.*,u.username AS panel_username,u.enabled AS panel_user_enabled, EXISTS(SELECT 1 FROM unit_account_suspensions x WHERE x.unit_id=r.unit_id AND x.user_id=r.panel_user_id) AS unit_login_suspended FROM unit_roster r LEFT JOIN users u ON u.id=r.panel_user_id WHERE r.unit_id=? ORDER BY r.archived,r.game_name COLLATE NOCASE,r.id",
                    (unit_id,),
                )
            ]
            membership = conn.execute(
                "SELECT role,capabilities FROM unit_staff WHERE unit_id=? AND user_id=?",
                (unit_id, g.user["id"]),
            ).fetchone()
            if not panel_admin() and membership["role"] == "member":
                public_unit = {key: unit[key] for key in ("id", "name", "revision")}
                decorate_slots(conn, unit_id, roster)
                public_roster = [
                    {
                        key: m[key]
                        for key in (
                            "id",
                            "game_name",
                            "rank",
                            "rank_track",
                            "rank_display",
                            "rank_abbreviation",
                            "status",
                            "certificates",
                            "billet_id",
                            "billet_path",
                            "placement_id",
                            "assignment_path",
                            "effective_callsign",
                            "expired_certificates",
                            "qualification_expiries",
                        )
                    }
                    for m in roster
                    if not m["archived"]
                ]
                for m in public_roster:
                    m.update(
                        archived=False,
                        promotion=dict(
                            eligible=False, next_rank="", next_date="", missing=[]
                        ),
                    )
                return jsonify(
                    unit=dict(
                        public_unit, catalog={}, branding=branding(conn, unit_id)
                    ),
                    temporary_covers=[
                        {
                            key: item[key]
                            for key in (
                                "id",
                                "member_id",
                                "billet_id",
                                "game_name",
                                "starts_on",
                                "ends_on",
                            )
                        }
                        for item in personnel_coverage(conn, unit_id)
                    ],
                    sync_token=collaboration_snapshot(conn, unit_id)["token"],
                    role="member",
                    structure=structure_rows(conn, unit_id),
                    roster=public_roster,
                    staff=[],
                    accounts=[],
                    can_edit=False,
                    can_staff=False,
                    can_delete=False,
                    can_settings=False,
                )
            catalog = json.loads(unit["catalog"])
            structure = structure_rows(conn, unit_id)
            billet_types = [
                dict(row)
                for row in conn.execute(
                    "SELECT id,name FROM unit_billet_types WHERE unit_id=? ORDER BY name COLLATE NOCASE",
                    (unit_id,),
                )
            ]
            decorate_slots(conn, unit_id, roster, structure)
            for member in roster:
                member["promotion"] = promotion(member, catalog)
            unit_brand = branding(conn, unit_id)
            admin = panel_admin() or membership["role"] == "admin"
            accounts = (
                [
                    dict(r)
                    for r in conn.execute(
                        "SELECT id,username,enabled FROM users ORDER BY username"
                    )
                ]
                if panel_admin()
                else [
                    dict(r)
                    for r in conn.execute(
                        "SELECT u.id,u.username,u.enabled FROM users u JOIN unit_staff s ON s.user_id=u.id WHERE s.unit_id=? ORDER BY u.username",
                        (unit_id,),
                    )
                ]
            )
            staff = (
                [
                    dict(r, capabilities=list(unit_role_capabilities(r["role"])))
                    for r in conn.execute(
                        "SELECT s.*,u.username,u.enabled FROM unit_staff s JOIN users u ON u.id=s.user_id WHERE unit_id=? ORDER BY username",
                        (unit_id,),
                    )
                ]
                if admin
                else []
            )
            temporary_covers = [
                {
                    key: item[key]
                    for key in (
                        "id",
                        "member_id",
                        "billet_id",
                        "game_name",
                        "starts_on",
                        "ends_on",
                    )
                }
                for item in personnel_coverage(conn, unit_id)
            ]
            sync_token = collaboration_snapshot(conn, unit_id)["token"]
        return jsonify(
            temporary_covers=temporary_covers,
            sync_token=sync_token,
            unit=dict(unit, catalog=catalog, branding=unit_brand),
            billet_types=billet_types,
            structure=structure,
            roster=roster,
            staff=staff,
            can_edit=admin or "roster" in unit_role_capabilities(membership["role"]),
            can_staff=admin,
            can_delete=admin,
            accounts=accounts,
            can_settings=panel_admin(),
        )

    def find_member(conn, unit_id, member_id):
        member = conn.execute(
            "SELECT r.*,u.username AS panel_username,u.enabled AS panel_user_enabled, EXISTS(SELECT 1 FROM unit_account_suspensions x WHERE x.unit_id=r.unit_id AND x.user_id=r.panel_user_id) AS unit_login_suspended FROM unit_roster r LEFT JOIN users u ON u.id=r.panel_user_id WHERE r.unit_id=? AND r.id=?",
            (unit_id, member_id),
        ).fetchone()
        if not member:
            abort(404, description="Member not found in this unit")
        return member

    @api.app.get("/api/units/<int:unit_id>/roster/<int:member_id>/record")
    def unit_member_record(unit_id, member_id):
        try:
            before = int(request.args.get("before", "0"))
            if not 0 <= before <= 9223372036854775807:
                raise ValueError()
        except ValueError:
            return jsonify(ok=False, error="Choose a valid record history cursor"), 400
        with db() as conn:
            unit = access(conn, unit_id)
            member = dict(find_member(conn, unit_id, member_id))
            decorate_slots(conn, unit_id, [member])
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT id,author_name,created_at,note,edited_at,edited_by,version FROM unit_member_notes WHERE unit_id=? AND member_id=? AND (?=0 OR id<?) ORDER BY id DESC LIMIT 51",
                    (unit_id, member_id, before, before),
                )
            ]
            membership = conn.execute(
                "SELECT role,capabilities FROM unit_staff WHERE unit_id=? AND user_id=?",
                (unit_id, g.user["id"]),
            ).fetchone()
            qualifications = [
                dict(row)
                for row in conn.execute(
                    "SELECT certificate,awarded_on,expires_on,issuer,notes FROM unit_qualification_awards WHERE unit_id=? AND member_id=? ORDER BY certificate",
                    (unit_id, member_id),
                )
            ]
            can_write = (
                panel_admin()
                or membership["role"] == "admin"
                or "roster" in unit_role_capabilities(membership["role"])
            )
        return jsonify(
            catalog=json.loads(unit["catalog"]),
            member=dict(
                member, promotion=promotion(member, json.loads(unit["catalog"]))
            ),
            qualifications=qualifications,
            notes=rows[:50],
            next_before=rows[49]["id"] if len(rows) > 50 else None,
            can_write=can_write,
            can_delete=panel_admin() or membership["role"] == "admin",
            can_award=panel_admin()
            or membership["role"] == "admin"
            or "awards" in unit_role_capabilities(membership["role"]),
        )

    @api.app.post("/api/units/<int:unit_id>/roster/<int:member_id>/login")
    def unit_member_login_create(unit_id, member_id):
        data = request.get_json()
        try:
            if data.get("role", "member") != "member" or any(
                key in data for key in ("panel_admin", "access_all", "server_roles")
            ):
                raise ValueError("This action creates a Member login only")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "roster")
                revision(conn, unit_id, data)
                member = find_member(conn, unit_id, member_id)
                if member["archived"]:
                    raise ValueError(
                        "Restore this roster member before creating a login"
                    )
                if member["panel_user_id"] is not None:
                    abort(409, description="This member already has a linked login")
                username = text(data.get("username"), "Username", 32, True)
                user_id = api.create_unit_login(
                    conn,
                    username,
                    data.get("password"),
                    unit_id=unit_id,
                    allow_unit_staff=True,
                )
                conn.execute(
                    "INSERT INTO unit_staff(unit_id,user_id,role,capabilities) VALUES(?,?,'member','[]')",
                    (unit_id, user_id),
                )
                conn.execute(
                    "UPDATE unit_roster SET panel_user_id=?,updated_at=? WHERE unit_id=? AND id=?",
                    (user_id, time.time(), unit_id, member_id),
                )
            g.audit_details = dict(
                unit_id=unit_id,
                member_id=member_id,
                username=username,
                change="member login created",
            )
            return jsonify(ok=True, username=username)
        except (ValueError, sqlite3.IntegrityError) as exc:
            return (
                jsonify(
                    ok=False,
                    error=(
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "This username or member link is already in use"
                    ),
                ),
                400,
            )

    @api.app.post("/api/units/<int:unit_id>/roster/<int:member_id>/record")
    def unit_member_note_save(unit_id, member_id):
        data = request.get_json()
        try:
            note = text(data.get("note"), "Record note", 4000, True)
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "roster")
                find_member(conn, unit_id, member_id)
                author_name = actor(conn, unit_id)
                identity = conn.execute(
                    "INSERT INTO unit_member_notes(unit_id,member_id,author_id,author_name,created_at,note) VALUES(?,?,?,?,?,?)",
                    (unit_id, member_id, g.user["id"], author_name, time.time(), note),
                ).lastrowid
            g.audit_details = dict(
                unit_id=unit_id, member_id=member_id, note_id=identity
            )
            return jsonify(ok=True, id=identity)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post(
        "/api/units/<int:unit_id>/roster/<int:member_id>/record/<int:note_id>/edit"
    )
    def unit_member_note_edit(unit_id, member_id, note_id):
        data = request.get_json()
        try:
            if not isinstance(data, dict) or type(data.get("version")) is not int:
                raise ValueError("Reload the note before editing")
            note = text(data.get("note"), "Record note", 4000, True)
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "roster")
                find_member(conn, unit_id, member_id)
                if not 1 <= note_id <= 9223372036854775807:
                    abort(404, description="Note not found")
                previous = conn.execute(
                    "SELECT version FROM unit_member_notes WHERE unit_id=? AND member_id=? AND id=?",
                    (unit_id, member_id, note_id),
                ).fetchone()
                if not previous:
                    abort(404, description="Note not found in this member record")
                if previous["version"] != data["version"]:
                    abort(
                        409,
                        description="This note changed. Reopen the member record before editing.",
                    )
                edited_at = time.time()
                edited_by = actor(conn, unit_id)
                conn.execute(
                    "UPDATE unit_member_notes SET note=?,edited_at=?,edited_by=?,version=version+1 WHERE unit_id=? AND member_id=? AND id=?",
                    (note, edited_at, edited_by, unit_id, member_id, note_id),
                )
                conn.execute(
                    "UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,)
                )
            g.audit_details = dict(
                unit_id=unit_id,
                member_id=member_id,
                note_id=note_id,
                change="record note edited",
            )
            return jsonify(
                ok=True,
                note=note,
                edited_at=edited_at,
                edited_by=edited_by,
                version=data["version"] + 1,
            )
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post(
        "/api/units/<int:unit_id>/roster/<int:member_id>/record/<int:note_id>/delete"
    )
    def unit_member_note_delete(unit_id, member_id, note_id):
        data = request.get_json()
        if not isinstance(data, dict) or data.get("confirmed") is not True:
            return jsonify(ok=False, error="Confirm note deletion"), 400
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            access(conn, unit_id, "roster")
            find_member(conn, unit_id, member_id)
            if not 1 <= note_id <= 9223372036854775807:
                abort(404, description="Note not found in this member record")
            note = conn.execute(
                "SELECT id,author_name FROM unit_member_notes WHERE unit_id=? AND member_id=? AND id=?",
                (unit_id, member_id, note_id),
            ).fetchone()
            if not note:
                abort(404, description="Note not found in this member record")
            conn.execute(
                "DELETE FROM unit_member_notes WHERE unit_id=? AND member_id=? AND id=?",
                (unit_id, member_id, note_id),
            )
            # Invalidate collaboration tokens even when deleting an older note.
            conn.execute("UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,))
        g.audit_details = dict(
            unit_id=unit_id,
            member_id=member_id,
            note_id=note_id,
            author=note["author_name"],
            change="record note deleted",
        )
        return jsonify(ok=True)

    def recorded(conn, unit_id):
        links = [
            r["server_id"]
            for r in conn.execute(
                "SELECT server_id FROM unit_servers WHERE unit_id=?", (unit_id,)
            )
        ]
        if not links:
            return []
        marks = ",".join("?" for _ in links)
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT lower(identity) AS identity,name,last_seen FROM player_history WHERE server_id IN ({marks}) ORDER BY last_seen DESC",
                links,
            )
            if UUID.fullmatch(r["identity"])
        ]

    @api.app.get("/api/units/<int:unit_id>/identities")
    def unit_identities(unit_id):
        with db() as conn:
            access(conn, unit_id, "roster")
            query = request.args.get("q", "").strip().casefold()
            if len(query) > 120:
                abort(400, description="Search must be at most 120 characters")
            unique = {}
            for row in recorded(conn, unit_id):
                if row["identity"] not in unique and (
                    query in row["name"].casefold() or query in row["identity"]
                ):
                    unique[row["identity"]] = row
            rows = list(unique.values())
        return jsonify(players=rows[:100], more=len(rows) > 100)

    def member_values(conn, unit_id, data, existing=None):
        values = {
            field: text(
                data.get(field, ""),
                field,
                (
                    8000
                    if field in ("certificates", "position")
                    else (
                        2000 if field == "notes" else 60 if field == "callsign" else 120
                    )
                ),
                field == "game_name",
            )
            for field in FIELDS
        }
        if values["status"] not in ("active", "reserve", "loa"):
            raise ValueError("Choose Active, Reserve or LOA")
        identity = values["identity"].lower()
        if identity and (
            not UUID.fullmatch(identity)
            or identity != (existing["identity"] if existing else "")
            and identity not in {r["identity"] for r in recorded(conn, unit_id)}
        ):
            raise ValueError("Choose a recorded UUID from a server linked to this unit")
        values["identity"] = identity
        catalog = json.loads(
            conn.execute("SELECT catalog FROM units WHERE id=?", (unit_id,)).fetchone()[
                "catalog"
            ]
        )
        certs = [c.strip() for c in values["certificates"].split(";") if c.strip()]
        if any(c not in catalog.get("certificates", []) for c in certs):
            raise ValueError("Choose qualifications from the unit catalog")
        archived = {
            entry["name"]
            for entry in catalog.get("qualification_details", [])
            if entry.get("archived")
        }
        previous = set(existing["certificates"].split(";")) if existing else set()
        if any(name in archived and name not in previous for name in certs):
            raise ValueError("Archived qualifications cannot be newly awarded")
        values["certificates"] = ";".join(sorted(set(certs)))
        positions = [p.strip() for p in values["position"].split(";") if p.strip()]
        if any(p not in catalog.get("positions", []) for p in positions) and values[
            "position"
        ] != (existing["position"] if existing else ""):
            raise ValueError("Choose positions from the unit catalog")
        values["position"] = ";".join(sorted(set(positions)))
        structures = catalog.get("rank_structures", [])
        if values["rank"] and not values["rank_track"] and len(structures) == 1:
            values["rank_track"] = structures[0]["name"]
        structure = next(
            (s for s in structures if s["name"] == values["rank_track"]), None
        )
        if values["rank_track"] and not structure:
            raise ValueError("Choose a rank structure from this unit")
        if values["rank"] and (
            not structure
            or values["rank"] not in {r["name"] for r in structure["ranks"]}
        ):
            raise ValueError(
                "Choose a rank from the selected structure, or leave it blank"
            )
        for field in ("joined_on", "loa_from", "loa_until", "last_promo"):
            if values[field]:
                try:
                    values[field] = date.fromisoformat(values[field]).isoformat()
                except ValueError:
                    raise ValueError(f"{field}: choose a valid date") from None
        if (
            values["loa_from"]
            and values["loa_until"]
            and values["loa_from"] > values["loa_until"]
        ):
            raise ValueError("LOA end date must be on or after its start date")
        if values["last_promo"] and values["last_promo"] > date.today().isoformat():
            raise ValueError("Last promotion date cannot be in the future")
        return values

    @api.app.post("/api/units/<int:unit_id>/roster")
    def unit_roster_save(unit_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "roster")
                member_id = data.get("id")
                if member_id is None:
                    revision(conn, unit_id, data)
                else:
                    member_revision(conn, unit_id, data, member_id)
                existing = conn.execute(
                    "SELECT * FROM unit_roster WHERE id=? AND unit_id=?",
                    (member_id, unit_id),
                ).fetchone()
                if member_id is not None and not existing:
                    abort(404, description="Member not found in this unit")
                if type(data.get("archived", False)) is not bool:
                    raise ValueError("Choose a valid membership state")
                previous_state = (
                    roster_state(conn, unit_id, member_id) if existing else None
                )
                values = member_values(conn, unit_id, data, existing)
                account_id = data.get(
                    "panel_user_id", existing["panel_user_id"] if existing else None
                )
                if account_id != (existing["panel_user_id"] if existing else None):
                    access(conn, unit_id, "staff")
                if account_id is not None:
                    if (
                        type(account_id) is not int
                        or not conn.execute(
                            "SELECT 1 FROM users WHERE id=?", (account_id,)
                        ).fetchone()
                    ):
                        raise ValueError(
                            "Choose an existing panel account, or leave the member unlinked"
                        )
                    unchanged = existing and existing["panel_user_id"] == account_id
                    if (
                        not unchanged
                        and not panel_admin()
                        and not conn.execute(
                            "SELECT 1 FROM unit_staff WHERE unit_id=? AND user_id=?",
                            (unit_id, account_id),
                        ).fetchone()
                    ):
                        raise ValueError(
                            "Choose a staff account already assigned to this unit"
                        )
                    if conn.execute(
                        "SELECT 1 FROM unit_roster WHERE unit_id=? AND panel_user_id=? AND id!=?",
                        (unit_id, account_id, member_id or 0),
                    ).fetchone():
                        raise ValueError(
                            "That panel account is already linked to a roster member in this unit"
                        )
                if existing:
                    conn.execute(
                        "UPDATE unit_roster SET "
                        + ",".join(f"{k}=?" for k in FIELDS)
                        + ",archived=?,panel_user_id=?,updated_at=? WHERE id=? AND unit_id=?",
                        (
                            *values.values(),
                            int(data.get("archived", False)),
                            account_id,
                            time.time(),
                            member_id,
                            unit_id,
                        ),
                    )
                else:
                    # Deleted record URLs must never resolve to a different person.
                    member_id = conn.execute(
                        "SELECT COALESCE(MAX(id),0)+1 FROM (SELECT id FROM unit_roster UNION ALL SELECT id FROM unit_roster_deleted_ids)"
                    ).fetchone()[0]
                    conn.execute(
                        "INSERT INTO unit_roster(id,unit_id,"
                        + ",".join(FIELDS)
                        + ",archived,panel_user_id,created_at,updated_at) VALUES("
                        + ",".join("?" for _ in range(len(FIELDS) + 6))
                        + ")",
                        (
                            member_id,
                            unit_id,
                            *values.values(),
                            int(data.get("archived", False)),
                            account_id,
                            time.time(),
                            time.time(),
                        ),
                    )
                if data.get("archived", False):
                    conn.execute(
                        "UPDATE unit_temporary_assignments SET cancelled=1 WHERE unit_id=? AND member_id=?",
                        (unit_id, member_id),
                    )
                    conn.execute(
                        "DELETE FROM unit_member_placements WHERE unit_id=? AND member_id=?",
                        (unit_id, member_id),
                    )
                    conn.execute(
                        "DELETE FROM unit_primary_slots WHERE unit_id=? AND member_id=?",
                        (unit_id, member_id),
                    )
                elif "placement_id" in data:
                    assign_placement(conn, unit_id, member_id, data["placement_id"])
                elif "billet_id" in data:
                    assign_slot(conn, unit_id, member_id, data["billet_id"])
                record_roster_change(conn, unit_id, member_id, previous_state, data)
                sync_event_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                member_id=member_id,
                billet_id=data.get("billet_id"),
                before=(
                    {f: existing[f] for f in (*FIELDS, "archived", "panel_user_id")}
                    if existing
                    else None
                ),
                after=dict(
                    values,
                    archived=data.get("archived", False),
                    panel_user_id=account_id,
                ),
            )
            return jsonify(ok=True, id=member_id)
        except (ValueError, sqlite3.IntegrityError) as exc:
            return (
                jsonify(
                    ok=False,
                    error=(
                        "That UUID or panel account already has a roster record in this unit; edit or restore it instead"
                        if isinstance(exc, sqlite3.IntegrityError)
                        else str(exc)
                    ),
                ),
                400,
            )

    @api.app.post("/api/units/<int:unit_id>/roster/<int:member_id>/delete")
    def unit_roster_delete(unit_id, member_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                member = find_member(conn, unit_id, member_id)
                revision(conn, unit_id, data)
                if data.get("confirm_name") != member["game_name"]:
                    raise ValueError(
                        "Type the member’s game name exactly to confirm deletion"
                    )
                previous_state = roster_state(conn, unit_id, member_id)
                notes = conn.execute(
                    "SELECT count(*) FROM unit_member_notes WHERE unit_id=? AND member_id=?",
                    (unit_id, member_id),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO unit_roster_deleted_ids VALUES(?)", (member_id,)
                )
                conn.execute(
                    "DELETE FROM unit_member_notes WHERE unit_id=? AND member_id=?",
                    (unit_id, member_id),
                )
                conn.execute(
                    "DELETE FROM unit_primary_slots WHERE unit_id=? AND member_id=?",
                    (unit_id, member_id),
                )
                conn.execute(
                    "DELETE FROM unit_qualification_awards WHERE unit_id=? AND member_id=?",
                    (unit_id, member_id),
                )
                conn.execute(
                    "DELETE FROM unit_roster_history WHERE unit_id=? AND member_id=?",
                    (unit_id, member_id),
                )
                conn.execute(
                    "DELETE FROM unit_member_awards WHERE unit_id=? AND member_id=?",
                    (unit_id, member_id),
                )
                conn.execute(
                    "DELETE FROM unit_resource_audit WHERE unit_id=? AND member_id=?",
                    (unit_id, member_id),
                )
                conn.execute(
                    "DELETE FROM unit_member_placements WHERE unit_id=? AND member_id=?",
                    (unit_id, member_id),
                )
                conn.execute(
                    "DELETE FROM unit_roster WHERE unit_id=? AND id=?",
                    (unit_id, member_id),
                )
                conn.execute(
                    "UPDATE unit_temporary_assignments SET cancelled=1 WHERE unit_id=? AND member_id=?",
                    (unit_id, member_id),
                )
                record_strength(conn, unit_id, previous_state, None)
                sync_event_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                member_id=member_id,
                game_name=member["game_name"],
                deleted_notes=notes,
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/staff")
    def unit_staff_save(unit_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                revision(conn, unit_id, data)
                username = text(data.get("username"), "Username", 32, True)
                if type(data.get("create_account", False)) is not bool:
                    raise ValueError("Choose a new or existing account")
                if data.get("create_account"):
                    if data.get("role") not in ("member", "staff", "admin"):
                        raise ValueError("Choose Member, Staff or Unit administrator")
                    user_id = api.create_unit_login(
                        conn, username, data.get("password"), unit_id=unit_id
                    )
                    user = conn.execute(
                        "SELECT * FROM users WHERE id=?", (user_id,)
                    ).fetchone()
                else:
                    user = conn.execute(
                        "SELECT * FROM users WHERE username=? COLLATE NOCASE",
                        (username,),
                    ).fetchone()
                if not user:
                    raise ValueError(
                        "No matching panel account. Ask a panel administrator to create it first."
                    )
                role = data.get("role")
                capabilities = list(unit_role_capabilities(role))
                if role != "remove":
                    if not user["enabled"]:
                        raise ValueError(
                            "Ask a panel administrator to enable this account first"
                        )
                    validate_staff(role)
                protect_admin(conn, unit_id, user["id"], role)
                conn.execute(
                    "DELETE FROM unit_account_suspensions WHERE unit_id=? AND user_id=?",
                    (unit_id, user["id"]),
                )
                conn.execute(
                    "DELETE FROM unit_staff WHERE unit_id=? AND user_id=?",
                    (unit_id, user["id"]),
                )
                if role != "remove":
                    conn.execute(
                        "INSERT INTO unit_staff VALUES(?,?,?,?)",
                        (unit_id, user["id"], role, json.dumps(capabilities)),
                    )
                    if "link_member_id" in data:
                        member_id = data["link_member_id"]
                        if member_id is not None:
                            if type(member_id) is not int:
                                raise ValueError(
                                    "Choose a roster member or leave unlinked"
                                )
                            member = find_member(conn, unit_id, member_id)
                            if member["panel_user_id"] not in (None, user["id"]):
                                raise ValueError(
                                    "That member is already linked to another account"
                                )
                            if (
                                member["archived"]
                                and member["panel_user_id"] != user["id"]
                            ):
                                raise ValueError(
                                    "Restore the roster member before linking a new account"
                                )
                        conn.execute(
                            "UPDATE unit_roster SET panel_user_id=NULL WHERE unit_id=? AND panel_user_id=?",
                            (unit_id, user["id"]),
                        )
                        if member_id is not None:
                            conn.execute(
                                "UPDATE unit_roster SET panel_user_id=? WHERE unit_id=? AND id=?",
                                (user["id"], unit_id, member_id),
                            )
            g.audit_details = dict(
                unit_id=unit_id,
                username=user["username"],
                role=role,
                capabilities=capabilities,
                created_account=bool(data.get("create_account")),
                linked_member=data.get("link_member_id"),
            )
            return jsonify(ok=True)
        except (ValueError, sqlite3.IntegrityError) as exc:
            return (
                jsonify(
                    ok=False,
                    error=(
                        "Username is already in use; select Existing account instead"
                        if isinstance(exc, sqlite3.IntegrityError)
                        else str(exc)
                    ),
                ),
                400,
            )

    @api.app.get("/api/units/<int:unit_id>/health")
    def unit_health(unit_id):
        with db() as conn:
            access(conn, unit_id)
            links = [
                r["server_id"]
                for r in conn.execute(
                    "SELECT server_id FROM unit_servers WHERE unit_id=?", (unit_id,)
                )
            ]
        rows = []
        user = dict(g.user)
        for server_id in links:
            try:
                with api.operator_tools.selected(server_id):
                    pid = api.get_server_pid()
                    cpu, ram = api.get_cpu_ram(pid) if pid else (0, 0)
                    rows.append(
                        dict(
                            id=server_id,
                            running=bool(pid),
                            cpu=cpu,
                            ram_process=ram,
                            can_open=bool(api.server_permissions(user, server_id)),
                        )
                    )
            except (ValueError, KeyError, api.ConfigReadError):
                rows.append(dict(id=server_id, unavailable=True))
        return jsonify(servers=rows)

    def export_cell(value):
        # Spreadsheet formulas must remain literal when the CSV is opened.
        return (
            "'" + str(value)
            if str(value).lstrip().startswith(("=", "+", "-", "@"))
            else str(value)
        )

    @api.app.get("/api/units/<int:unit_id>/roster.csv")
    def unit_roster_export(unit_id):
        with db() as conn:
            access(conn, unit_id)
            unit = access(conn, unit_id)
            catalog = json.loads(unit["catalog"])
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM unit_roster WHERE unit_id=? ORDER BY game_name COLLATE NOCASE",
                    (unit_id,),
                )
            ]
            decorate_slots(conn, unit_id, rows)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            (
                *FIELDS,
                "archived",
                "rank_abbreviation",
                "primary_billet",
                "primary_billet_path",
                "effective_callsign",
                "direct_formation_path",
                "next_rank",
                "next_eligible_date",
                "missing_qualifications",
            )
        )
        for row in rows:
            result = promotion(row, catalog)
            writer.writerow(
                [export_cell(row[f]) for f in (*FIELDS, "archived")]
                + [
                    export_cell(row["rank_abbreviation"]),
                    export_cell(row["billet_name"]),
                    export_cell(row["billet_path"]),
                    export_cell(row["effective_callsign"]),
                    export_cell(row["placement_path"]),
                    export_cell(result["next_rank"]),
                    result["next_date"],
                    export_cell(";".join(result["missing"])),
                ]
            )
        return api.Response(
            "\ufeff" + output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="unit-{unit_id}-roster.csv"'
            },
        )

    from unit_resources import install as install_resources
    from unit_events import install as install_events
    from roster_tools import install as install_roster_tools
    from unit_members import install as install_members
    from unit_sops import install as install_sops
    from unit_structure import (
        install as install_structure,
        initialize as initialize_structure,
    )
    from unit_login_management import install as install_login_management
    from unit_demo import install as install_demo
    from unit_collaboration import install as install_collaboration
    from unit_personnel import (
        install as install_personnel,
        initialize as initialize_personnel,
    )

    initialize_structure(db)
    initialize_personnel(db)
    # Register schemas and route dependencies before accepting requests.
    record_strength = install_resources(
        api, db, access, revision, panel_admin, endpoints
    )
    sync_event_roster = install_events(
        api, db, access, panel_admin, promotion, endpoints
    )
    roster_state, record_roster_change = install_roster_tools(
        api,
        db,
        access,
        revision,
        promotion,
        decorate_slots,
        assign_slot,
        structure_rows,
        endpoints,
        record_strength,
        sync_event_roster,
        assign_placement,
        member_revision,
    )
    required_reading = install_members(
        api, db, access, revision, panel_admin, endpoints
    )
    install_sops(api, db, access, revision, panel_admin, endpoints, required_reading)
    install_structure(
        api,
        db,
        access,
        revision,
        endpoints,
        structure_node,
        roster_state,
        record_roster_change,
    )
    install_login_management(
        api, db, access, revision, endpoints, find_member, panel_admin
    )
    install_demo(api, db, panel_admin, endpoints, record_roster_change, record_strength)
    personnel_coverage = install_personnel(
        api,
        db,
        access,
        revision,
        endpoints,
        find_member,
        structure_node,
        decorate_slots,
        roster_state,
        promotion,
        sync_event_roster,
    )
    collaboration_snapshot = install_collaboration(
        api, db, access, panel_admin, endpoints
    )


# Keep established imports available to integrations while sharing their definitions.
__all__ = [
    "install",
    "text",
    "UUID",
    "CAPABILITIES",
    "STAFF_CAPABILITIES",
    "unit_role_capabilities",
    "rank_structures_catalog",
    "FIELDS",
]
