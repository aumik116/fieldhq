"""Platform workspace: existing administrator rights, independent of hosting."""

import json
from flask import abort, jsonify, request, send_from_directory


def install(api, db, panel_admin, endpoints):
    names = {"platform_admin_page", "platform_summary", "platform_activity"}
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)

    def require_admin():
        if not panel_admin():
            abort(
                403,
                description="Only platform administrators can access Platform Admin",
            )

    @api.app.get("/admin")
    def platform_admin_page():
        require_admin()
        return send_from_directory(api._BASE_DIR, "users.html")

    @api.app.get("/api/platform/summary")
    def platform_summary():
        require_admin()
        with db() as conn:
            accounts = conn.execute("SELECT count(*) FROM users").fetchone()[0]
            units = conn.execute("SELECT count(*) FROM units").fetchone()[0]
            owner = conn.execute(
                "SELECT username FROM users JOIN panel_owner p ON p.user_id=users.id"
            ).fetchone()
        return jsonify(
            accounts=accounts,
            units=units,
            servers=len(api.server_registry.list()) + (0 if api.manager_mode else 1),
            mode="Managed hosting" if api.manager_mode else "Single server",
            port=api.PANEL_PORT,
            owner=owner["username"] if owner else "",
        )

    @api.app.get("/api/platform/activity")
    def platform_activity():
        require_admin()
        value = request.args.get("before", "0")
        if (
            not value.isascii()
            or not value.isdecimal()
            or len(value) > 19
            or int(value) > 9223372036854775807
        ):
            abort(400, description="Choose a valid activity cursor")
        before = int(value)
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM activity WHERE (?=0 OR id<?) ORDER BY id DESC LIMIT 51",
                (before, before),
            ).fetchall()
        return jsonify(
            events=[dict(row, details=json.loads(row["details"])) for row in rows[:50]],
            next_before=rows[49]["id"] if len(rows) > 50 else None,
        )
