"""Batch billet creation and empty structure copies, scoped to unit administrators."""

from flask import g, jsonify, request
from unit_common import number, text


def install(api, db, access, revision, endpoints, structure_node):
    names = {"unit_structure_copy", "unit_structure_billets"}
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
            names = []
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Choose valid billet entries")
                name = text(entry.get("name"), "Billet name", 80, True)
                count = number(entry.get("count", 1), "Copies", 1, 50)
                names.extend([name] * count)
            if len(names) > 100:
                raise ValueError("Add at most 100 billets in one save")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                revision(conn, unit_id, data)
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
                for offset, name in enumerate(names):
                    ids.append(
                        conn.execute(
                            "INSERT INTO unit_structure(unit_id,parent_id,kind,name,sort_order) VALUES(?,?,'billet',?,?)",
                            (unit_id, node_id, name, order + offset),
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
                        "INSERT INTO unit_structure(unit_id,parent_id,kind,name,sort_order) VALUES(?,?,?,?,?)",
                        (
                            unit_id,
                            destination,
                            node["kind"],
                            name if node["id"] == node_id else node["name"],
                            next_order(conn, unit_id, destination),
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
