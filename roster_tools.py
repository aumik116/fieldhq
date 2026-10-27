"""Qualification records, member timelines and explicit roster change previews."""

from datetime import date
import hashlib
import json
import time

from flask import abort, g, jsonify, request

from unit_common import actor as author, text, effective_certificates


def install(
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
):
    def configured_expiry(conn, unit_id, certificate, value, awarded_on):
        catalog = json.loads(
            conn.execute("SELECT catalog FROM units WHERE id=?", (unit_id,)).fetchone()[
                0
            ]
        )
        if not any(
            entry["name"] == certificate and entry.get("renewal_required")
            for entry in catalog.get("qualification_details", [])
        ):
            return ""
        return expiry_date(value, awarded_on)

    def state(conn, unit_id, member_id):
        row = conn.execute(
            "SELECT * FROM unit_roster WHERE unit_id=? AND id=?", (unit_id, member_id)
        ).fetchone()
        if not row:
            abort(404, description="Member not found in this unit")
        member = dict(row)
        decorate_slots(conn, unit_id, [member])
        member["status"] = member["scheduled_status"]
        return {
            key: member[key]
            for key in (
                "id",
                "game_name",
                "discord",
                "identity",
                "joined_on",
                "notes",
                "panel_user_id",
                "rank",
                "rank_track",
                "last_promo",
                "status",
                "loa_from",
                "loa_until",
                "archived",
                "certificates",
                "billet_id",
                "billet_path",
                "placement_id",
                "placement_path",
                "assignment_path",
                "callsign",
                "effective_callsign",
            )
        }

    def history(conn, unit_id, member_id, kind, before, after, reason="", actor=None):
        conn.execute(
            "INSERT INTO unit_roster_history(unit_id,member_id,kind,actor,created_at,before_value,after_value,reason) VALUES(?,?,?,?,?,?,?,?)",
            (
                unit_id,
                member_id,
                kind,
                actor if actor is not None else author(conn, unit_id),
                time.time(),
                json.dumps(before),
                json.dumps(after),
                reason,
            ),
        )

    def award_date(value, allow_unknown=False):
        if allow_unknown and value in ("", None):
            return None
        try:
            parsed = date.fromisoformat(value)
            if parsed > date.today():
                raise ValueError()
            return parsed.isoformat()
        except (ValueError, TypeError):
            raise ValueError("Choose an award date on or before today") from None

    def expiry_date(value, awarded_on):
        if not value:
            return ""
        try:
            value = date.fromisoformat(value).isoformat()
        except (ValueError, TypeError):
            raise ValueError("Choose a valid expiry date") from None
        if awarded_on and value < awarded_on:
            raise ValueError("Expiry must be on or after the award date")
        return value

    def record_change(conn, unit_id, member_id, before, data=None):
        data = data or {}
        after = state(conn, unit_id, member_id)
        reason = text(data.get("history_reason", ""), "Change note", 1000)
        if before is None:
            history(conn, unit_id, member_id, "created", None, after, reason)
        previous = before or {}
        for kind, keys in [
            ("rank", ("rank_track", "rank", "last_promo")),
            (
                "profile",
                (
                    "game_name",
                    "discord",
                    "identity",
                    "joined_on",
                    "notes",
                    "panel_user_id",
                ),
            ),
            ("billet", ("billet_id", "billet_path", "placement_id", "placement_path")),
            ("status", ("status", "archived", "loa_from", "loa_until")),
            ("callsign", ("callsign", "effective_callsign")),
        ]:
            old = {k: previous.get(k) for k in keys}
            new = {k: after[k] for k in keys}
            if before is not None and old != new:
                history(conn, unit_id, member_id, kind, old, new, reason)
        held = {c for c in after["certificates"].split(";") if c}
        old_held = {c for c in previous.get("certificates", "").split(";") if c}
        for certificate in sorted(old_held - held):
            row = conn.execute(
                "SELECT * FROM unit_qualification_awards WHERE unit_id=? AND member_id=? AND certificate=?",
                (unit_id, member_id, certificate),
            ).fetchone()
            history(
                conn,
                unit_id,
                member_id,
                "qualification_revoked",
                dict(row) if row else {"certificate": certificate},
                None,
                reason,
            )
            conn.execute(
                "DELETE FROM unit_qualification_awards WHERE unit_id=? AND member_id=? AND certificate=?",
                (unit_id, member_id, certificate),
            )
        for certificate in sorted(held - old_held):
            awarded_on = award_date(
                data.get("qualification_awarded_on") or date.today().isoformat()
            )
            notes = text(data.get("qualification_notes", reason), "Award notes", 1000)
            issuer = (
                text(
                    data.get("qualification_issuer", author(conn, unit_id)),
                    "Issuing staff name",
                    120,
                )
                or None
            )
            conn.execute(
                "INSERT INTO unit_qualification_awards(unit_id,member_id,certificate,awarded_on,issuer,notes) VALUES(?,?,?,?,?,?)",
                (unit_id, member_id, certificate, awarded_on, issuer, notes),
            )
            expires_on = configured_expiry(
                conn,
                unit_id,
                certificate,
                data.get("qualification_expires_on", ""),
                awarded_on,
            )
            conn.execute(
                "UPDATE unit_qualification_awards SET expires_on=? WHERE unit_id=? AND member_id=? AND certificate=?",
                (expires_on, unit_id, member_id, certificate),
            )
            history(
                conn,
                unit_id,
                member_id,
                "qualification_granted",
                None,
                dict(
                    certificate=certificate,
                    expires_on=expires_on,
                    awarded_on=awarded_on,
                    issuer=issuer,
                    notes=notes,
                ),
                reason,
            )

        record_strength(conn, unit_id, before, after)

    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS unit_qualification_awards (
                unit_id INTEGER NOT NULL, member_id INTEGER NOT NULL, certificate TEXT NOT NULL,
                awarded_on TEXT, issuer TEXT, notes TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(unit_id,member_id,certificate));
            CREATE TABLE IF NOT EXISTS unit_roster_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL,
                created_at REAL NOT NULL, before_value TEXT NOT NULL,
                after_value TEXT NOT NULL, reason TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_roster_history_member ON unit_roster_history(unit_id,member_id,id);
        """)
        if "expires_on" not in {
            row["name"]
            for row in conn.execute("PRAGMA table_info(unit_qualification_awards)")
        }:
            conn.execute(
                "ALTER TABLE unit_qualification_awards ADD COLUMN expires_on TEXT NOT NULL DEFAULT ''"
            )
        conn.execute("BEGIN IMMEDIATE")
        # Explicit expiry dates from the previous release already opted these awards in.
        for row in conn.execute("SELECT id,catalog FROM units").fetchall():
            catalog = json.loads(row["catalog"])
            details = {
                entry["name"]: entry
                for entry in catalog.get("qualification_details", [])
            }
            changed = False
            for name in catalog.get("certificates", []):
                entry = details.setdefault(
                    name,
                    dict(name=name, abbreviation="", description="", archived=False),
                )
                if "renewal_required" not in entry:
                    entry["renewal_required"] = bool(
                        conn.execute(
                            "SELECT 1 FROM unit_qualification_awards WHERE unit_id=? AND certificate=? AND expires_on!='' LIMIT 1",
                            (row["id"], name),
                        ).fetchone()
                    )
                    changed = True
            if changed:
                catalog["qualification_details"] = list(details.values())
                conn.execute(
                    "UPDATE units SET catalog=?,revision=revision+1 WHERE id=?",
                    (json.dumps(catalog), row["id"]),
                )
        # Existing data is a baseline, not evidence of when or by whom it was awarded.
        for member in conn.execute(
            "SELECT id,unit_id,certificates FROM unit_roster"
        ).fetchall():
            if not conn.execute(
                "SELECT 1 FROM unit_roster_history WHERE unit_id=? AND member_id=? LIMIT 1",
                (member["unit_id"], member["id"]),
            ).fetchone():
                history(
                    conn,
                    member["unit_id"],
                    member["id"],
                    "baseline",
                    None,
                    state(conn, member["unit_id"], member["id"]),
                    "Existing record at upgrade; earlier changes and award dates are unknown.",
                    actor="System",
                )
            for certificate in filter(None, member["certificates"].split(";")):
                conn.execute(
                    "INSERT OR IGNORE INTO unit_qualification_awards(unit_id,member_id,certificate,awarded_on,issuer,notes) VALUES(?,?,?,NULL,NULL,?)",
                    (
                        member["unit_id"],
                        member["id"],
                        certificate,
                        "Existing qualification; original date and issuer unknown.",
                    ),
                )

    names = {
        "unit_roster_tools",
        "unit_roster_timeline",
        "unit_qualification_save",
        "unit_qualification_delete",
        "unit_member_promote",
        "unit_promotion_preview",
        "unit_roster_bulk_preview",
        "unit_roster_bulk_apply",
        "unit_qualification_renew",
    }
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS

    MUTATIONS.update(
        {
            name: "view"
            for name in (
                "unit_qualification_save",
                "unit_qualification_delete",
                "unit_member_promote",
                "unit_roster_bulk_apply",
                "unit_qualification_renew",
            )
        }
    )

    @api.app.get("/api/units/<int:unit_id>/roster-tools")
    def unit_roster_tools(unit_id):
        with db() as conn:
            unit = access(conn, unit_id)
            awards = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM unit_qualification_awards WHERE unit_id=? ORDER BY member_id,certificate",
                    (unit_id,),
                )
            ]
            actor_name = author(conn, unit_id)
            renewing = {
                entry["name"]
                for entry in json.loads(unit["catalog"]).get(
                    "qualification_details", []
                )
                if entry.get("renewal_required")
            }
            for award in awards:
                if award["certificate"] not in renewing:
                    award["expires_on"] = ""
        return jsonify(
            awards=awards,
            revision=unit["revision"],
            today=date.today().isoformat(),
            actor=actor_name,
        )

    @api.app.post("/api/units/<int:unit_id>/qualifications/renew")
    def unit_qualification_renew(unit_id):
        data = request.get_json()
        try:
            selected = data.get("awards")
            if not isinstance(selected, list) or not 1 <= len(selected) <= 500:
                raise ValueError("Choose 1–500 qualification awards")
            awarded_on = award_date(data.get("awarded_on"))
            expires_on = expiry_date(data.get("expires_on", ""), awarded_on)
            if not expires_on:
                raise ValueError(
                    "Choose the new expiry date for these renewable qualifications"
                )
            reason = text(data.get("reason"), "Renewal reason", 1000, True)
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                unit = access(conn, unit_id, "roster")
                issuer = text(
                    data.get("issuer", author(conn, unit_id)), "Instructor", 120, True
                )
                catalog = json.loads(unit["catalog"])
                seen = set()
                changes = []
                for item in selected:
                    if (
                        not isinstance(item, dict)
                        or type(item.get("member_id")) is not int
                        or not 1 <= item["member_id"] <= 9223372036854775807
                    ):
                        raise ValueError("Choose a valid member award")
                    certificate = text(
                        item.get("certificate"), "Qualification", 80, True
                    )
                    key = (item["member_id"], certificate)
                    if key in seen:
                        raise ValueError("Each award can only be selected once")
                    seen.add(key)
                    member = conn.execute(
                        "SELECT game_name,certificates,archived FROM unit_roster WHERE unit_id=? AND id=?",
                        (unit_id, key[0]),
                    ).fetchone()
                    if (
                        not member
                        or member["archived"]
                        or certificate not in member["certificates"].split(";")
                    ):
                        raise ValueError(
                            "A selected award is no longer held by a current member"
                        )
                    definition = next(
                        (
                            entry
                            for entry in catalog.get("qualification_details", [])
                            if entry["name"] == certificate
                        ),
                        {},
                    )
                    if not definition.get("renewal_required"):
                        raise ValueError(
                            "Renewal is not configured for this qualification"
                        )
                    if certificate not in catalog.get(
                        "certificates", []
                    ) or definition.get("archived"):
                        raise ValueError("Restore the qualification before renewing it")
                    award = conn.execute(
                        "SELECT * FROM unit_qualification_awards WHERE unit_id=? AND member_id=? AND certificate=?",
                        (unit_id, *key),
                    ).fetchone()
                    if not award:
                        raise ValueError(
                            "A selected award changed; refresh the renewal queue"
                        )
                    before = dict(award)
                    after = dict(
                        before,
                        awarded_on=awarded_on,
                        expires_on=expires_on,
                        issuer=issuer,
                    )
                    changes.append(
                        dict(
                            member_id=key[0],
                            name=member["game_name"],
                            certificate=certificate,
                            before=before,
                            after=after,
                        )
                    )
                digest = hashlib.sha256(
                    json.dumps(
                        dict(changes=changes, reason=reason), sort_keys=True
                    ).encode()
                ).hexdigest()
                changed = sum(row["before"] != row["after"] for row in changes)
                if data.get("confirmed") is not True:
                    return jsonify(
                        ok=True, changes=changes, changed=changed, preview_token=digest
                    )
                if data.get("preview_token") != digest:
                    abort(
                        409,
                        description="These awards changed. Review a fresh renewal preview; your entered dates are still here.",
                    )
                for row in changes:
                    if row["before"] == row["after"]:
                        continue
                    conn.execute(
                        "UPDATE unit_qualification_awards SET awarded_on=?,expires_on=?,issuer=? WHERE unit_id=? AND member_id=? AND certificate=?",
                        (
                            awarded_on,
                            expires_on,
                            issuer,
                            unit_id,
                            row["member_id"],
                            row["certificate"],
                        ),
                    )
                    history(
                        conn,
                        unit_id,
                        row["member_id"],
                        "qualification_updated",
                        row["before"],
                        row["after"],
                        reason,
                    )
                if changed:
                    conn.execute(
                        "UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,)
                    )
            g.audit_details = dict(
                unit_id=unit_id,
                member_ids=[row["member_id"] for row in changes],
                change="qualification renewal",
                changed=changed,
            )
            return jsonify(ok=True, changed=changed)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.get("/api/units/<int:unit_id>/roster/<int:member_id>/timeline")
    def unit_roster_timeline(unit_id, member_id):
        try:
            before = int(request.args.get("before", "0"))
            if not 0 <= before <= 9223372036854775807:
                raise ValueError()
        except ValueError:
            return jsonify(ok=False, error="Choose a valid timeline cursor"), 400
        kind = request.args.get("kind", "all")
        if kind not in (
            "all",
            "rank",
            "billet",
            "qualification",
            "status",
            "callsign",
            "profile",
            "temporary",
        ):
            return jsonify(ok=False, error="Choose a valid timeline filter"), 400
        with db() as conn:
            access(conn, unit_id)
            state(conn, unit_id, member_id)
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM unit_roster_history WHERE unit_id=? AND member_id=? AND (?=0 OR id<?) AND (?='all' OR kind IN ('baseline','created') OR kind=? OR (?='qualification' AND kind LIKE 'qualification_%')) ORDER BY id DESC LIMIT 51",
                    (unit_id, member_id, before, before, kind, kind, kind),
                )
            ]
        for row in rows:
            row["before_value"] = json.loads(row["before_value"])
            row["after_value"] = json.loads(row["after_value"])
        return jsonify(
            entries=rows[:50], next_before=rows[49]["id"] if len(rows) > 50 else None
        )

    @api.app.post("/api/units/<int:unit_id>/qualifications/delete")
    def unit_qualification_delete(unit_id):
        try:
            data = request.get_json()
            name = text(data.get("name"), "Qualification", 80, True)
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                unit = access(conn, unit_id, "staff")
                if (
                    type(data.get("revision")) is not int
                    or data["revision"] != unit["revision"]
                ):
                    abort(
                        409,
                        description="This unit changed. Reopen the deletion preview.",
                    )
                catalog = json.loads(unit["catalog"])
                if name not in catalog.get("certificates", []):
                    raise ValueError("Qualification not found in this unit")
                members = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT id,game_name,certificates,archived FROM unit_roster WHERE unit_id=?",
                        (unit_id,),
                    )
                    if name in row["certificates"].split(";")
                ]
                ranks = [
                    dict(structure=track["name"], rank=rank["name"])
                    for track in catalog.get("rank_structures", [])
                    for rank in track["ranks"]
                    if name in rank["certificates"]
                ]
                rules = []
                for row in conn.execute(
                    "SELECT reference_id,targets FROM unit_document_rules WHERE unit_id=?",
                    (unit_id,),
                ):
                    old = json.loads(row["targets"])
                    new = [
                        target
                        for target in old
                        if not (
                            target["kind"] == "qualification"
                            and target.get("name") == name
                        )
                    ]
                    if new != old:
                        rules.append((row["reference_id"], new))
                references = []
                for row in conn.execute(
                    "SELECT id,title,related,published_value FROM unit_references WHERE unit_id=?",
                    (unit_id,),
                ):
                    related = json.loads(row["related"])
                    new = [
                        item
                        for item in related
                        if not (
                            item["kind"] == "qualification" and item.get("name") == name
                        )
                    ]
                    published = (
                        json.loads(row["published_value"]).get("related", "[]")
                        if row["published_value"]
                        else "[]"
                    )
                    published_related = (
                        json.loads(published)
                        if isinstance(published, str)
                        else published
                    )
                    if new != related or any(
                        item["kind"] == "qualification" and item.get("name") == name
                        for item in published_related
                    ):
                        references.append((row["id"], row["title"], new))
                impact = dict(
                    members=[
                        dict(
                            id=member["id"],
                            name=member["game_name"],
                            former=bool(member["archived"]),
                        )
                        for member in members
                    ],
                    ranks=ranks,
                    reading_audiences=len(rules),
                    references=[row[1] for row in references],
                )
                if data.get("confirmed") is not True:
                    g.audit_details = dict(
                        unit_id=unit_id,
                        qualification=name,
                        change="qualification deletion preview",
                    )
                    return jsonify(ok=True, impact=impact)
                if data.get("confirm_name") != name:
                    raise ValueError(
                        "Type the exact qualification name to confirm deletion"
                    )
                revision(conn, unit_id, data)
                for member in members:
                    before = state(conn, unit_id, member["id"])
                    certificates = ";".join(
                        value
                        for value in member["certificates"].split(";")
                        if value and value != name
                    )
                    conn.execute(
                        "UPDATE unit_roster SET certificates=?,updated_at=? WHERE unit_id=? AND id=?",
                        (certificates, time.time(), unit_id, member["id"]),
                    )
                    record_change(
                        conn,
                        unit_id,
                        member["id"],
                        before,
                        dict(
                            history_reason="Qualification deleted from unit catalog: "
                            + name
                        ),
                    )
                conn.execute(
                    "DELETE FROM unit_qualification_awards WHERE unit_id=? AND certificate=?",
                    (unit_id, name),
                )
                catalog["certificates"] = [
                    value for value in catalog["certificates"] if value != name
                ]
                catalog["qualification_details"] = [
                    value
                    for value in catalog.get("qualification_details", [])
                    if value["name"] != name
                ]
                for track in catalog.get("rank_structures", []):
                    for rank in track["ranks"]:
                        rank["certificates"] = [
                            value for value in rank["certificates"] if value != name
                        ]
                conn.execute(
                    "UPDATE units SET catalog=? WHERE id=?",
                    (json.dumps(catalog), unit_id),
                )
                for reference_id, targets in rules:
                    conn.execute(
                        "UPDATE unit_document_rules SET targets=? WHERE unit_id=? AND reference_id=?",
                        (json.dumps(targets), unit_id, reference_id),
                    )
                for reference_id, title, related in references:
                    conn.execute(
                        "UPDATE unit_references SET related=? WHERE unit_id=? AND id=?",
                        (json.dumps(related), unit_id, reference_id),
                    )
                sync_event_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                qualification=name,
                change="qualification deleted",
                member_awards=len(members),
                rank_requirements=len(ranks),
                reading_audiences=len(rules),
                references=len(references),
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/roster/<int:member_id>/qualifications")
    def unit_qualification_save(unit_id, member_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                unit = access(conn, unit_id, "roster")
                member_revision(conn, unit_id, data, member_id)
                before = state(conn, unit_id, member_id)
                certificate = text(data.get("certificate"), "Qualification", 80, True)
                if certificate not in json.loads(unit["catalog"]).get(
                    "certificates", []
                ):
                    raise ValueError("Choose a qualification from this unit’s catalog")
                held = set(filter(None, before["certificates"].split(";")))
                action = data.get("action")
                renewing = any(
                    entry["name"] == certificate and entry.get("renewal_required")
                    for entry in json.loads(unit["catalog"]).get(
                        "qualification_details", []
                    )
                )
                if action != "revoke" and data.get("expires_on") and not renewing:
                    abort(
                        409,
                        description="Renewal is no longer enabled for this qualification. Your draft is kept; review the current settings before saving.",
                    )
                if action == "grant" and renewing and not data.get("expires_on"):
                    raise ValueError(
                        "Choose an expiry date for this renewable qualification"
                    )
                reason = text(
                    data.get("reason", ""), "Reason", 1000, action == "revoke"
                )
                if action == "grant" and any(
                    entry["name"] == certificate and entry.get("archived")
                    for entry in json.loads(unit["catalog"]).get(
                        "qualification_details", []
                    )
                ):
                    raise ValueError("Restore this qualification before awarding it")
                if action == "grant":
                    if certificate in held:
                        raise ValueError("Already held; edit the award details instead")
                    held.add(certificate)
                elif action == "revoke":
                    if certificate not in held:
                        raise ValueError("This member does not hold that qualification")
                    held.remove(certificate)
                elif action == "update":
                    if certificate not in held:
                        raise ValueError(
                            "Grant the qualification before editing its details"
                        )
                    old = conn.execute(
                        "SELECT * FROM unit_qualification_awards WHERE unit_id=? AND member_id=? AND certificate=?",
                        (unit_id, member_id, certificate),
                    ).fetchone()
                    awarded_on = award_date(data.get("awarded_on"), allow_unknown=True)
                    expires_on = configured_expiry(
                        conn,
                        unit_id,
                        certificate,
                        data.get("expires_on", old["expires_on"]),
                        awarded_on,
                    )
                    notes = text(data.get("notes", ""), "Award notes", 1000)
                    issuer = (
                        text(
                            data.get("issuer", old["issuer"] or ""),
                            "Issuing staff name",
                            120,
                        )
                        or None
                    )
                    conn.execute(
                        "UPDATE unit_qualification_awards SET awarded_on=?,notes=?,issuer=?,expires_on=? WHERE unit_id=? AND member_id=? AND certificate=?",
                        (
                            awarded_on,
                            notes,
                            issuer,
                            expires_on,
                            unit_id,
                            member_id,
                            certificate,
                        ),
                    )
                    if (
                        old["awarded_on"],
                        old["issuer"],
                        old["notes"],
                        old["expires_on"],
                    ) != (
                        awarded_on,
                        issuer,
                        notes,
                        expires_on,
                    ):
                        history(
                            conn,
                            unit_id,
                            member_id,
                            "qualification_updated",
                            dict(old),
                            dict(
                                certificate=certificate,
                                expires_on=expires_on,
                                awarded_on=awarded_on,
                                issuer=issuer,
                                notes=notes,
                            ),
                            reason,
                        )
                else:
                    raise ValueError("Choose grant, revoke or update")
                if action != "update":
                    conn.execute(
                        "UPDATE unit_roster SET certificates=?,updated_at=? WHERE unit_id=? AND id=?",
                        (";".join(sorted(held)), time.time(), unit_id, member_id),
                    )
                    record_change(
                        conn,
                        unit_id,
                        member_id,
                        before,
                        dict(
                            history_reason=reason,
                            qualification_awarded_on=data.get("awarded_on"),
                            qualification_expires_on=data.get("expires_on", ""),
                            qualification_notes=data.get("notes", ""),
                            qualification_issuer=data.get(
                                "issuer", author(conn, unit_id)
                            ),
                        ),
                    )
                sync_event_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                member_id=member_id,
                qualification=certificate,
                change=action,
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def promotion_at(conn, unit_id, member, catalog, raw_date):
        effective = award_date(raw_date or date.today().isoformat())
        if member["last_promo"] and effective < member["last_promo"]:
            raise ValueError("Promotion cannot predate the previous promotion")
        member = dict(member)
        member["active_certificates"] = effective_certificates(
            conn, unit_id, member, effective
        )
        result = promotion(member, catalog, effective)
        return effective, result

    @api.app.post("/api/units/<int:unit_id>/roster/<int:member_id>/promotion-preview")
    def unit_promotion_preview(unit_id, member_id):
        try:
            with db() as conn:
                unit = access(conn, unit_id, "roster")
                member = conn.execute(
                    "SELECT * FROM unit_roster WHERE unit_id=? AND id=?",
                    (unit_id, member_id),
                ).fetchone()
                if not member:
                    abort(404, description="Member not found")
                effective, ready = promotion_at(
                    conn,
                    unit_id,
                    member,
                    json.loads(unit["catalog"]),
                    request.get_json().get("effective_date"),
                )
            return jsonify(ok=True, effective_date=effective, promotion=ready)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/roster/<int:member_id>/promote")
    def unit_member_promote(unit_id, member_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                unit = access(conn, unit_id, "roster")
                member_revision(conn, unit_id, data, member_id)
                member = conn.execute(
                    "SELECT * FROM unit_roster WHERE unit_id=? AND id=?",
                    (unit_id, member_id),
                ).fetchone()
                if not member:
                    abort(404, description="Member not found in this unit")
                effective, ready = promotion_at(
                    conn,
                    unit_id,
                    member,
                    json.loads(unit["catalog"]),
                    data.get("effective_date"),
                )
                if (
                    not ready["eligible"]
                    or data.get("confirm_rank") != ready["next_rank"]
                    or data.get("confirm_date") != date.today().isoformat()
                ):
                    raise ValueError(
                        "The rank, promotion date or eligibility changed. Reload the review queue before confirming."
                    )
                reason = text(data.get("reason"), "Promotion review note", 1000, True)
                before = state(conn, unit_id, member_id)
                conn.execute(
                    "UPDATE unit_roster SET rank=?,last_promo=?,updated_at=? WHERE unit_id=? AND id=?",
                    (
                        ready["next_rank"],
                        effective,
                        time.time(),
                        unit_id,
                        member_id,
                    ),
                )
                record_change(
                    conn, unit_id, member_id, before, dict(history_reason=reason)
                )
                sync_event_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                member_id=member_id,
                change="manual promotion",
                before=before["rank"],
                after=ready["next_rank"],
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def bulk_plan(conn, unit_id, data):
        unit = access(conn, unit_id, "roster")
        if (
            type(data.get("revision")) is not int
            or data["revision"] != unit["revision"]
        ):
            abort(
                409,
                description="This unit changed. Reload the roster and preview again.",
            )
        ids = data.get("members")
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 500
            or any(type(i) is not int for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("Select 1–500 distinct current members")
        action = data.get("action")
        reason = text(data.get("reason"), "Bulk change reason", 1000, True)
        changes = []
        for member_id in sorted(ids):
            before = state(conn, unit_id, member_id)
            if before["archived"]:
                raise ValueError("Restore former members before applying bulk changes")
            changes.append(
                dict(
                    member_id=member_id,
                    name=before["game_name"],
                    before=before,
                    after=dict(before),
                )
            )
        if action in ("grant", "revoke"):
            certificate = text(data.get("certificate"), "Qualification", 80, True)
            if certificate not in json.loads(unit["catalog"]).get("certificates", []):
                raise ValueError("Choose a qualification from this unit’s catalog")
            if action == "grant":
                if any(
                    entry["name"] == certificate and entry.get("archived")
                    for entry in json.loads(unit["catalog"]).get(
                        "qualification_details", []
                    )
                ):
                    raise ValueError("Restore this qualification before awarding it")
                awarded_on = award_date(data.get("awarded_on"))
                expiry_date(data.get("expires_on", ""), awarded_on)
                text(data.get("issuer", ""), "Issuing staff name", 120)
            for change in changes:
                held = set(filter(None, change["before"]["certificates"].split(";")))
                if action == "grant":
                    held.add(certificate)
                else:
                    held.discard(certificate)
                change["after"]["certificates"] = ";".join(sorted(held))
        elif action == "status":
            status = data.get("status")
            if status not in ("active", "reserve", "loa"):
                raise ValueError("Choose Active, Reserve or LOA")
            for change in changes:
                change["after"]["status"] = status
                if status != change["before"]["status"]:
                    change["after"]["loa_from"] = ""
                    change["after"]["loa_until"] = ""
        elif action in ("section", "unassign"):
            nodes = structure_rows(conn, unit_id)
            available = []
            if action == "section":
                target = data.get("section_id")
                if type(target) is not int or not any(
                    n["id"] == target and n["kind"] == "section" for n in nodes
                ):
                    raise ValueError("Choose a section in this unit")
                descendants = {target}
                for _ in range(7):
                    descendants.update(
                        n["id"] for n in nodes if n["parent_id"] in descendants
                    )
                billets = []

                def visit(parent_id):
                    for node in nodes:
                        if node["parent_id"] == parent_id:
                            if node["kind"] == "billet":
                                billets.append(node)
                            else:
                                visit(node["id"])

                visit(target)
                occupied = {
                    r[0]
                    for r in conn.execute(
                        "SELECT billet_id FROM unit_primary_slots WHERE unit_id=?",
                        (unit_id,),
                    )
                }
                available = [n for n in billets if n["id"] not in occupied]
                by_id = {n["id"]: n for n in nodes}
            for change in changes:
                if action == "section" and change["before"]["billet_id"] in descendants:
                    continue
                billet_id = None
                path = ""
                if action == "section":
                    if not available:
                        raise ValueError(
                            "There are not enough open billets in the selected section. Add slots or select fewer members."
                        )
                    billet = available.pop(0)
                    billet_id = billet["id"]
                    parts = [billet["name"]]
                    parent = by_id.get(billet["parent_id"])
                    while parent:
                        parts.append(parent["name"])
                        parent = by_id.get(parent["parent_id"])
                    path = " / ".join(reversed(parts))
                change["after"].update(
                    billet_id=billet_id,
                    billet_path=path,
                    placement_id=None,
                    placement_path="",
                    assignment_path=path,
                )
        else:
            raise ValueError(
                "Choose qualification grant/revoke, status, section move or unassign"
            )
        payload = dict(
            revision=unit["revision"],
            action=action,
            reason=reason,
            certificate=data.get("certificate"),
            awarded_on=data.get("awarded_on"),
            expires_on=data.get("expires_on", ""),
            issuer=data.get("issuer", ""),
            status=data.get("status"),
            section_id=data.get("section_id"),
            changes=changes,
        )
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        return changes, digest

    @api.app.post("/api/units/<int:unit_id>/roster/bulk/preview")
    def unit_roster_bulk_preview(unit_id):
        try:
            with db() as conn:
                # One read transaction keeps the revision and proposed changes consistent.
                conn.execute("BEGIN")
                changes, token = bulk_plan(conn, unit_id, request.get_json())
            return jsonify(ok=True, changes=changes, preview_token=token)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/roster/bulk/apply")
    def unit_roster_bulk_apply(unit_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                changes, token = bulk_plan(conn, unit_id, data)
                if data.get("preview_token") != token:
                    abort(
                        409,
                        description="The preview changed. Review a fresh preview before applying.",
                    )
                revision(conn, unit_id, data)
                for change in changes:
                    before = change["before"]
                    after = change["after"]
                    member_id = change["member_id"]
                    if before == after:
                        continue
                    conn.execute(
                        "UPDATE unit_roster SET certificates=?,status=?,loa_from=?,loa_until=?,updated_at=? WHERE unit_id=? AND id=?",
                        (
                            after["certificates"],
                            after["status"],
                            after["loa_from"],
                            after["loa_until"],
                            time.time(),
                            unit_id,
                            member_id,
                        ),
                    )
                    if before["placement_id"] != after["placement_id"]:
                        assign_placement(
                            conn, unit_id, member_id, after["placement_id"]
                        )
                    if before["billet_id"] != after["billet_id"]:
                        assign_slot(conn, unit_id, member_id, after["billet_id"])
                    record_change(
                        conn,
                        unit_id,
                        member_id,
                        before,
                        dict(
                            history_reason=data["reason"],
                            qualification_awarded_on=data.get("awarded_on"),
                            qualification_expires_on=data.get("expires_on", ""),
                            qualification_issuer=data.get("issuer")
                            or author(conn, unit_id),
                        ),
                    )
                sync_event_roster(conn, unit_id)
            g.audit_details = dict(
                unit_id=unit_id,
                member_ids=[c["member_id"] for c in changes],
                change="bulk " + data["action"],
            )
            return jsonify(
                ok=True, changed=sum(c["before"] != c["after"] for c in changes)
            )
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    return state, record_change
