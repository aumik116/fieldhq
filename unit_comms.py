"""Unit communications cards with independent optimistic versions."""

from datetime import date
import json
import time

from flask import abort, g, jsonify, request
from unit_common import actor, get_row, text, unit_role_capabilities


def install(api, db, access, panel_admin, endpoints):
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS unit_comms_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
            title TEXT NOT NULL, effective_on TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '', circuits TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1, updated_at REAL NOT NULL,
            updated_by TEXT NOT NULL)""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS unit_comms_unit ON unit_comms_cards(unit_id,id)"
        )
    names = {"unit_comms_list", "unit_comms_save", "unit_comms_delete"}
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS

    MUTATIONS.update(unit_comms_save="view", unit_comms_delete="view")

    def check_version(card, data):
        if type(data.get("version")) is not int or data["version"] != card["version"]:
            abort(
                409,
                description="This card was changed by another editor. Your draft is preserved; reopen the card before applying your changes.",
            )

    def changed(conn, unit_id, card_id, action):
        conn.execute("UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,))
        # Circuit data may contain game crypto; audit metadata only.
        g.audit_details = dict(unit_id=unit_id, card_id=card_id, change=action)

    @api.app.get("/api/units/<int:unit_id>/comms")
    def unit_comms_list(unit_id):
        with db() as conn:
            access(conn, unit_id)
            membership = conn.execute(
                "SELECT role FROM unit_staff WHERE unit_id=? AND user_id=?",
                (unit_id, g.user["id"]),
            ).fetchone()
            editable = panel_admin() or (
                membership
                and "references" in unit_role_capabilities(membership["role"])
            )
            cards = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM unit_comms_cards WHERE unit_id=? ORDER BY title COLLATE NOCASE,id",
                    (unit_id,),
                )
            ]
        for card in cards:
            card["circuits"] = json.loads(card["circuits"])
        return jsonify(cards=cards, can_edit=bool(editable))

    @api.app.post("/api/units/<int:unit_id>/comms")
    def unit_comms_save(unit_id):
        data = request.get_json()
        try:
            title = text(data.get("title", ""), "Card title", 120, True)
            notes = text(data.get("notes", ""), "Radio notes", 4000)
            effective = text(data.get("effective_on", ""), "Effective date", 10)
            if effective and date.fromisoformat(effective).isoformat() != effective:
                raise ValueError("Choose a valid effective date")
            rows = data.get("circuits", [])
            if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
                raise ValueError("Add between 1 and 200 circuits per card")
            circuits = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Choose valid circuit rows")
                circuits.append(
                    {
                        key: text(row.get(key, ""), label, limit, required)
                        for key, label, limit, required in (
                            ("name", "Circuit name", 120, True),
                            ("frequency", "Frequency", 40, True),
                            ("radio", "Radio type", 120, True),
                            ("group", "Group", 120, False),
                            ("crypto", "Crypto", 120, False),
                            ("password", "Password", 120, False),
                        )
                    }
                )
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "references")
                identity = data.get("id")
                if identity is not None:
                    card = get_row(conn, "unit_comms_cards", unit_id, identity)
                    check_version(card, data)
                    conn.execute(
                        "UPDATE unit_comms_cards SET title=?,effective_on=?,notes=?,circuits=?,version=version+1,updated_at=?,updated_by=? WHERE unit_id=? AND id=?",
                        (
                            title,
                            effective,
                            notes,
                            json.dumps(circuits),
                            time.time(),
                            actor(conn, unit_id),
                            unit_id,
                            identity,
                        ),
                    )
                else:
                    if (
                        conn.execute(
                            "SELECT count(*) FROM unit_comms_cards WHERE unit_id=?",
                            (unit_id,),
                        ).fetchone()[0]
                        >= 100
                    ):
                        raise ValueError(
                            "Keep at most 100 communications cards per unit"
                        )
                    identity = conn.execute(
                        "INSERT INTO unit_comms_cards(unit_id,title,effective_on,notes,circuits,updated_at,updated_by) VALUES(?,?,?,?,?,?,?)",
                        (
                            unit_id,
                            title,
                            effective,
                            notes,
                            json.dumps(circuits),
                            time.time(),
                            actor(conn, unit_id),
                        ),
                    ).lastrowid
                changed(conn, unit_id, identity, "communications card saved")
            return jsonify(ok=True, id=identity)
        except ValueError as error:
            return jsonify(ok=False, error=str(error)), 400

    @api.app.post("/api/units/<int:unit_id>/comms/<int:card_id>/delete")
    def unit_comms_delete(unit_id, card_id):
        if card_id > 9223372036854775807:
            abort(404, description="Communications card not found")
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            access(conn, unit_id, "references")
            card = get_row(conn, "unit_comms_cards", unit_id, card_id)
            check_version(card, request.get_json())
            conn.execute(
                "DELETE FROM unit_comms_cards WHERE unit_id=? AND id=?",
                (unit_id, card_id),
            )
            changed(conn, unit_id, card_id, "communications card deleted")
        return jsonify(ok=True)
