"""Unit-scoped Member access management; shared credentials stay panel-managed."""

import bcrypt
from flask import abort, g, jsonify, request


def install(api, db, access, revision, endpoints, find_member, panel_admin):
    name = "unit_member_login_manage"
    endpoints.add(name)
    api.PANEL_WIDE_ENDPOINTS.add(name)
    from panel_features import MUTATIONS

    MUTATIONS[name] = "view"

    @api.app.post("/api/units/<int:unit_id>/roster/<int:member_id>/login/manage")
    def unit_member_login_manage(unit_id, member_id):
        try:
            data = request.get_json()
            action = data.get("action")
            if action not in ("reset", "disable", "enable"):
                raise ValueError("Choose reset, disable or enable")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "staff")
                revision(conn, unit_id, data)
                member = find_member(conn, unit_id, member_id)
                user_id = member["panel_user_id"]
                if user_id is None:
                    raise ValueError("This member has no linked login")
                membership = conn.execute(
                    "SELECT role FROM unit_staff WHERE unit_id=? AND user_id=?",
                    (unit_id, user_id),
                ).fetchone()
                if not membership or membership["role"] != "member":
                    raise ValueError(
                        "Use Accounts & access to manage Staff or administrator memberships"
                    )
                if action == "disable":
                    conn.execute(
                        "INSERT OR IGNORE INTO unit_account_suspensions VALUES(?,?)",
                        (unit_id, user_id),
                    )
                elif action == "enable":
                    conn.execute(
                        "DELETE FROM unit_account_suspensions WHERE unit_id=? AND user_id=?",
                        (unit_id, user_id),
                    )
                else:
                    user = conn.execute(
                        "SELECT * FROM users WHERE id=?", (user_id,)
                    ).fetchone()
                    shared = conn.execute(
                        "SELECT 1 FROM unit_staff WHERE user_id=? AND unit_id!=?",
                        (user_id, unit_id),
                    ).fetchone()
                    hosting = conn.execute(
                        "SELECT 1 FROM user_server_roles WHERE user_id=? LIMIT 1",
                        (user_id,),
                    ).fetchone()
                    if not panel_admin() and (
                        shared
                        or hosting
                        or user["panel_admin"]
                        or user["access_all"]
                        or conn.execute(
                            "SELECT 1 FROM panel_owner WHERE user_id=?", (user_id,)
                        ).fetchone()
                    ):
                        abort(
                            403,
                            description="Ask a panel administrator to reset this shared or hosting account",
                        )
                    password = data.get("password")
                    if (
                        not isinstance(password, str)
                        or len(password) < 10
                        or len(password.encode()) > 72
                    ):
                        raise ValueError(
                            "Use at least 10 characters and at most 72 UTF-8 bytes"
                        )
                    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                    conn.execute(
                        "UPDATE users SET password=?,version=version+1 WHERE id=?",
                        (hashed, user_id),
                    )
            g.audit_details = dict(
                unit_id=unit_id, member_id=member_id, user_id=user_id, action=action
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
