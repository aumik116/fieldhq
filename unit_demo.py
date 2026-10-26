"""An opt-in, editable fictional unit for exploring the normal unit workspace."""

from datetime import date, timedelta
import json
import time

from flask import abort, g, jsonify
from unit_common import audit


def install(api, db, panel_admin, endpoints, record_change, record_strength):
    with db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS unit_demo_units(unit_id INTEGER PRIMARY KEY)"
        )
    endpoint = "unit_demo_create"
    endpoints.add(endpoint)
    api.PANEL_WIDE_ENDPOINTS.add(endpoint)
    from panel_features import MUTATIONS

    MUTATIONS[endpoint] = "view"

    @api.app.post("/api/units/demo")
    def unit_demo_create():
        if not panel_admin():
            abort(403, description="Only panel administrators can create the demo unit")
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT u.id FROM units u JOIN unit_demo_units d ON d.unit_id=u.id LIMIT 1"
            ).fetchone()
            if existing:
                return jsonify(ok=True, id=existing["id"], existing=True)
            unit_id = seed(conn)
        g.audit_details = dict(unit_id=unit_id, change="demo unit created", members=48)
        return jsonify(ok=True, id=unit_id, existing=False)

    def seed(conn):
        today = date.today()
        now = time.time()

        def rank(name, days=0, next_rank="", certificates=()):
            return dict(
                name=name,
                paygrade="",
                days=days,
                next_rank=next_rank,
                certificates=list(certificates),
            )

        catalog = dict(
            certificates=[
                "Basic training",
                "Leadership",
                "Radio operator",
                "Medical",
                "Support weapons",
            ],
            positions=[],
            rank_structures=[
                dict(
                    name="Enlisted",
                    ranks=[
                        rank("Pvt", next_rank="Pfc"),
                        rank("Pfc", 30, "Cpl", ["Basic training"]),
                        rank("Cpl", 45, "Sgt", ["Leadership"]),
                        rank("Sgt", 60, "SSgt", ["Leadership", "Radio operator"]),
                        rank("SSgt", 90, "1st Sgt", ["Leadership"]),
                        rank("1st Sgt", 120),
                    ],
                ),
                dict(
                    name="Officer",
                    ranks=[
                        rank("2nd Lt", next_rank="1st Lt"),
                        rank("1st Lt", 90, "Capt", ["Leadership"]),
                        rank("Capt", 180),
                    ],
                ),
                dict(
                    name="Medical",
                    ranks=[
                        rank("HM3", next_rank="HM2"),
                        rank("HM2", 60, certificates=["Medical"]),
                    ],
                ),
            ],
        )
        name = "Demo Company — Training Sandbox"
        # Do not adopt a real unit that happens to use the same display name.
        if conn.execute("SELECT 1 FROM units WHERE name=?", (name,)).fetchone():
            base = name
            number = 2
            while conn.execute("SELECT 1 FROM units WHERE name=?", (name,)).fetchone():
                name = f"{base} {number}"
                number += 1
        unit_id = conn.execute(
            "INSERT INTO units(name,tag,catalog) VALUES(?,?,?)",
            (name, "DEMO", json.dumps(catalog)),
        ).lastrowid
        conn.execute("INSERT INTO unit_demo_units VALUES(?)", (unit_id,))
        conn.execute(
            "INSERT INTO unit_staff(unit_id,user_id,role) VALUES(?,?,'admin')",
            (unit_id, g.user["id"]),
        )
        conn.execute(
            "INSERT INTO unit_branding(unit_id,description) VALUES(?,?)",
            (
                unit_id,
                "DEMO · 48 fictional members. Editable sample content; no game servers or login credentials.",
            ),
        )

        def reference(kind, title, category, role, body, slots):
            reference_id = conn.execute(
                "INSERT INTO unit_references(unit_id,kind,title,category,role,body,slots,updated_by,updated_at,folder,status) VALUES(?,?,?,?,?,?,?,?,?,?,'published')",
                (
                    unit_id,
                    kind,
                    title,
                    category,
                    role,
                    body,
                    json.dumps(slots),
                    "Demo setup",
                    now,
                    "Demo / " + category,
                ),
            ).lastrowid
            saved = dict(
                conn.execute(
                    "SELECT * FROM unit_references WHERE id=? AND unit_id=?",
                    (reference_id, unit_id),
                ).fetchone()
            )
            saved.pop("published_value", None)
            saved["file_tokens"] = []
            conn.execute(
                "UPDATE unit_references SET published_value=? WHERE id=? AND unit_id=?",
                (json.dumps(saved), reference_id, unit_id),
            )
            audit(
                conn,
                unit_id,
                "reference",
                reference_id,
                "published",
                None,
                saved,
                "Fictional demo reference",
            )

        first_member_id = conn.execute(
            "SELECT coalesce(max(id),0)+1 FROM (SELECT id FROM unit_roster UNION ALL SELECT id FROM unit_roster_deleted_ids)"
        ).fetchone()[0]
        type_ids = {}

        def node(title, kind, parent=None, callsign=""):
            type_id = None
            if kind == "billet":
                if title not in type_ids:
                    type_ids[title] = conn.execute(
                        "INSERT INTO unit_billet_types(unit_id,name) VALUES(?,?)",
                        (unit_id, title),
                    ).lastrowid
                type_id = type_ids[title]
            order = conn.execute(
                "SELECT coalesce(max(sort_order),-1)+1 FROM unit_structure WHERE unit_id=? AND parent_id IS ?",
                (unit_id, parent),
            ).fetchone()[0]
            return conn.execute(
                "INSERT INTO unit_structure(unit_id,parent_id,kind,name,sort_order,billet_type_id,callsign) VALUES(?,?,?,?,?,?,?)",
                (unit_id, parent, kind, title, order, type_id, callsign),
            ).lastrowid

        first = [
            "Alex",
            "Morgan",
            "Jordan",
            "Taylor",
            "Casey",
            "Riley",
            "Jamie",
            "Avery",
            "Cameron",
            "Drew",
            "Robin",
            "Quinn",
        ]
        last = [
            "Ashford",
            "Beckett",
            "Calder",
            "Dalton",
            "Ellery",
            "Finch",
            "Grayson",
            "Hale",
            "Irwin",
            "Jensen",
            "Keene",
            "Lennox",
            "Marlow",
            "Nolan",
            "Oakley",
            "Prescott",
            "Rowan",
            "Sutton",
            "Thorne",
            "Vale",
            "Weston",
            "Yarrow",
            "Briar",
            "Mercer",
        ]
        members = []

        def member(
            parent,
            title=None,
            callsign="",
            rank_name="Pfc",
            track="Enlisted",
            leadership=False,
            medic=False,
        ):
            i = len(members)
            game_name = f"{first[i%len(first)]} {last[i//2]}"
            certs = (
                ["Basic training"]
                + (["Leadership", "Radio operator"] if leadership else [])
                + (["Medical"] if medic else [])
                + (["Support weapons"] if i % 7 == 0 else [])
            )
            status = "loa" if i >= 45 else "reserve" if i >= 40 else "active"
            member_id = first_member_id + i
            conn.execute(
                "INSERT INTO unit_roster(id,unit_id,game_name,discord,status,rank,rank_track,certificates,joined_on,last_promo,loa_from,loa_until,callsign,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    member_id,
                    unit_id,
                    game_name,
                    "demo-" + game_name.lower().replace(" ", "."),
                    status,
                    rank_name,
                    track,
                    ";".join(sorted(certs)),
                    (today - timedelta(days=240 + i)).isoformat(),
                    (today - timedelta(days=120 if i % 3 == 0 else 15)).isoformat(),
                    (today - timedelta(days=3)).isoformat() if status == "loa" else "",
                    (today + timedelta(days=10)).isoformat() if status == "loa" else "",
                    f"Nomad {i+1}" if i in (9, 30) else "",
                    "Fictional demonstration member. Safe to edit.",
                    now,
                    now,
                ),
            )
            if title:
                slot = node(title, "billet", parent, callsign)
                conn.execute(
                    "INSERT INTO unit_primary_slots VALUES(?,?,?)",
                    (unit_id, member_id, slot),
                )
            else:
                conn.execute(
                    "INSERT INTO unit_member_placements VALUES(?,?,?)",
                    (unit_id, member_id, parent),
                )
            record_change(
                conn,
                unit_id,
                member_id,
                None,
                dict(
                    history_reason="Fictional demo record created",
                    qualification_awarded_on=(today - timedelta(days=60)).isoformat(),
                    qualification_issuer="Demo training cadre",
                ),
            )
            if i % 6 == 0:
                conn.execute(
                    "INSERT INTO unit_member_notes(unit_id,member_id,author_id,author_name,created_at,note) VALUES(?,?,?,?,?,?)",
                    (
                        unit_id,
                        member_id,
                        g.user["id"],
                        "Demo training cadre",
                        now,
                        "Sample staff note: completed orientation; review qualifications and promotion readiness at the next staff meeting.",
                    ),
                )
            members.append(member_id)

        company = node("Company", "group")
        hq = node("Company HQ", "section", company)
        member(hq, "Company Commander", "Atlas 6", "Capt", "Officer", True)
        member(hq, "Executive Officer", "Atlas 5", "1st Lt", "Officer", True)
        member(hq, "Company First Sergeant", "Atlas 7", "1st Sgt", leadership=True)
        member(hq, "Company Medic", "Atlas Doc", "HM2", "Medical", medic=True)
        node("Supply Sergeant", "billet", hq, "Atlas 4")
        for platoon_number in (1, 2):
            platoon = node(f"{platoon_number} Platoon", "section", company)
            plt_hq = node("Platoon HQ", "section", platoon)
            prefix = f"Atlas {platoon_number}"
            member(plt_hq, "Platoon Leader", prefix + "-6", "2nd Lt", "Officer", True)
            member(plt_hq, "Platoon Sergeant", prefix + "-7", "SSgt", leadership=True)
            member(plt_hq, "Radio Operator", prefix + "-R", "Cpl", leadership=True)
            member(
                plt_hq, "Platoon Medic", prefix + "-Doc", "HM3", "Medical", medic=True
            )
            node("Forward Observer", "billet", plt_hq, prefix + "-FO")
            for squad_number in (1, 2):
                squad = node(f"{squad_number} Squad", "section", platoon)
                member(
                    squad,
                    "Squad Leader",
                    f"{prefix}-{squad_number}",
                    "Sgt",
                    leadership=True,
                )
                for team_name in ("Alpha", "Bravo"):
                    team = node(team_name + " Team", "section", squad)
                    member(
                        team,
                        "Team Leader",
                        f"{prefix}-{squad_number}-{team_name[0]}",
                        "Cpl",
                        leadership=True,
                    )
                    for _ in range(3):
                        member(
                            team, rank_name="Pvt" if len(members) % 3 == 0 else "Pfc"
                        )
        # All examples are visible through the normal published-resource reader.
        sops = [
            (
                "Welcome to the demo",
                "Orientation",
                "Start here",
                "This is an editable fictional company. Explore the roster, open member records and try assignments. No game servers or login accounts are created.\n\n## Try these workflows\n- Fill an open billet.\n- Move a member to a different team.\n- Edit a slot callsign and view its occupant.\n- Review a promotion or qualification.\n- Create a Member login from a record to explore the read-only roster.",
            ),
            (
                "Member conduct and session safety",
                "Administration",
                "Conduct",
                "Treat others respectfully. Follow the session host’s instructions. Report technical or conduct issues to staff privately.\n\n## Before a session\n1. Check the event briefing.\n2. Confirm your assigned role and required resources.\n3. Tell staff if you need assistance.",
            ),
            (
                "Radio callsign guide",
                "Communications",
                "Radio operator",
                "This sample company uses Atlas as its callsign prefix. Slot callsigns are inherited by their occupants unless a personal override is set.\n\n## Example\nAtlas 1-6 is the first platoon leader. Callsigns should be unique within the session. Check the roster before using the radio.",
            ),
            (
                "Attendance and leave requests",
                "Administration",
                "Attendance",
                "Attendance is collected only during tracked events. Demo members have no real UUIDs, so they do not generate automatic attendance.\n\n## Leave\nAsk staff to record an LOA date range. Dates are inclusive. RSVPs express intent and do not mark you present.",
            ),
            (
                "Promotion review checklist",
                "Personnel",
                "Leadership",
                "Rank changes require staff approval. Meeting a time requirement never promotes a member automatically.\n\n## Review\n- Verify the last promotion date.\n- Check the next rank’s time and qualification requirements.\n- Add a review note before approving.",
            ),
            (
                "Equipment readiness checklist",
                "Training",
                "Basic training",
                "These sample loadouts are reference documents, not equipment applied to a game server.\n\n## Readiness\n- Read the role’s kit reference.\n- Use equipment approved by the event host.\n- Report missing items before the session starts.",
            ),
        ]
        for title, category, role, body in sops:
            reference(
                "sop",
                title,
                category,
                role,
                "# "
                + title
                + "\n\n> DEMO CONTENT — replace with your unit’s policy.\n\n"
                + body,
                [],
            )
        for role in (
            "Rifleman",
            "Team Leader",
            "Squad Leader",
            "Platoon Leader",
            "Medic",
            "Support Gunner",
        ):
            slots = [
                dict(
                    slot="Uniform",
                    standard="Unit-approved uniform and protective equipment",
                    alternatives="",
                    notes="Example only; follow event requirements.",
                ),
                dict(
                    slot="Primary equipment",
                    standard=(
                        "Medical kit"
                        if role == "Medic"
                        else "Unit-approved primary weapon"
                    ),
                    alternatives="",
                    notes="Choose actual Workshop equipment for your real unit.",
                ),
                dict(
                    slot="Radio",
                    standard=(
                        "Personal radio"
                        if role == "Rifleman"
                        else "Role-appropriate radio"
                    ),
                    alternatives="",
                    notes="Use the roster callsign.",
                ),
                dict(
                    slot="Supplies",
                    standard="Role-appropriate ammunition and medical supplies",
                    alternatives="",
                    notes="Confirm quantities with the session host.",
                ),
            ]
            reference(
                "loadout",
                role + " — Sample Kit",
                "Role kits",
                role,
                "DEMO reference only. These examples do not install mods or apply a kit in game.",
                slots,
            )
        conn.execute(
            "INSERT INTO unit_member_announcements(unit_id,title,body,pinned,author,updated_at) VALUES(?,?,?,?,?,?)",
            (
                unit_id,
                "Welcome to the demo company",
                "48 fictional members, three open billets, six SOPs and six sample kits. Edit freely inside this unit. No servers or login credentials were created.",
                1,
                "Demo setup",
                now,
            ),
        )
        record_strength(conn, unit_id, baseline=True)
        return unit_id
