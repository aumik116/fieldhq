"""Single-use member invitations; account credentials remain in users."""

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time

import bcrypt
from flask import abort, g, jsonify, render_template_string, request, session


def install(api, db, access, endpoints, find_member):
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS unit_login_links (
                token_hash TEXT PRIMARY KEY, unit_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL, kind TEXT NOT NULL,
                user_id INTEGER, user_version INTEGER, issuer_id INTEGER NOT NULL,
                created_at REAL NOT NULL, expires_at REAL NOT NULL,
                invalidated INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS unit_login_links_member
                ON unit_login_links(unit_id,member_id,invalidated);
            CREATE TRIGGER IF NOT EXISTS unit_login_link_member_change
            AFTER UPDATE OF archived,panel_user_id ON unit_roster
            WHEN NEW.archived!=OLD.archived OR NEW.panel_user_id IS NOT OLD.panel_user_id
            BEGIN
                UPDATE unit_login_links SET invalidated=1 WHERE unit_id=OLD.unit_id AND member_id=OLD.id;
            END;
            CREATE TRIGGER IF NOT EXISTS unit_login_link_access_removed
            AFTER DELETE ON unit_staff
            BEGIN
                UPDATE unit_login_links SET invalidated=1 WHERE unit_id=OLD.unit_id AND
                    (issuer_id=OLD.user_id OR user_id=OLD.user_id);
            END;
            CREATE TRIGGER IF NOT EXISTS unit_login_link_suspended
            AFTER INSERT ON unit_account_suspensions
            BEGIN
                UPDATE unit_login_links SET invalidated=1 WHERE unit_id=NEW.unit_id AND
                    (issuer_id=NEW.user_id OR user_id=NEW.user_id);
            END;
            CREATE TRIGGER IF NOT EXISTS unit_login_link_account_changed
            AFTER UPDATE OF version,enabled ON users
            WHEN NEW.version!=OLD.version OR NEW.enabled!=OLD.enabled
            BEGIN
                UPDATE unit_login_links SET invalidated=1 WHERE issuer_id=OLD.id OR user_id=OLD.id;
            END;
            CREATE TRIGGER IF NOT EXISTS unit_login_link_member_deleted
            AFTER DELETE ON unit_roster
            BEGIN
                UPDATE unit_login_links SET invalidated=1 WHERE unit_id=OLD.unit_id AND member_id=OLD.id;
                INSERT OR IGNORE INTO unit_account_suspensions(unit_id,user_id)
                    SELECT OLD.unit_id,user_id FROM unit_staff
                    WHERE unit_id=OLD.unit_id AND user_id=OLD.panel_user_id AND role='member';
            END;
        """)

    names = {
        "unit_member_invite",
        "member_signup_page",
        "member_signup_info",
        "member_signup_accept",
        "member_invitations_list",
    }
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS

    MUTATIONS["unit_member_invite"] = "view"

    def digest(token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            abort(
                410,
                description="This link is invalid, expired or already used. Ask unit staff for a new link.",
            )
        return hashlib.sha256(token.encode()).hexdigest()

    def is_admin(conn, user):
        return user and bool(
            user["panel_admin"]
            or conn.execute(
                "SELECT 1 FROM panel_owner WHERE user_id=?", (user["id"],)
            ).fetchone()
        )

    def can_reset(conn, issuer, target, unit_id):
        owner = conn.execute(
            "SELECT user_id FROM panel_owner WHERE singleton=1"
        ).fetchone()
        if (
            owner
            and target["id"] == owner["user_id"]
            and issuer["id"] != owner["user_id"]
        ):
            return False
        if is_admin(conn, issuer):
            return True
        # Unit administrators cannot take over shared, elevated or hosting accounts.
        membership = conn.execute(
            "SELECT role FROM unit_staff WHERE unit_id=? AND user_id=?",
            (unit_id, target["id"]),
        ).fetchone()
        return bool(
            membership
            and membership["role"] == "member"
            and not target["panel_admin"]
            and not target["access_all"]
            and not conn.execute(
                "SELECT 1 FROM panel_owner WHERE user_id=?", (target["id"],)
            ).fetchone()
            and not conn.execute(
                "SELECT 1 FROM user_server_roles WHERE user_id=?", (target["id"],)
            ).fetchone()
            and not conn.execute(
                "SELECT 1 FROM unit_staff WHERE user_id=? AND unit_id!=?",
                (target["id"], unit_id),
            ).fetchone()
        )

    def audit(conn, actor, action, unit_id, member_id):
        conn.execute(
            "INSERT INTO activity(ts,actor,action,outcome,details) VALUES(?,?,?,?,?)",
            (
                time.time(),
                actor,
                action,
                "success",
                json.dumps(dict(unit_id=unit_id, member_id=member_id)),
            ),
        )

    def valid_link(conn, token):
        link = conn.execute(
            "SELECT * FROM unit_login_links WHERE token_hash=? AND invalidated=0 AND expires_at>?",
            (digest(token), time.time()),
        ).fetchone()
        if not link:
            abort(
                410,
                description="This link is invalid, expired or already used. Ask unit staff for a new link.",
            )
        member = conn.execute(
            "SELECT * FROM unit_roster WHERE id=? AND unit_id=? AND archived=0",
            (link["member_id"], link["unit_id"]),
        ).fetchone()
        issuer = conn.execute(
            "SELECT * FROM users WHERE id=? AND enabled=1", (link["issuer_id"],)
        ).fetchone()
        membership = conn.execute(
            "SELECT role FROM unit_staff WHERE unit_id=? AND user_id=?",
            (link["unit_id"], link["issuer_id"]),
        ).fetchone()
        suspended = conn.execute(
            "SELECT 1 FROM unit_account_suspensions WHERE unit_id=? AND user_id=?",
            (link["unit_id"], link["issuer_id"]),
        ).fetchone()
        if (
            not member
            or not issuer
            or not conn.execute(
                "SELECT 1 FROM units WHERE id=?", (link["unit_id"],)
            ).fetchone()
            or (
                not is_admin(conn, issuer)
                and (
                    suspended
                    or not membership
                    or membership["role"] not in ("staff", "admin")
                )
            )
        ):
            abort(
                410,
                description="This invitation is no longer available. Ask unit staff for a new link.",
            )
        if link["kind"] == "signup":
            if member["panel_user_id"] is not None:
                abort(
                    410,
                    description="This member already has a login. Sign in normally or ask staff for help.",
                )
        else:
            target = conn.execute(
                "SELECT * FROM users WHERE id=? AND enabled=1", (link["user_id"],)
            ).fetchone()
            if (
                not target
                or member["panel_user_id"] != target["id"]
                or target["version"] != link["user_version"]
                or not can_reset(conn, issuer, target, link["unit_id"])
                or (not is_admin(conn, issuer) and membership["role"] != "admin")
                or conn.execute(
                    "SELECT 1 FROM unit_account_suspensions WHERE unit_id=? AND user_id=?",
                    (link["unit_id"], target["id"]),
                ).fetchone()
                or not conn.execute(
                    "SELECT 1 FROM unit_staff WHERE unit_id=? AND user_id=?",
                    (link["unit_id"], target["id"]),
                ).fetchone()
            ):
                abort(
                    410,
                    description="This reset link is no longer available. Ask an administrator for help.",
                )
        return link, member

    def decorate(conn, members):
        pending = (
            {
                (row["unit_id"], row["member_id"]): row["expires"]
                for row in conn.execute(
                    "SELECT unit_id,member_id,max(expires_at) AS expires FROM unit_login_links WHERE invalidated=0 AND kind='signup' AND expires_at>? AND unit_id=? GROUP BY unit_id,member_id",
                    (time.time(), members[0]["unit_id"]),
                )
            }
            if members
            else {}
        )
        for member in members:
            expires = pending.get((member["unit_id"], member["id"]))
            member["invite_expires_at"] = expires
            member["login_status"] = (
                (
                    "disabled"
                    if member.get("unit_login_suspended")
                    or not member.get("panel_user_enabled")
                    else "active"
                )
                if member.get("panel_user_id")
                else "pending" if expires else "none"
            )

    api.decorate_member_invitations = decorate

    @api.app.get("/api/member-invitations")
    def member_invitations_list():
        if "users" not in g.panel_permissions:
            abort(403, description="Only panel administrators can view all invitations")
        unit = request.args.get("unit", "")
        query = request.args.get("q", "").strip()
        if len(query) > 120 or (unit and not re.fullmatch(r"[1-9][0-9]{0,17}", unit)):
            abort(
                400,
                description="Choose a valid unit and search of at most 120 characters",
            )
        with db() as conn:
            rows = conn.execute(
                """
                SELECT l.unit_id,l.member_id,l.created_at,l.expires_at,r.game_name,
                    u.name AS unit_name,issuer.username AS invited_by
                FROM unit_login_links l JOIN units u ON u.id=l.unit_id
                JOIN unit_roster r ON r.unit_id=l.unit_id AND r.id=l.member_id
                JOIN users issuer ON issuer.id=l.issuer_id
                WHERE l.kind='signup' AND l.invalidated=0 AND l.expires_at>?
                    AND r.archived=0 AND r.panel_user_id IS NULL AND issuer.enabled=1
                    AND (issuer.panel_admin=1 OR EXISTS(SELECT 1 FROM panel_owner WHERE user_id=issuer.id)
                        OR (EXISTS(SELECT 1 FROM unit_staff s WHERE s.unit_id=l.unit_id AND s.user_id=issuer.id AND s.role IN ('staff','admin'))
                            AND NOT EXISTS(SELECT 1 FROM unit_account_suspensions s WHERE s.unit_id=l.unit_id AND s.user_id=issuer.id)))
                    AND (?='' OR l.unit_id=?)
                    AND (instr(lower(r.game_name),lower(?))>0 OR instr(lower(u.name),lower(?))>0)
                ORDER BY l.expires_at,l.member_id LIMIT 501
                """,
                (time.time(), unit, unit, query, query),
            ).fetchall()
            units = [
                dict(row)
                for row in conn.execute(
                    "SELECT id,name FROM units ORDER BY name COLLATE NOCASE"
                )
            ]
        return jsonify(
            invitations=[dict(row) for row in rows[:500]],
            more=len(rows) > 500,
            units=units,
        )

    @api.app.post("/api/units/<int:unit_id>/roster/<int:member_id>/invite")
    def unit_member_invite(unit_id, member_id):
        data = request.get_json()
        action = data.get("action", "signup")
        if action not in ("signup", "reset", "revoke"):
            abort(400, description="Choose signup, reset or revoke")
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            access(conn, unit_id, "staff" if action == "reset" else "roster")
            member = find_member(conn, unit_id, member_id)
            if member["archived"]:
                abort(
                    400, description="Restore this member before managing login links"
                )
            user = conn.execute(
                "SELECT * FROM users WHERE id=?", (member["panel_user_id"],)
            ).fetchone()
            if action == "signup" and user:
                abort(409, description="This member already has a linked login")
            if action == "reset" and (
                not user
                or not user["enabled"]
                or not can_reset(conn, g.user, user, unit_id)
            ):
                abort(
                    403,
                    description="A panel administrator must manage password resets for shared, staff or hosting accounts",
                )
            if action == "reset" and (
                not conn.execute(
                    "SELECT 1 FROM unit_staff WHERE unit_id=? AND user_id=?",
                    (unit_id, user["id"]),
                ).fetchone()
                or conn.execute(
                    "SELECT 1 FROM unit_account_suspensions WHERE unit_id=? AND user_id=?",
                    (unit_id, user["id"]),
                ).fetchone()
            ):
                abort(
                    409,
                    description="Restore this account’s unit access before generating a reset link",
                )
            conn.execute(
                "UPDATE unit_login_links SET invalidated=1 WHERE unit_id=? AND member_id=?",
                (unit_id, member_id),
            )
            g.audit_details = dict(
                unit_id=unit_id, member_id=member_id, change="login link " + action
            )
            if action == "revoke":
                conn.execute(
                    "UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,)
                )
                return jsonify(ok=True)
            token = secrets.token_urlsafe(32)
            expires = time.time() + (86400 if action == "reset" else 7 * 86400)
            conn.execute(
                "INSERT INTO unit_login_links(token_hash,unit_id,member_id,kind,user_id,user_version,issuer_id,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    digest(token),
                    unit_id,
                    member_id,
                    action,
                    user["id"] if user else None,
                    user["version"] if user else None,
                    g.user["id"],
                    time.time(),
                    expires,
                ),
            )
            conn.execute("UPDATE units SET revision=revision+1 WHERE id=?", (unit_id,))
            # Fragment tokens never appear in HTTP paths, access logs or referrers.
            return jsonify(ok=True, path="/signup#" + token, expires_at=expires)

    @api.app.get("/signup")
    def member_signup_page():
        csrf = api._ensure_csrf()
        with open(
            os.path.join(api._BASE_DIR, "signup.html"), encoding="utf-8"
        ) as stream:
            response = api.app.make_response(
                render_template_string(stream.read(), csrf=csrf)
            )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    def public_body():
        if not api._login_rate_ok(request.endpoint + ":" + api._client_ip()):
            abort(429, description="Too many attempts. Wait a minute and try again.")
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, description="Send a valid signup form")
        error = api._csrf_required()
        if error:
            abort(
                403, description="Your session expired. Reload this page and try again."
            )
        return data

    @api.app.post("/api/signup/info")
    def member_signup_info():
        data = public_body()
        with db() as conn:
            link, member = valid_link(conn, data.get("token"))
            unit = conn.execute(
                "SELECT name FROM units WHERE id=?", (link["unit_id"],)
            ).fetchone()
            brand = conn.execute(
                "SELECT icon,icon_type FROM unit_branding WHERE unit_id=?",
                (link["unit_id"],),
            ).fetchone()
            icon = ""
            if (
                brand
                and brand["icon"]
                and brand["icon_type"] in ("image/png", "image/jpeg", "image/webp")
            ):
                icon = (
                    "data:"
                    + brand["icon_type"]
                    + ";base64,"
                    + base64.b64encode(brand["icon"]).decode()
                )
            return jsonify(
                kind=link["kind"],
                member=member["game_name"],
                unit=unit["name"],
                icon=icon,
                expires_at=link["expires_at"],
            )

    @api.app.post("/api/signup/accept")
    def member_signup_accept():
        data = public_body()
        mode = data.get("mode", "new")
        if mode not in ("new", "existing", "reset"):
            abort(400, description="Choose a signup option")
        existing = None
        hashed = None
        if mode == "existing":
            existing = api.authenticate_user(data.get("username"), data.get("password"))
            if not existing:
                abort(401, description="Invalid username or password")
        else:
            password = data.get("password")
            if (
                not isinstance(password, str)
                or len(password) < 10
                or len(password.encode()) > 72
            ):
                abort(
                    400,
                    description="Use at least 10 characters and at most 72 UTF-8 bytes",
                )
            if password != data.get("confirm_password"):
                abort(400, description="Passwords do not match")
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                link, member = valid_link(conn, data.get("token"))
                if link["kind"] == "reset":
                    if mode != "reset":
                        abort(400, description="Use this link to set a new password")
                    user_id = link["user_id"]
                    conn.execute(
                        "UPDATE users SET password=?,version=version+1 WHERE id=?",
                        (hashed, user_id),
                    )
                else:
                    if mode == "reset":
                        abort(
                            400,
                            description="Use this invitation to create or link an account",
                        )
                    if existing:
                        user_id = existing["id"]
                        live = conn.execute(
                            "SELECT * FROM users WHERE id=?", (user_id,)
                        ).fetchone()
                        if (
                            not live
                            or not live["enabled"]
                            or live["version"] != existing["version"]
                        ):
                            abort(409, description="Account changed. Sign in again.")
                        if conn.execute(
                            "SELECT 1 FROM unit_roster WHERE unit_id=? AND panel_user_id=?",
                            (link["unit_id"], user_id),
                        ).fetchone():
                            abort(
                                409,
                                description="This account is already linked to another member in this unit. Ask staff for help.",
                            )
                        if conn.execute(
                            "SELECT 1 FROM unit_account_suspensions WHERE unit_id=? AND user_id=?",
                            (link["unit_id"], user_id),
                        ).fetchone():
                            abort(
                                403,
                                description="Your access to this unit is disabled. Contact unit staff.",
                            )
                    else:
                        username = data.get("username", "")
                        if not isinstance(username, str) or not re.fullmatch(
                            r"[A-Za-z0-9_.-]{3,32}", username
                        ):
                            abort(
                                400,
                                description="Use a 3–32 character username: letters, numbers, _, . or -",
                            )
                        user_id = conn.execute(
                            "INSERT INTO users(username,password,role,enabled,access_all,panel_admin) VALUES(?,?,'viewer',1,0,0)",
                            (username, hashed),
                        ).lastrowid
                    conn.execute(
                        "INSERT OR IGNORE INTO unit_staff(unit_id,user_id,role,capabilities) VALUES(?,?,'member','[]')",
                        (link["unit_id"], user_id),
                    )
                    conn.execute(
                        "UPDATE unit_roster SET panel_user_id=?,updated_at=? WHERE unit_id=? AND id=?",
                        (user_id, time.time(), link["unit_id"], member["id"]),
                    )
                conn.execute(
                    "UPDATE unit_login_links SET invalidated=1 WHERE unit_id=? AND member_id=?",
                    (link["unit_id"], member["id"]),
                )
                conn.execute(
                    "UPDATE units SET revision=revision+1 WHERE id=?",
                    (link["unit_id"],),
                )
                conn.execute(
                    "UPDATE users SET last_login_at=? WHERE id=?",
                    (time.time(), user_id),
                )
                user = conn.execute(
                    "SELECT * FROM users WHERE id=?", (user_id,)
                ).fetchone()
                audit(
                    conn,
                    user["username"],
                    (
                        "member_reset_accepted"
                        if mode == "reset"
                        else "member_invite_accepted"
                    ),
                    link["unit_id"],
                    member["id"],
                )
            session.clear()
            session.permanent = True
            session.update(
                logged_in=True,
                user_id=user["id"],
                user_version=user["version"],
                login_at=int(time.time()),
            )
            api._ensure_csrf()
            return jsonify(ok=True, redirect=f"/units?unit={link['unit_id']}&tab=home")
        except sqlite3.IntegrityError:
            abort(
                409,
                description="That username or member link is already in use. Choose another username, or sign in to your existing account.",
            )
