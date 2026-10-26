"""Shared unit identity, role checks and reference serialization."""

from datetime import date
import hashlib
import json
import re
import time
from urllib.parse import urlsplit

from flask import abort, g

UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

STAFF_CAPABILITIES = (
    "roster",
    "events",
    "attendance",
    "references",
    "awards",
    "campaigns",
)
CAPABILITIES = STAFF_CAPABILITIES + ("staff",)


def unit_role_capabilities(role):
    return (
        CAPABILITIES
        if role == "admin"
        else STAFF_CAPABILITIES if role == "staff" else ()
    )


def text(value, name, limit=120, required=False):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise ValueError(f"{name}: use text up to {limit} characters")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name} is required")
    return value


def actor(conn, unit_id):
    row = conn.execute(
        "SELECT game_name FROM unit_roster WHERE unit_id=? AND panel_user_id=?",
        (unit_id, g.user["id"]),
    ).fetchone()
    return row["game_name"] if row else g.user["username"]


def get_row(conn, table, unit_id, object_id):
    if type(object_id) is not int or not 1 <= object_id <= 9223372036854775807:
        raise ValueError("Choose a valid record")
    row = conn.execute(
        f"SELECT * FROM {table} WHERE unit_id=? AND id=?", (unit_id, object_id)
    ).fetchone()
    if not row:
        abort(404, description="Record not found in this unit")
    return dict(row)


def url(value, label):
    value = text(value, label, 2000)
    if value:
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in ("https", "http")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or any(c.isspace() for c in value)
            ):
                raise ValueError()
        except ValueError:
            raise ValueError(
                f"{label}: use an HTTP or HTTPS address without embedded credentials"
            ) from None
    return value


def number(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}: choose a whole number from {low} to {high}")
    return value


def archive(data):
    if type(data.get("archived", False)) is not bool:
        raise ValueError("Archived must be true or false")
    return int(data.get("archived", False))


def audit(
    conn, unit_id, kind, object_id, action, before, after, reason="", member_id=None
):
    conn.execute(
        "INSERT INTO unit_resource_audit(unit_id,object_kind,object_id,member_id,actor,created_at,action,before_value,after_value,reason) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            unit_id,
            kind,
            object_id,
            member_id,
            actor(conn, unit_id),
            time.time(),
            action,
            json.dumps(before),
            json.dumps(after),
            reason,
        ),
    )


def role(conn, unit_id):
    row = conn.execute(
        "SELECT role FROM unit_staff WHERE unit_id=? AND user_id=?",
        (unit_id, g.user["id"]),
    ).fetchone()
    return row["role"] if row else None


def can(conn, unit_id, capability, panel_admin):
    return panel_admin() or capability in unit_role_capabilities(role(conn, unit_id))


def permissions(conn, unit_id, panel_admin):
    capabilities = (
        CAPABILITIES if panel_admin() else unit_role_capabilities(role(conn, unit_id))
    )
    return {key: key in capabilities for key in ("references", "awards", "campaigns")}


def is_member(conn, unit_id, panel_admin):
    return not panel_admin() and role(conn, unit_id) == "member"


def publication_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def decode_reference(row):
    item = dict(row)
    item.pop("published_value", None)
    item["slots"] = json.loads(item["slots"])
    return item


def roster_status(member, on=None):
    """LOA dates are inclusive; undated legacy LOA remains indefinite."""
    day = on or date.today().isoformat()
    if member["status"] != "loa":
        return member["status"]
    start = member["loa_from"] if "loa_from" in member.keys() else ""
    end = member["loa_until"]
    return "active" if (start and day < start) or (end and day > end) else "loa"


def effective_certificates(conn, unit_id, member, on=None):
    """Recorded awards remain in history; only date-valid awards satisfy requirements."""
    day = on or date.today().isoformat()
    awards = {
        row["certificate"]: row
        for row in conn.execute(
            "SELECT * FROM unit_qualification_awards WHERE unit_id=? AND member_id=?",
            (unit_id, member["id"]),
        )
    }
    return [
        name
        for name in member["certificates"].split(";")
        if name
        and (
            name not in awards
            or (
                (not awards[name]["awarded_on"] or awards[name]["awarded_on"] <= day)
                and (
                    not awards[name]["expires_on"] or awards[name]["expires_on"] >= day
                )
            )
        )
    ]
