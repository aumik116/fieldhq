"""Small unit snapshots and a paged roster feed for saved-change collaboration."""

from datetime import date
import hashlib
import json
import math
from flask import g, jsonify, request


def install(api, db, access, panel_admin, endpoints):
    with db() as conn:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS unit_notes_sync ON unit_member_notes(unit_id,id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS unit_attendance_sync ON unit_attendance_audit(unit_id,id)"
        )
    names = {"unit_collab_state", "unit_roster_feed"}
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)

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
