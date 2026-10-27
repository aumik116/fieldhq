"""Staff personnel tools: coverage, vacancies, follow-ups, comparisons and unit archives."""

from datetime import date, datetime, timedelta, timezone
import csv
import io
import json
import re
import time
import zipfile
from flask import g, jsonify, request, send_file
from unit_common import actor, audit, number, text


def initialize(db):
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS unit_temporary_assignments(id INTEGER PRIMARY KEY AUTOINCREMENT,unit_id INTEGER NOT NULL,member_id INTEGER NOT NULL,billet_id INTEGER NOT NULL,starts_on TEXT NOT NULL,ends_on TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',cancelled INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS unit_temporary_unit ON unit_temporary_assignments(unit_id,billet_id,starts_on);
        CREATE TABLE IF NOT EXISTS unit_followups(id INTEGER PRIMARY KEY AUTOINCREMENT,unit_id INTEGER NOT NULL,member_id INTEGER,title TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',due_on TEXT NOT NULL DEFAULT '',completed INTEGER NOT NULL DEFAULT 0,author TEXT NOT NULL,updated_at REAL NOT NULL);
        """)


def install(
    api,
    db,
    access,
    revision,
    endpoints,
    find_member,
    structure_node,
    decorate,
    roster_state,
    promotion,
    sync_roster,
):
    names = {
        "unit_personnel",
        "unit_temporary_save",
        "unit_temporary_cancel",
        "unit_followup_save",
        "unit_member_compare",
        "unit_backup",
    }
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS

    MUTATIONS.update(
        {
            name: "view"
            for name in (
                "unit_temporary_save",
                "unit_temporary_cancel",
                "unit_followup_save",
            )
        }
    )

    def day(value, label, optional=False):
        if optional and not value:
            return ""
        try:
            return date.fromisoformat(value).isoformat()
        except (ValueError, TypeError):
            raise ValueError(f"{label}: choose a valid date") from None

    def coverage(conn, unit_id, current=True):
        today = date.today().isoformat()
        return [
            dict(row)
            for row in conn.execute(
                "SELECT a.*,r.game_name,s.name AS billet_name FROM unit_temporary_assignments a JOIN unit_roster r ON r.id=a.member_id AND r.unit_id=a.unit_id JOIN unit_structure s ON s.id=a.billet_id AND s.unit_id=a.unit_id WHERE a.unit_id=? AND a.cancelled=0 AND r.archived=0 AND (a.ends_on='' OR a.ends_on>=?) AND (?=0 OR a.starts_on<=?) ORDER BY a.starts_on,a.id",
                (unit_id, today, int(current), today),
            )
        ]

    @api.app.get("/api/units/<int:unit_id>/personnel")
    def unit_personnel(unit_id):
        with db() as conn:
            conn.execute("BEGIN")
            unit = access(conn, unit_id, "roster")
            catalog = json.loads(unit["catalog"])
            members = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM unit_roster WHERE unit_id=? ORDER BY game_name",
                    (unit_id,),
                )
            ]
            decorate(conn, unit_id, members)
            nodes = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM unit_structure WHERE unit_id=? ORDER BY sort_order,id",
                    (unit_id,),
                )
            ]
            node_map = {node["id"]: node for node in nodes}

            def path(node):
                names = []
                while node:
                    names.insert(0, node["name"])
                    node = node_map.get(node["parent_id"])
                return " / ".join(names)

            temporary = coverage(conn, unit_id, False)
            for item in temporary:
                item["path"] = path(node_map[item["billet_id"]])
                item["active"] = item["starts_on"] <= date.today().isoformat()
            filled = {
                row[0]
                for row in conn.execute(
                    "SELECT billet_id FROM unit_primary_slots WHERE unit_id=?",
                    (unit_id,),
                )
            }
            vacancies = [
                dict(
                    id=node["id"],
                    name=node["name"],
                    path=path(node),
                    formation_id=node["parent_id"],
                    cover=[
                        item["game_name"]
                        for item in temporary
                        if item["billet_id"] == node["id"] and item["active"]
                    ],
                )
                for node in nodes
                if node["kind"] == "billet" and node["id"] not in filled
            ]
            horizon = (date.today() + timedelta(days=30)).isoformat()
            renewals = [
                dict(row)
                for row in conn.execute(
                    "SELECT q.member_id,r.game_name,q.certificate,q.awarded_on,q.expires_on FROM unit_qualification_awards q JOIN unit_roster r ON r.id=q.member_id AND r.unit_id=q.unit_id WHERE q.unit_id=? AND r.archived=0 AND q.expires_on!='' AND q.expires_on<=? ORDER BY q.expires_on,r.game_name",
                    (unit_id, horizon),
                )
                if any(
                    entry["name"] == row["certificate"]
                    and entry.get("renewal_required")
                    for entry in catalog.get("qualification_details", [])
                )
            ]
            eligible = [
                dict(
                    id=member["id"],
                    name=member["game_name"],
                    **promotion(member, catalog),
                )
                for member in members
                if not member["archived"] and promotion(member, catalog)["eligible"]
            ]
            followups = [
                dict(row)
                for row in conn.execute(
                    "SELECT f.*,r.game_name FROM unit_followups f LEFT JOIN unit_roster r ON r.id=f.member_id AND r.unit_id=f.unit_id WHERE f.unit_id=? ORDER BY f.completed,(f.due_on=''),f.due_on,f.id DESC LIMIT 300",
                    (unit_id,),
                )
            ]
        return jsonify(
            today=date.today().isoformat(),
            revision=unit["revision"],
            vacancies=vacancies,
            temporary=temporary,
            renewals=renewals,
            eligible=eligible,
            followups=followups,
        )

    @api.app.post("/api/units/<int:unit_id>/temporary-assignments")
    def unit_temporary_save(unit_id):
        try:
            data = request.get_json()
            member_id = number(data.get("member_id"), "Member", 1, 9223372036854775807)
            billet_id = number(data.get("billet_id"), "Billet", 1, 9223372036854775807)
            starts = day(data.get("starts_on"), "Start date")
            ends = day(data.get("ends_on"), "End date", True)
            notes = text(data.get("notes", ""), "Coverage notes", 1000)
            if ends and ends < starts:
                raise ValueError("End date must not precede the start")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "roster")
                revision(conn, unit_id, data)
                member = find_member(conn, unit_id, member_id)
                structure_node(conn, unit_id, billet_id, "billet")
                if conn.execute(
                    "SELECT 1 FROM unit_primary_slots WHERE unit_id=? AND member_id=? AND billet_id=?",
                    (unit_id, member_id, billet_id),
                ).fetchone():
                    raise ValueError("This is already the member’s primary billet")
                if member["archived"]:
                    raise ValueError(
                        "Restore this member before assigning temporary cover"
                    )
                if conn.execute(
                    "SELECT 1 FROM unit_temporary_assignments WHERE unit_id=? AND cancelled=0 AND (member_id=? OR billet_id=?) AND starts_on<=? AND (ends_on='' OR ends_on>=?)",
                    (unit_id, member_id, billet_id, ends or "9999-12-31", starts),
                ).fetchone():
                    raise ValueError(
                        "The member or billet already has overlapping temporary cover"
                    )
                identity = conn.execute(
                    "INSERT INTO unit_temporary_assignments(unit_id,member_id,billet_id,starts_on,ends_on,notes) VALUES(?,?,?,?,?,?)",
                    (unit_id, member_id, billet_id, starts, ends, notes),
                ).lastrowid
                after = dict(
                    id=identity,
                    billet_id=billet_id,
                    starts_on=starts,
                    ends_on=ends,
                    notes=notes,
                )
                conn.execute(
                    "INSERT INTO unit_roster_history(unit_id,member_id,kind,actor,created_at,before_value,after_value,reason) VALUES(?,?,'temporary',?,?,'null',?,?)",
                    (
                        unit_id,
                        member_id,
                        actor(conn, unit_id),
                        time.time(),
                        json.dumps(after),
                        "Temporary cover assigned; primary placement unchanged",
                    ),
                )
                audit(
                    conn,
                    unit_id,
                    "temporary",
                    identity,
                    "created",
                    None,
                    after,
                    member_id=member_id,
                )
                sync_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                member_id=member_id,
                billet_id=billet_id,
                change="temporary cover assigned",
            )
            return jsonify(ok=True, id=identity)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post(
        "/api/units/<int:unit_id>/temporary-assignments/<int:assignment_id>/cancel"
    )
    def unit_temporary_cancel(unit_id, assignment_id):
        try:
            number(assignment_id, "Assignment", 1, 9223372036854775807)
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "roster")
                revision(conn, unit_id, request.get_json())
                previous = conn.execute(
                    "SELECT * FROM unit_temporary_assignments WHERE unit_id=? AND id=?",
                    (unit_id, assignment_id),
                ).fetchone()
                if not previous or previous["cancelled"]:
                    raise ValueError(
                        "Temporary assignment not found or already cancelled"
                    )
                conn.execute(
                    "UPDATE unit_temporary_assignments SET cancelled=1 WHERE unit_id=? AND id=?",
                    (unit_id, assignment_id),
                )
                conn.execute(
                    "INSERT INTO unit_roster_history(unit_id,member_id,kind,actor,created_at,before_value,after_value,reason) VALUES(?,?,'temporary',?,?,?,'null',?)",
                    (
                        unit_id,
                        previous["member_id"],
                        actor(conn, unit_id),
                        time.time(),
                        json.dumps(dict(previous)),
                        "Temporary cover cancelled",
                    ),
                )
                audit(
                    conn,
                    unit_id,
                    "temporary",
                    assignment_id,
                    "cancelled",
                    dict(previous),
                    None,
                    member_id=previous["member_id"],
                )
                sync_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                member_id=previous["member_id"],
                change="temporary cover cancelled",
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/followups")
    def unit_followup_save(unit_id):
        try:
            data = request.get_json()
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "roster")
                revision(conn, unit_id, data)
                identity = data.get("id")
                if identity is not None:
                    old = conn.execute(
                        "SELECT * FROM unit_followups WHERE unit_id=? AND id=?",
                        (unit_id, identity),
                    ).fetchone()
                    if not old:
                        raise ValueError("Follow-up not found")
                    if type(data.get("completed")) is not bool:
                        raise ValueError("Choose a completion state")
                    member_id = data.get("member_id", old["member_id"])
                    if member_id is not None:
                        find_member(
                            conn,
                            unit_id,
                            number(member_id, "Member", 1, 9223372036854775807),
                        )
                    title = text(
                        data.get("title", old["title"]), "Follow-up title", 120, True
                    )
                    notes = text(data.get("notes", old["notes"]), "Notes", 2000)
                    due = day(data.get("due_on", old["due_on"]), "Due date", True)
                    conn.execute(
                        "UPDATE unit_followups SET title=?,notes=?,due_on=?,member_id=?,completed=?,updated_at=? WHERE unit_id=? AND id=?",
                        (
                            title,
                            notes,
                            due,
                            member_id,
                            int(data["completed"]),
                            time.time(),
                            unit_id,
                            identity,
                        ),
                    )
                    audit(
                        conn,
                        unit_id,
                        "followup",
                        identity,
                        "completed" if data["completed"] else "reopened",
                        dict(old),
                        dict(
                            title=title,
                            notes=notes,
                            due_on=due,
                            member_id=member_id,
                            completed=data["completed"],
                        ),
                    )
                else:
                    if (
                        conn.execute(
                            "SELECT count(*) FROM unit_followups WHERE unit_id=? AND completed=0",
                            (unit_id,),
                        ).fetchone()[0]
                        >= 250
                    ):
                        raise ValueError(
                            "Complete existing follow-ups before adding more"
                        )
                    member_id = data.get("member_id")
                    member = (
                        find_member(
                            conn,
                            unit_id,
                            number(member_id, "Member", 1, 9223372036854775807),
                        )
                        if member_id is not None
                        else None
                    )
                    title = text(data.get("title"), "Follow-up title", 120, True)
                    notes = text(data.get("notes", ""), "Notes", 2000)
                    due = day(data.get("due_on"), "Due date", True)
                    identity = conn.execute(
                        "INSERT INTO unit_followups(unit_id,member_id,title,notes,due_on,author,updated_at) VALUES(?,?,?,?,?,?,?)",
                        (
                            unit_id,
                            member["id"] if member else None,
                            title,
                            notes,
                            due,
                            actor(conn, unit_id),
                            time.time(),
                        ),
                    ).lastrowid
                    audit(
                        conn,
                        unit_id,
                        "followup",
                        identity,
                        "created",
                        None,
                        dict(title=title, notes=notes, due_on=due),
                    )
            g.audit_details = dict(
                unit_id=unit_id, change="follow-up saved", followup_id=identity
            )
            return jsonify(ok=True, id=identity)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.get("/api/units/<int:unit_id>/roster/<int:member_id>/compare")
    def unit_member_compare(unit_id, member_id):
        try:
            with db() as conn:
                conn.execute("BEGIN")
                access(conn, unit_id, "roster")
                find_member(conn, unit_id, member_id)
                history = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM unit_roster_history WHERE unit_id=? AND member_id=? ORDER BY id",
                        (unit_id, member_id),
                    )
                ]
                versions = [
                    dict(
                        id=row["id"],
                        kind=row["kind"],
                        actor=row["actor"],
                        when=row["created_at"],
                    )
                    for row in reversed(history[-100:])
                ]

                def reconstruct(raw):
                    if raw == "current":
                        result = roster_state(conn, unit_id, member_id)
                        result["qualification_records"] = {
                            row["certificate"]: dict(row)
                            for row in conn.execute(
                                "SELECT certificate,awarded_on,expires_on,issuer,notes FROM unit_qualification_awards WHERE unit_id=? AND member_id=?",
                                (unit_id, member_id),
                            )
                        }
                        result["temporary_assignments"] = {
                            str(row["id"]): dict(row)
                            for row in conn.execute(
                                "SELECT id,billet_id,starts_on,ends_on,notes FROM unit_temporary_assignments WHERE unit_id=? AND member_id=? AND cancelled=0",
                                (unit_id, member_id),
                            )
                        }
                        return result
                    key = number(int(raw), "Version", 1, 9223372036854775807)
                    if not any(row["id"] == key for row in history):
                        raise ValueError("Choose versions from this member record")
                    result = {}
                    awards = {}
                    for row in history:
                        if row["id"] > key:
                            break
                        before = json.loads(row["before_value"])
                        after = json.loads(row["after_value"])
                        kind = row["kind"]
                        if kind in ("baseline", "created") and after:
                            result.update(after)
                            awards = {
                                name: dict(
                                    certificate=name,
                                    awarded_on=None,
                                    expires_on="",
                                    issuer=None,
                                    notes="Original details not recorded",
                                )
                                for name in after.get("certificates", "").split(";")
                                if name
                            }
                        elif kind.startswith("qualification_"):
                            entry = after or before or {}
                            name = entry.get("certificate")
                            if name:
                                if kind == "qualification_revoked":
                                    awards.pop(name, None)
                                else:
                                    awards[name] = {
                                        key: entry.get(key)
                                        for key in (
                                            "certificate",
                                            "awarded_on",
                                            "expires_on",
                                            "issuer",
                                            "notes",
                                        )
                                    }
                            result["certificates"] = ";".join(sorted(awards))
                        elif (
                            kind in ("rank", "billet", "status", "callsign", "profile")
                            and after
                        ):
                            result.update(after)
                        elif kind == "temporary":
                            temporary = result.setdefault("temporary_assignments", {})
                            if after:
                                temporary[str(after["id"])] = {
                                    key: after.get(key)
                                    for key in (
                                        "id",
                                        "billet_id",
                                        "starts_on",
                                        "ends_on",
                                        "notes",
                                    )
                                }
                            elif before:
                                temporary.pop(str(before["id"]), None)
                    result["qualification_records"] = awards
                    return result

                left_raw = request.args.get(
                    "from",
                    (
                        str(history[-2]["id"])
                        if len(history) > 1
                        else str(history[0]["id"]) if history else "current"
                    ),
                )
                right_raw = request.args.get("to", "current")
                before = reconstruct(left_raw)
                after = reconstruct(right_raw)
                fields = sorted(set(before) | set(after))
                changes = [
                    dict(
                        field=field,
                        before=before.get(field),
                        after=after.get(field),
                        before_known=field in before,
                        after_known=field in after,
                        changed=before.get(field) != after.get(field)
                        or (field in before) != (field in after),
                    )
                    for field in fields
                ]
            return jsonify(
                versions=versions,
                from_version=left_raw,
                to_version=right_raw,
                fields=changes,
            )
        except (ValueError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.get("/api/units/<int:unit_id>/backup")
    def unit_backup(unit_id):
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            unit = access(conn, unit_id, "staff")
            tables = {}
            schemas = []
            files = {}
            for item in conn.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall():
                table = item["name"]
                quoted = '"' + table.replace('"', '""') + '"'
                columns = {
                    row["name"] for row in conn.execute(f"PRAGMA table_info({quoted})")
                }
                if table == "units":
                    rows = conn.execute(
                        "SELECT * FROM units WHERE id=?", (unit_id,)
                    ).fetchall()
                elif "unit_id" in columns:
                    rows = conn.execute(
                        f"SELECT * FROM {quoted} WHERE unit_id=?", (unit_id,)
                    ).fetchall()
                elif table in (
                    "unit_event_members",
                    "unit_event_evidence",
                    "unit_event_samples",
                ):
                    rows = conn.execute(
                        f"SELECT * FROM {quoted} WHERE event_id IN (SELECT id FROM unit_events WHERE unit_id=?)",
                        (unit_id,),
                    ).fetchall()
                else:
                    continue
                serialized = []
                for index, row in enumerate(rows):
                    record = dict(row)
                    for column, value in record.items():
                        if isinstance(value, bytes):
                            suffix = (
                                re.sub(
                                    r"[^A-Za-z0-9.]",
                                    "",
                                    str(record.get("filename", "")).rsplit(".", 1)[-1],
                                )[:12]
                                if "." in str(record.get("filename", ""))
                                else "bin"
                            )
                            path = f"attachments/{table}-{index}-{column}.{suffix}"
                            files[path] = value
                            record[column] = dict(archive_file=path)
                    serialized.append(record)
                tables[table] = serialized
                schemas.append(item["sql"] + ";")
            accounts = [
                dict(row)
                for row in conn.execute(
                    "SELECT DISTINCT id,username FROM users WHERE id IN (SELECT user_id FROM unit_staff WHERE unit_id=? UNION SELECT panel_user_id FROM unit_roster WHERE unit_id=?)",
                    (unit_id, unit_id),
                )
            ]
            members = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM unit_roster WHERE unit_id=?", (unit_id,)
                )
            ]
            decorate(conn, unit_id, members)
            audit(
                conn,
                unit_id,
                "unit",
                unit_id,
                "backup_exported",
                None,
                dict(members=len(members)),
            )
        output = io.BytesIO()
        sheet = io.StringIO()
        writer = csv.writer(sheet)
        writer.writerow(
            [
                "Game name",
                "Rank",
                "Callsign",
                "Placement",
                "Qualifications",
                "UUID",
                "Status",
            ]
        )
        for member in members:
            cells = [
                member["game_name"],
                member["rank"],
                member["effective_callsign"],
                member["assignment_path"],
                member["certificates"],
                member["identity"],
                member["status"],
            ]
            writer.writerow(
                [
                    (
                        "'" + value
                        if value.lstrip().startswith(("=", "+", "-", "@"))
                        else value
                    )
                    for value in cells
                ]
            )
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "unit.json",
                json.dumps(
                    dict(
                        format="FIELDHQ unit archive",
                        version=1,
                        exported_at=datetime.now(timezone.utc).isoformat(),
                        unit_id=unit_id,
                        account_links=accounts,
                        tables=tables,
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            archive.writestr("schema.sql", "\n".join(schemas))
            archive.writestr(
                "catalog.json",
                json.dumps(json.loads(unit["catalog"]), ensure_ascii=False, indent=2),
            )
            archive.writestr("roster.csv", "\ufeff" + sheet.getvalue())
            archive.writestr(
                "README.txt",
                "FIELDHQ unit archive. Contains private roster records, staff notes, history, SOPs/loadouts, attachments, branding and event data. No login passwords or server binaries are included. Account IDs and server links must be mapped when restoring to a different installation. This archive is for manual recovery; it is not a server installer. Binary columns refer to files inside attachments/.\n",
            )
            for name, value in files.items():
                archive.writestr(name, value)
        output.seek(0)
        response = send_file(
            output,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"unit-{unit_id}-backup.zip",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    return coverage
