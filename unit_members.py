"""Member self-service, reading acknowledgements and staff document reviews."""

from datetime import date
import json
import time

from flask import abort, g, jsonify, request
from functools import partial
from unit_common import actor, can, publication_digest, text, roster_status


def install(api, db, access, revision, panel_admin, endpoints):
    staff = partial(can, panel_admin=panel_admin)
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS unit_document_rules (
                unit_id INTEGER NOT NULL, reference_id INTEGER NOT NULL,
                targets TEXT NOT NULL DEFAULT '[]', reading_due TEXT NOT NULL DEFAULT '',
                owner_id INTEGER, reviewed_on TEXT NOT NULL DEFAULT '', review_on TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(unit_id,reference_id));
            CREATE TABLE IF NOT EXISTS unit_reading_acknowledgements (
                unit_id INTEGER NOT NULL, reference_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                publication TEXT NOT NULL, acknowledged_at REAL NOT NULL,
                PRIMARY KEY(unit_id,reference_id,user_id,publication));
            CREATE TABLE IF NOT EXISTS unit_event_rsvps (
                unit_id INTEGER NOT NULL, event_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL, event_version INTEGER NOT NULL, answer TEXT NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(unit_id,event_id,user_id));
            CREATE TABLE IF NOT EXISTS unit_member_announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                title TEXT NOT NULL, body TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
                expires_on TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0,
                author TEXT NOT NULL, updated_at REAL NOT NULL);
        """)
    names = {
        "unit_member_home",
        "unit_self_profile",
        "unit_reading_acknowledge",
        "unit_rsvp_save",
        "unit_document_rules",
        "unit_document_rules_save",
        "unit_announcement_save",
    }
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS

    MUTATIONS.update(
        {
            name: "view"
            for name in (
                "unit_reading_acknowledge",
                "unit_rsvp_save",
                "unit_document_rules_save",
                "unit_announcement_save",
            )
        }
    )

    def own_member(conn, unit_id):
        return conn.execute(
            "SELECT * FROM unit_roster WHERE unit_id=? AND panel_user_id=?",
            (unit_id, g.user["id"]),
        ).fetchone()

    def document(conn, unit_id, reference_id):
        if not 1 <= reference_id <= 9223372036854775807:
            abort(404, description="SOP not found")
        row = conn.execute(
            "SELECT * FROM unit_references WHERE unit_id=? AND id=? AND kind='sop'",
            (unit_id, reference_id),
        ).fetchone()
        if not row:
            abort(404, description="SOP not found in this unit")
        return row

    def applies(conn, unit_id, member, targets):
        positions = set()
        if member and not member["archived"]:
            positions.update(
                position.strip()
                for position in member["position"].split(";")
                if position.strip()
            )
            slot = conn.execute(
                "SELECT s.name FROM unit_primary_slots p JOIN unit_structure s ON s.id=p.billet_id AND s.unit_id=p.unit_id WHERE p.unit_id=? AND p.member_id=?",
                (unit_id, member["id"]),
            ).fetchone()
            if slot:
                positions.add(slot["name"])
        certificates = (
            set(member["certificates"].split(";"))
            if member and not member["archived"]
            else set()
        )
        return any(
            t["kind"] == "all"
            or t["kind"] == "position"
            and t["name"] in positions
            or t["kind"] == "qualification"
            and t["name"] in certificates
            for t in targets
        )

    def reading(conn, unit_id):
        member = own_member(conn, unit_id)
        result = []
        for row in conn.execute(
            "SELECT r.id,r.title,r.published_value,d.targets,d.reading_due FROM unit_references r JOIN unit_document_rules d ON d.reference_id=r.id AND d.unit_id=r.unit_id WHERE r.unit_id=? AND r.kind='sop' AND r.archived=0 AND r.published_value!=''",
            (unit_id,),
        ):
            if not applies(conn, unit_id, member, json.loads(row["targets"])):
                continue
            digest = publication_digest(row["published_value"])
            ack = conn.execute(
                "SELECT acknowledged_at FROM unit_reading_acknowledgements WHERE unit_id=? AND reference_id=? AND user_id=? AND publication=?",
                (unit_id, row["id"], g.user["id"], digest),
            ).fetchone()
            published = json.loads(row["published_value"])
            result.append(
                dict(
                    id=row["id"],
                    title=published["title"],
                    publication=digest,
                    due=row["reading_due"],
                    acknowledged_at=ack[0] if ack else None,
                )
            )
        return sorted(
            result,
            key=lambda r: (
                r["acknowledged_at"] is not None,
                r["due"] or "9999",
                r["title"].casefold(),
            ),
        )

    def calendar_day(value, label):
        value = text(value, label, 10)
        if value:
            try:
                parsed = date.fromisoformat(value)
                if not 2000 <= parsed.year <= 2100:
                    raise ValueError()
                value = parsed.isoformat()
            except ValueError:
                raise ValueError(f"{label}: choose a valid date") from None
        return value

    def review_list(conn, unit_id):
        return [
            dict(r)
            for r in conn.execute(
                "SELECT r.id,r.title,d.review_on,d.reviewed_on,d.owner_id,coalesce(m.game_name,u.username,'Unassigned') AS owner FROM unit_document_rules d JOIN unit_references r ON r.id=d.reference_id AND r.unit_id=d.unit_id LEFT JOIN users u ON u.id=d.owner_id LEFT JOIN unit_roster m ON m.unit_id=d.unit_id AND m.panel_user_id=d.owner_id WHERE d.unit_id=? AND r.archived=0 AND r.status!='template' AND d.review_on!='' ORDER BY d.review_on,r.title",
                (unit_id,),
            )
        ]

    @api.app.get("/api/units/<int:unit_id>/member-home")
    def unit_member_home(unit_id):
        with db() as conn:
            unit = access(conn, unit_id)
            now = time.time()
            today = date.today().isoformat()
            member = own_member(conn, unit_id)
            can_manage = staff(conn, unit_id, "references")
            can_events = staff(conn, unit_id, "events")
            announcements = [
                dict(r)
                for r in conn.execute(
                    "SELECT id,title,body,pinned,expires_on,author,updated_at FROM unit_member_announcements WHERE unit_id=? AND archived=0 AND (expires_on='' OR expires_on>=?) ORDER BY pinned DESC,updated_at DESC LIMIT 100",
                    (unit_id, today),
                )
            ]
            events = [
                dict(r)
                for r in conn.execute(
                    "SELECT e.id,e.name,e.category,e.briefing,e.location,e.starts,e.ends,e.timezone,e.version,r.answer AS rsvp FROM unit_events e LEFT JOIN unit_event_rsvps r ON r.event_id=e.id AND r.unit_id=e.unit_id AND r.user_id=? AND r.member_id=? AND r.event_version=e.version WHERE e.unit_id=? AND e.state='scheduled' AND e.ends>? AND (e.formation_ids='[]' OR ? OR EXISTS(SELECT 1 FROM unit_event_members em WHERE em.event_id=e.id AND em.member_id=?)) ORDER BY e.starts,e.id LIMIT 50",
                    (
                        g.user["id"],
                        member["id"] if member else -1,
                        unit_id,
                        now,
                        int(can_events),
                        member["id"] if member else -1,
                    ),
                )
            ]
            invited_events = {
                row[0]
                for row in conn.execute(
                    "SELECT m.event_id FROM unit_event_members m JOIN unit_events e ON e.id=m.event_id WHERE e.unit_id=? AND m.member_id=? AND e.state=? AND e.starts>?",
                    (unit_id, member["id"] if member else -1, "scheduled", now),
                )
            }
            for event in events:
                event["can_rsvp"] = bool(
                    member
                    and not member["archived"]
                    and event["starts"] > now
                    and event["id"] in invited_events
                )
                if can_events:
                    event["responses"] = [
                        dict(r)
                        for r in conn.execute(
                            "SELECT p.answer,m.game_name FROM unit_event_rsvps p JOIN unit_roster m ON m.unit_id=p.unit_id AND m.id=p.member_id AND m.panel_user_id=p.user_id JOIN unit_staff s ON s.unit_id=p.unit_id AND s.user_id=p.user_id JOIN users u ON u.id=p.user_id WHERE p.unit_id=? AND p.event_id=? AND p.event_version=? AND m.archived=0 AND u.enabled=1 ORDER BY p.answer,m.game_name",
                            (unit_id, event["id"], event["version"]),
                        )
                    ]
            reviews = review_list(conn, unit_id) if can_manage else []
            announcement_history = (
                [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM unit_member_announcements WHERE unit_id=? ORDER BY updated_at DESC LIMIT 100",
                        (unit_id,),
                    )
                ]
                if can_manage
                else []
            )
            return jsonify(
                announcement_history=announcement_history,
                reading=reading(conn, unit_id),
                announcements=announcements,
                events=events,
                reviews=reviews,
                review_due=sum(r["review_on"] <= today for r in reviews),
                can_manage=can_manage,
                can_events=can_events,
                profile_linked=bool(member),
                revision=unit["revision"],
                today=today,
            )

    @api.app.get("/api/units/<int:unit_id>/my-profile")
    def unit_self_profile(unit_id):
        with db() as conn:
            unit = access(conn, unit_id)
            member = own_member(conn, unit_id)
            if not member:
                return jsonify(
                    member=None, attendance=[], qualifications=[], positions=[]
                )
            keys = (
                "game_name",
                "discord",
                "status",
                "rank",
                "rank_track",
                "position",
                "joined_on",
                "last_promo",
                "certificates",
                "archived",
            )
            public = {key: member[key] for key in keys}
            public["status"] = roster_status(member)
            # Award notes and staff attendance reasons never enter this response.
            qualifications = [
                dict(r)
                for r in conn.execute(
                    "SELECT certificate,awarded_on,expires_on FROM unit_qualification_awards WHERE unit_id=? AND member_id=? ORDER BY certificate",
                    (unit_id, member["id"]),
                )
            ]
            renewing = {
                entry["name"]
                for entry in json.loads(unit["catalog"]).get(
                    "qualification_details", []
                )
                if entry.get("renewal_required")
            }
            for qualification in qualifications:
                if qualification["certificate"] not in renewing:
                    qualification["expires_on"] = ""
            positions = [
                dict(r)
                for r in conn.execute(
                    "SELECT s.id,s.name,s.parent_id,s.kind,s.callsign FROM unit_structure s WHERE s.unit_id=?",
                    (unit_id,),
                )
            ]
            assigned = conn.execute(
                "SELECT billet_id FROM unit_primary_slots WHERE unit_id=? AND member_id=? UNION ALL SELECT parent_id FROM unit_member_placements WHERE unit_id=? AND member_id=? LIMIT 1",
                (unit_id, member["id"], unit_id, member["id"]),
            ).fetchone()
            by_id = {p["id"]: p for p in positions}
            path = []
            node = by_id.get(assigned[0]) if assigned else None
            public["effective_callsign"] = member["callsign"] or (
                node["callsign"] if node and node["kind"] == "billet" else ""
            )
            visited = set()
            while node and node["id"] not in visited:
                visited.add(node["id"])
                path.insert(0, node["name"])
                node = by_id.get(node["parent_id"])
            attendance = [
                dict(r)
                for r in conn.execute(
                    "SELECT e.id,e.name,e.starts,m.outcome,m.expected FROM unit_event_members m JOIN unit_events e ON e.id=m.event_id WHERE e.unit_id=? AND m.member_id=? AND e.state='finalized' AND e.tracked=1 ORDER BY e.starts DESC LIMIT 100",
                    (unit_id, member["id"]),
                )
            ]
            return jsonify(
                member=public,
                qualifications=qualifications,
                positions=path,
                attendance=attendance,
            )

    @api.app.post("/api/units/<int:unit_id>/reading/<int:reference_id>/acknowledge")
    def unit_reading_acknowledge(unit_id, reference_id):
        data = request.get_json()
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            access(conn, unit_id)
            row = document(conn, unit_id, reference_id)
            rule = conn.execute(
                "SELECT targets FROM unit_document_rules WHERE unit_id=? AND reference_id=?",
                (unit_id, reference_id),
            ).fetchone()
            if (
                row["archived"]
                or not row["published_value"]
                or not rule
                or not applies(
                    conn,
                    unit_id,
                    own_member(conn, unit_id),
                    json.loads(rule["targets"]),
                )
            ):
                abort(404, description="Required reading not found")
            digest = publication_digest(row["published_value"])
            if data.get("publication") != digest:
                abort(
                    409,
                    description="This SOP was republished. Open the latest version before acknowledging it.",
                )
            conn.execute(
                "INSERT OR IGNORE INTO unit_reading_acknowledgements VALUES(?,?,?,?,?)",
                (unit_id, reference_id, g.user["id"], digest, time.time()),
            )
        g.audit_details = dict(
            unit_id=unit_id,
            reference_id=reference_id,
            change="required reading acknowledged",
        )
        return jsonify(ok=True)

    @api.app.post("/api/units/<int:unit_id>/member-events/<int:event_id>/rsvp")
    def unit_rsvp_save(unit_id, event_id):
        data = request.get_json()
        if not 1 <= event_id <= 9223372036854775807:
            abort(404, description="Event not found")
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            access(conn, unit_id)
            member = own_member(conn, unit_id)
            if not member or member["archived"]:
                abort(
                    403,
                    description="Ask a unit administrator to link your login to an active roster member first",
                )
            event = conn.execute(
                "SELECT * FROM unit_events WHERE unit_id=? AND id=?",
                (unit_id, event_id),
            ).fetchone()
            if not event:
                abort(404, description="Event not found")
            if not conn.execute(
                "SELECT 1 FROM unit_event_members WHERE event_id=? AND member_id=?",
                (event_id, member["id"]),
            ).fetchone():
                abort(403, description="You are not on this event’s selected roster")
            if (
                event["state"] != "scheduled"
                or event["starts"] <= time.time()
                or type(data.get("version")) is not int
                or data["version"] != event["version"]
            ):
                abort(
                    409,
                    description="This event changed or has started. Refresh the event list.",
                )
            answer = data.get("answer")
            if answer not in ("attending", "tentative", "unavailable", "clear"):
                return jsonify(ok=False, error="Choose a valid RSVP"), 400
            if answer == "clear":
                conn.execute(
                    "DELETE FROM unit_event_rsvps WHERE unit_id=? AND event_id=? AND user_id=?",
                    (unit_id, event_id, g.user["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO unit_event_rsvps VALUES(?,?,?,?,?,?,?) ON CONFLICT(unit_id,event_id,user_id) DO UPDATE SET member_id=excluded.member_id,event_version=excluded.event_version,answer=excluded.answer,updated_at=excluded.updated_at",
                    (
                        unit_id,
                        event_id,
                        g.user["id"],
                        member["id"],
                        event["version"],
                        answer,
                        time.time(),
                    ),
                )
        g.audit_details = dict(
            unit_id=unit_id, event_id=event_id, answer=answer, change="event RSVP"
        )
        return jsonify(ok=True)

    @api.app.get("/api/units/<int:unit_id>/library/<int:reference_id>/rules")
    def unit_document_rules(unit_id, reference_id):
        with db() as conn:
            unit = access(conn, unit_id, "references")
            row = document(conn, unit_id, reference_id)
            rules = conn.execute(
                "SELECT * FROM unit_document_rules WHERE unit_id=? AND reference_id=?",
                (unit_id, reference_id),
            ).fetchone()
            owners = [
                dict(r)
                for r in conn.execute(
                    "SELECT u.id,coalesce(m.game_name,u.username) AS name FROM unit_staff s JOIN users u ON u.id=s.user_id LEFT JOIN unit_roster m ON m.unit_id=s.unit_id AND m.panel_user_id=s.user_id WHERE s.unit_id=? AND s.role IN ('staff','admin') AND u.enabled=1 ORDER BY name",
                    (unit_id,),
                )
            ]
            accounts = conn.execute(
                "SELECT u.id,u.username FROM unit_staff s JOIN users u ON u.id=s.user_id WHERE s.unit_id=? AND u.enabled=1",
                (unit_id,),
            ).fetchall()
            progress = []
            targets = json.loads(rules["targets"]) if rules else []
            if row["published_value"] and not row["archived"]:
                for account in accounts:
                    member = conn.execute(
                        "SELECT * FROM unit_roster WHERE unit_id=? AND panel_user_id=?",
                        (unit_id, account["id"]),
                    ).fetchone()
                    if applies(conn, unit_id, member, targets):
                        ack = conn.execute(
                            "SELECT acknowledged_at FROM unit_reading_acknowledgements WHERE unit_id=? AND reference_id=? AND user_id=? AND publication=?",
                            (
                                unit_id,
                                reference_id,
                                account["id"],
                                publication_digest(row["published_value"]),
                            ),
                        ).fetchone()
                        progress.append(
                            dict(
                                name=(
                                    member["game_name"]
                                    if member
                                    else account["username"]
                                ),
                                acknowledged_at=ack[0] if ack else None,
                            )
                        )
            return jsonify(
                rules=dict(rules) if rules else None,
                owners=owners,
                progress=progress,
                revision=unit["revision"],
            )

    @api.app.post("/api/units/<int:unit_id>/library/<int:reference_id>/rules")
    def unit_document_rules_save(unit_id, reference_id):
        try:
            data = request.get_json()
            targets = data.get("targets", [])
            if not isinstance(targets, list) or len(targets) > 50:
                raise ValueError("Choose at most 50 reading audiences")
            reading_due = calendar_day(data.get("reading_due", ""), "Reading deadline")
            review_on = calendar_day(data.get("review_on", ""), "Next review")
            reviewed_on = calendar_day(data.get("reviewed_on", ""), "Last review")
            if reviewed_on and reviewed_on > date.today().isoformat():
                raise ValueError("Last review cannot be in the future")
            if reviewed_on and review_on and review_on < reviewed_on:
                raise ValueError("Next review cannot be before the last review")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                unit = access(conn, unit_id, "references")
                revision(conn, unit_id, data)
                document(conn, unit_id, reference_id)
                catalog = json.loads(unit["catalog"])
                clean = []
                for target in targets:
                    if not isinstance(target, dict) or target.get("kind") not in (
                        "all",
                        "position",
                        "qualification",
                    ):
                        raise ValueError("Choose valid reading audiences")
                    kind = target["kind"]
                    name = (
                        ""
                        if kind == "all"
                        else text(target.get("name"), "Audience", 120, True)
                    )
                    if (
                        kind != "all"
                        and name
                        not in catalog.get(
                            "positions" if kind == "position" else "certificates", []
                        )
                        and not (
                            kind == "position"
                            and conn.execute(
                                "SELECT 1 FROM unit_structure WHERE unit_id=? AND kind='billet' AND name=?",
                                (unit_id, name),
                            ).fetchone()
                        )
                    ):
                        raise ValueError(
                            "Choose an existing unit position or qualification"
                        )
                    if dict(kind=kind, name=name) not in clean:
                        clean.append(dict(kind=kind, name=name))
                owner = data.get("owner_id")
                if owner is not None and (
                    type(owner) is not int
                    or not conn.execute(
                        "SELECT 1 FROM unit_staff s JOIN users u ON u.id=s.user_id WHERE s.unit_id=? AND s.user_id=? AND s.role IN ('staff','admin') AND u.enabled=1",
                        (unit_id, owner),
                    ).fetchone()
                ):
                    raise ValueError("Choose an active unit staff member as owner")
                conn.execute(
                    "INSERT INTO unit_document_rules VALUES(?,?,?,?,?,?,?) ON CONFLICT(unit_id,reference_id) DO UPDATE SET targets=excluded.targets,reading_due=excluded.reading_due,owner_id=excluded.owner_id,reviewed_on=excluded.reviewed_on,review_on=excluded.review_on",
                    (
                        unit_id,
                        reference_id,
                        json.dumps(clean),
                        reading_due,
                        owner,
                        reviewed_on,
                        review_on,
                    ),
                )
            g.audit_details = dict(
                unit_id=unit_id,
                reference_id=reference_id,
                change="SOP reading and review rules saved",
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/announcements")
    def unit_announcement_save(unit_id):
        try:
            data = request.get_json()
            title = text(data.get("title"), "Title", 120, True)
            body = text(data.get("body"), "Announcement", 8000, True)
            expires = calendar_day(data.get("expires_on", ""), "Expiry date")
            if (
                type(data.get("pinned", False)) is not bool
                or type(data.get("archived", False)) is not bool
            ):
                raise ValueError("Choose valid announcement options")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "references")
                revision(conn, unit_id, data)
                values = (
                    title,
                    body,
                    int(data.get("pinned", False)),
                    expires,
                    int(data.get("archived", False)),
                    actor(conn, unit_id),
                    time.time(),
                )
                if "id" in data:
                    if not conn.execute(
                        "UPDATE unit_member_announcements SET title=?,body=?,pinned=?,expires_on=?,archived=?,author=?,updated_at=? WHERE unit_id=? AND id=?",
                        (*values, unit_id, data["id"]),
                    ).rowcount:
                        abort(404, description="Announcement not found")
                else:
                    if (
                        conn.execute(
                            "SELECT count(*) FROM unit_member_announcements WHERE unit_id=?",
                            (unit_id,),
                        ).fetchone()[0]
                        >= 1000
                    ):
                        raise ValueError("Keep at most 1000 announcements per unit")
                    conn.execute(
                        "INSERT INTO unit_member_announcements(unit_id,title,body,pinned,expires_on,archived,author,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (unit_id, *values),
                    )
            g.audit_details = dict(unit_id=unit_id, change="unit announcement saved")
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    return reading
