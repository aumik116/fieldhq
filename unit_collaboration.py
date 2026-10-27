"""Small unit snapshots and a paged roster feed for saved-change collaboration."""

from datetime import date
import hashlib
import json
import math
import time
import re
from flask import g, jsonify, request


def install(api, db, access, panel_admin, endpoints):
    with db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS unit_editors(unit_id INTEGER NOT NULL,user_id INTEGER NOT NULL,client TEXT NOT NULL,resource TEXT NOT NULL,expires REAL NOT NULL,PRIMARY KEY(unit_id,user_id,client))"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS unit_notes_sync ON unit_member_notes(unit_id,id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS unit_attendance_sync ON unit_attendance_audit(unit_id,id)"
        )
    names = {"unit_collab_state", "unit_roster_feed", "unit_editing"}
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS

    MUTATIONS["unit_editing"] = "view"

    @api.app.post("/api/units/<int:unit_id>/editing")
    def unit_editing(unit_id):
        data = request.get_json()
        client = data.get("client", "")
        resource = data.get("resource", "")
        if (
            not isinstance(client, str)
            or not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", client)
            or not isinstance(resource, str)
            or not 1 <= len(resource) <= 180
            or resource.split(":")[0]
            not in ("rank", "qualification", "member", "note", "branding")
            or type(data.get("active")) is not bool
        ):
            return jsonify(ok=False, error="Choose a valid editor"), 400
        with db() as conn:
            access(
                conn,
                unit_id,
                (
                    "staff"
                    if resource.split(":")[0] in ("rank", "qualification", "branding")
                    else "roster"
                ),
            )
            conn.execute("DELETE FROM unit_editors WHERE expires<?", (time.time(),))
            conn.execute(
                "DELETE FROM unit_editors WHERE unit_id=? AND user_id=? AND client=? AND (? OR resource=?)",
                (unit_id, g.user["id"], client, data["active"], resource),
            )
            if data["active"]:
                conn.execute(
                    "INSERT INTO unit_editors VALUES(?,?,?,?,?)",
                    (unit_id, g.user["id"], client, resource, time.time() + 45),
                )
            editors = []
            for row in conn.execute(
                "SELECT DISTINCT e.user_id,u.username FROM unit_editors e JOIN users u ON u.id=e.user_id WHERE e.unit_id=? AND e.resource=? AND u.enabled=1 AND NOT(e.user_id=? AND e.client=?) AND NOT EXISTS(SELECT 1 FROM unit_account_suspensions s WHERE s.unit_id=e.unit_id AND s.user_id=e.user_id)",
                (unit_id, resource, g.user["id"], client),
            ):
                name = conn.execute(
                    "SELECT game_name FROM unit_roster WHERE unit_id=? AND panel_user_id=?",
                    (unit_id, row["user_id"]),
                ).fetchone()
                editors.append(name["game_name"] if name else row["username"])
        return jsonify(ok=True, editors=editors)

    def snapshot(conn, unit_id):
        unit = access(conn, unit_id)
        membership = conn.execute(
            "SELECT role FROM unit_staff WHERE unit_id=? AND user_id=?",
            (unit_id, g.user["id"]),
        ).fetchone()
        staff = panel_admin() or membership["role"] in ("staff", "admin")
        note = (
            conn.execute(
                "SELECT coalesce(max(id),0) FROM unit_member_notes WHERE unit_id=?",
                (unit_id,),
            ).fetchone()[0]
            if staff
            else 0
        )
        events = conn.execute(
            "SELECT count(*),coalesce(max(id),0),coalesce(sum(version),0) FROM unit_events WHERE unit_id=?",
            (unit_id,),
        ).fetchone()
        changes = (
            conn.execute(
                "SELECT coalesce(max(id),0) FROM unit_attendance_audit WHERE unit_id=?",
                (unit_id,),
            ).fetchone()[0]
            if staff
            else 0
        )
        token = hashlib.sha256(
            f"{date.today().isoformat()}:{unit['revision']}:{note}:{tuple(events)}:{changes}".encode()
        ).hexdigest()
        return dict(token=token, revision=unit["revision"], staff=staff)

    @api.app.get("/api/units/<int:unit_id>/sync")
    def unit_collab_state(unit_id):
        with db() as conn:
            conn.execute("BEGIN")
            result = snapshot(conn, unit_id)
            result["editing"] = []
            if result["staff"]:
                for row in conn.execute(
                    "SELECT DISTINCT e.resource,COALESCE(r.game_name,u.username) AS name FROM unit_editors e JOIN users u ON u.id=e.user_id LEFT JOIN unit_roster r ON r.unit_id=e.unit_id AND r.panel_user_id=e.user_id WHERE e.unit_id=? AND e.expires>? AND u.enabled=1 AND (u.panel_admin=1 OR EXISTS(SELECT 1 FROM panel_owner p WHERE p.user_id=u.id) OR EXISTS(SELECT 1 FROM unit_staff s WHERE s.unit_id=e.unit_id AND s.user_id=u.id AND s.role!='member')) AND NOT EXISTS(SELECT 1 FROM unit_account_suspensions s WHERE s.unit_id=e.unit_id AND s.user_id=u.id)",
                    (unit_id, time.time()),
                ):
                    result["editing"].append(dict(row))
            latest = (
                conn.execute(
                    "SELECT actor,action,ts,details FROM activity WHERE outcome='success' AND json_extract(details,'$.unit_id')=? AND action NOT LIKE '%preview%' AND coalesce(json_extract(details,'$.change'),'') NOT LIKE '%preview%' ORDER BY id DESC LIMIT 1",
                    (unit_id,),
                ).fetchone()
                if result["staff"]
                else None
            )
            result["actor"] = latest["actor"] if latest else None
            result["member_id"] = (
                json.loads(latest["details"]).get("member_id") if latest else None
            )
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response

    @api.app.get("/api/units/<int:unit_id>/roster/feed")
    def unit_roster_feed(unit_id):
        try:
            before = float(request.args.get("before", "1e30"))
            key = request.args.get("key", "~")
            if not math.isfinite(before) or before < 0 or len(key) > 100:
                raise ValueError("Choose a valid feed cursor")
            with db() as conn:
                conn.execute("BEGIN")
                access(conn, unit_id, "roster")
                entries = []
                for row in conn.execute(
                    "SELECT h.*,r.game_name FROM unit_roster_history h LEFT JOIN unit_roster r ON r.id=h.member_id AND r.unit_id=h.unit_id WHERE h.unit_id=? AND h.kind NOT IN ('baseline') AND (h.created_at<? OR (h.created_at=? AND 'history:'||h.id<?)) ORDER BY h.created_at DESC,('history:'||h.id) DESC LIMIT 51",
                    (unit_id, before, before, key),
                ):
                    entries.append(
                        dict(
                            key="history:" + str(row["id"]),
                            when=row["created_at"],
                            actor=row["actor"],
                            kind=row["kind"],
                            member_id=row["member_id"] if row["game_name"] else None,
                            name=row["game_name"] or "Former/deleted member",
                            reason=row["reason"],
                            before=json.loads(row["before_value"]),
                            after=json.loads(row["after_value"]),
                        )
                    )
                for row in conn.execute(
                    "SELECT n.*,r.game_name FROM unit_member_notes n JOIN unit_roster r ON r.id=n.member_id AND r.unit_id=n.unit_id WHERE n.unit_id=? AND (n.created_at<? OR (n.created_at=? AND 'note:'||n.id<?)) ORDER BY n.created_at DESC,('note:'||n.id) DESC LIMIT 51",
                    (unit_id, before, before, key),
                ):
                    entries.append(
                        dict(
                            key="note:" + str(row["id"]),
                            when=row["created_at"],
                            actor=row["author_name"],
                            kind="note",
                            member_id=row["member_id"],
                            name=row["game_name"],
                            reason=row["note"][:240],
                            before=None,
                            after=None,
                        )
                    )
                for row in conn.execute(
                    "SELECT id,ts,actor,action,details FROM activity WHERE outcome='success' AND json_extract(details,'$.unit_id')=? AND action IN ('unit_structure_save','unit_structure_delete','unit_structure_copy','unit_structure_billets','unit_structure_order','unit_catalog_save','unit_billet_types_save','unit_qualification_delete','unit_formation_template_save','unit_formation_template_apply','unit_formation_template_delete','unit_roster_delete','unit_member_note_delete','unit_member_note_edit','unit_member_login_create','unit_member_login_manage','unit_staff_save','unit_followup_save') AND coalesce(json_extract(details,'$.change'),'') NOT LIKE '%preview%' AND (ts<? OR (ts=? AND 'activity:'||id<?)) ORDER BY ts DESC,('activity:'||id) DESC LIMIT 51",
                    (unit_id, before, before, key),
                ):
                    data = json.loads(row["details"])
                    entries.append(
                        dict(
                            key="activity:" + str(row["id"]),
                            when=row["ts"],
                            actor=row["actor"],
                            kind=row["action"],
                            member_id=None,
                            name=data.get("name")
                            or data.get("game_name")
                            or data.get("username")
                            or data.get("qualification")
                            or data.get("change")
                            or "Unit setup",
                            reason=data.get("change", ""),
                            before=None,
                            after=None,
                        )
                    )
            entries.sort(key=lambda entry: (entry["when"], entry["key"]), reverse=True)
            shown = entries[:50]
            return jsonify(
                entries=shown,
                next_cursor=(
                    dict(before=shown[-1]["when"], key=shown[-1]["key"])
                    if len(entries) > 50
                    else None
                ),
            )
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    return snapshot
