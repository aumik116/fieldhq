"""Batch billet creation and empty structure copies, scoped to unit administrators."""

import json
import sqlite3
from flask import g, jsonify, request
from unit_common import number, text


def initialize(db):
    with db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS unit_billet_types(id INTEGER PRIMARY KEY AUTOINCREMENT,unit_id INTEGER NOT NULL,name TEXT NOT NULL COLLATE NOCASE,UNIQUE(unit_id,name))"
        )
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(unit_structure)")}
        if "billet_type_id" not in columns:
            conn.execute("ALTER TABLE unit_structure ADD COLUMN billet_type_id INTEGER")
            conn.execute(
                "ALTER TABLE unit_structure ADD COLUMN callsign TEXT NOT NULL DEFAULT ''"
            )
            conn.execute(
                "INSERT OR IGNORE INTO unit_billet_types(unit_id,name) SELECT unit_id,name FROM unit_structure WHERE kind='billet'"
            )
            for unit in conn.execute("SELECT id,catalog FROM units").fetchall():
                for title in json.loads(unit["catalog"]).get("positions", []):
                    if title and len(title) <= 80:
                        conn.execute(
                            "INSERT OR IGNORE INTO unit_billet_types(unit_id,name) VALUES(?,?)",
                            (unit["id"], title),
                        )
            conn.execute(
                "UPDATE unit_structure SET billet_type_id=(SELECT t.id FROM unit_billet_types t WHERE t.unit_id=unit_structure.unit_id AND t.name=unit_structure.name) WHERE kind='billet'"
            )


def install(
    api, db, access, revision, endpoints, structure_node, roster_state, record_change
):
    names = {"unit_structure_copy", "unit_structure_billets", "unit_billet_types_save"}
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS

    MUTATIONS.update({name: "view" for name in names})

    def next_order(conn, unit_id, parent):
        return conn.execute(
            "SELECT coalesce(max(sort_order),-1)+1 FROM unit_structure WHERE unit_id=? AND parent_id IS ?",
            (unit_id, parent),
        ).fetchone()[0]

    def capacity(conn, unit_id, amount):
        if (
            conn.execute(
                "SELECT count(*) FROM unit_structure WHERE unit_id=?", (unit_id,)
            ).fetchone()[0]
            + amount
            > 2000
        ):
            raise ValueError("Keep at most 2000 structure items per unit")

    @api.app.post("/api/units/<int:unit_id>/structure/<int:node_id>/billets")
    def unit_structure_billets(unit_id, node_id):
        try:
            data = request.get_json()
            entries = data.get("entries")
            if not isinstance(entries, list) or not 1 <= len(entries) <= 50:
                raise ValueError("Enter 1–50 billet names")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                revision(conn, unit_id, data)
                names = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("Choose valid billet entries")
                    type_id = number(
                        entry.get("billet_type_id"),
                        "Billet type",
                        1,
                        9223372036854775807,
                    )
                    definition = conn.execute(
                        "SELECT name FROM unit_billet_types WHERE unit_id=? AND id=?",
                        (unit_id, type_id),
                    ).fetchone()
                    if not definition:
                        raise ValueError("Choose a saved billet type from this unit")
                    count = number(entry.get("count", 1), "Copies", 1, 50)
                    callsign = text(entry.get("callsign", ""), "Billet callsign", 60)
                    names.extend([(definition["name"], type_id, callsign)] * count)
                if len(names) > 100:
                    raise ValueError("Add at most 100 billets per save")
                target = structure_node(conn, unit_id, node_id)
                if target["kind"] == "billet":
                    raise ValueError("Add billets inside a formation")
                ancestor = target
                depth = 0
                while ancestor is not None:
                    depth += 1
                    ancestor = (
                        structure_node(conn, unit_id, ancestor["parent_id"])
                        if ancestor["parent_id"] is not None
                        else None
                    )
                if depth > 6:
                    raise ValueError("Use at most six levels below a group")
                capacity(conn, unit_id, len(names))
                order = next_order(conn, unit_id, node_id)
                ids = []
                for offset, (name, type_id, callsign) in enumerate(names):
                    ids.append(
                        conn.execute(
                            "INSERT INTO unit_structure(unit_id,parent_id,kind,name,sort_order,billet_type_id,callsign) VALUES(?,?,'billet',?,?,?,?)",
                            (unit_id, node_id, name, order + offset, type_id, callsign),
                        ).lastrowid
                    )
            g.audit_details = dict(
                unit_id=unit_id,
                section_id=node_id,
                created_billets=ids,
                change="billets added",
            )
            return jsonify(ok=True, ids=ids)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/structure/<int:node_id>/copy")
    def unit_structure_copy(unit_id, node_id):
        try:
            data = request.get_json()
            name = text(data.get("name"), "Name for copy", 80, True)
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                revision(conn, unit_id, data)
                source = structure_node(conn, unit_id, node_id)
                parent = data.get("parent_id", source["parent_id"])
                ancestors = []
                if source["kind"] == "group":
                    if parent is not None:
                        raise ValueError("Groups must stay at the top level")
                else:
                    target = structure_node(conn, unit_id, parent)
                    allowed = ("group", "section")
                    if target["kind"] not in allowed:
                        raise ValueError(
                            "Choose a valid destination for this structure type"
                        )
                    while target is not None:
                        ancestors.append(target["id"])
                        target = (
                            structure_node(conn, unit_id, target["parent_id"])
                            if target["parent_id"] is not None
                            else None
                        )
                nodes = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM unit_structure WHERE unit_id=? ORDER BY sort_order,id",
                        (unit_id,),
                    )
                ]
                children = {}
                for node in nodes:
                    children.setdefault(node["parent_id"], []).append(node)
                tree = []

                def collect(node, depth):
                    if len(ancestors) + depth > 6:
                        raise ValueError("Use at most six levels below a group")
                    tree.append(node)
                    for child in children.get(node["id"], []):
                        collect(child, depth + 1)

                collect(dict(source), 0)
                capacity(conn, unit_id, len(tree))
                copied = {}
                for node in tree:
                    destination = (
                        parent if node["id"] == node_id else copied[node["parent_id"]]
                    )
                    copied[node["id"]] = conn.execute(
                        "INSERT INTO unit_structure(unit_id,parent_id,kind,name,sort_order,billet_type_id) VALUES(?,?,?,?,?,?)",
                        (
                            unit_id,
                            destination,
                            node["kind"],
                            name if node["id"] == node_id else node["name"],
                            next_order(conn, unit_id, destination),
                            node["billet_type_id"],
                        ),
                    ).lastrowid
            g.audit_details = dict(
                unit_id=unit_id,
                source_structure=node_id,
                copied_structure=copied[node_id],
                created=len(copied),
                change="empty structure copied",
            )
            return jsonify(ok=True, id=copied[node_id], created=len(copied))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/billet-types")
    def unit_billet_types_save(unit_id):
        try:
            data = request.get_json()
            entries = data.get("entries")
            if not isinstance(entries, list) or len(entries) > 200:
                raise ValueError("Use up to 200 billet types")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                revision(conn, unit_id, data)
                original = {
                    row["id"]: row["name"]
                    for row in conn.execute(
                        "SELECT * FROM unit_billet_types WHERE unit_id=?", (unit_id,)
                    )
                }
                before = {
                    row[0]: roster_state(conn, unit_id, row[0])
                    for row in conn.execute(
                        "SELECT member_id FROM unit_primary_slots WHERE unit_id=?",
                        (unit_id,),
                    )
                }
                parsed = []
                seen = set()
                ids = set()
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("Choose valid billet types")
                    name = text(entry.get("name"), "Billet title", 80, True)
                    key = entry.get("id")
                    if name.casefold() in seen:
                        raise ValueError("Billet titles must be unique")
                    if key is not None and (
                        type(key) is not int or key not in original or key in ids
                    ):
                        raise ValueError("Choose existing billet types from this unit")
                    seen.add(name.casefold())
                    ids.add(key)
                    parsed.append((key, name))
                # Rebuild catalog rows with stable IDs, allowing titles to exchange names.
                conn.execute(
                    "DELETE FROM unit_billet_types WHERE unit_id=?", (unit_id,)
                )
                for key, name in parsed:
                    if key is None:
                        key = conn.execute(
                            "INSERT INTO unit_billet_types(unit_id,name) VALUES(?,?)",
                            (unit_id, name),
                        ).lastrowid
                    else:
                        conn.execute(
                            "INSERT INTO unit_billet_types(id,unit_id,name) VALUES(?,?,?)",
                            (key, unit_id, name),
                        )
                    conn.execute(
                        "UPDATE unit_structure SET name=? WHERE unit_id=? AND billet_type_id=?",
                        (name, unit_id, key),
                    )
                for key in original.keys() - ids:
                    conn.execute(
                        "UPDATE unit_structure SET billet_type_id=NULL WHERE unit_id=? AND billet_type_id=?",
                        (unit_id, key),
                    )
                for key, old in before.items():
                    record_change(
                        conn,
                        unit_id,
                        key,
                        old,
                        dict(history_reason="Billet type title changed"),
                    )
            g.audit_details = dict(
                unit_id=unit_id, change="billet types saved", count=len(parsed)
            )
            return jsonify(ok=True)
        except (ValueError, sqlite3.IntegrityError) as exc:
            return (
                jsonify(
                    ok=False,
                    error=(
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "Billet titles must be unique"
                    ),
                ),
                400,
            )
