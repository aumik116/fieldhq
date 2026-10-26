"""Runtime regression coverage for published resources and member self-service."""

from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import shutil
import sys
import unittest
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_panel


class UnitSelfServiceTests(unittest.TestCase):
    login = test_panel.PanelTests.login
    post = test_panel.PanelTests.post

    def setUp(self):
        test_panel.PanelTests.setUp(self)
        source = Path(__file__).resolve().parents[1]
        for name in ("units.html", "servers.html", "index.html"):
            shutil.copy(source / name, self.root / name)
        shutil.copytree(source / "static", self.root / "static")
        self.unit = self.new_unit("Alpha")
        self.other = self.new_unit("Bravo")

    def new_unit(self, name):
        result = self.post(
            self.admin, "/api/units", dict(name=name, tag=name[0], servers=[""])
        )
        self.assertEqual(result.status_code, 200, result.json)
        return result.json["id"]

    def detail(self, unit=None, client=None):
        return (client or self.admin).get(f"/api/units/{unit or self.unit}").json

    def change(self, path, data, unit=None, client=None):
        unit = unit or self.unit
        client = client or self.admin
        return self.post(
            client,
            f"/api/units/{unit}/{path}",
            dict(data, revision=self.detail(unit)["unit"]["revision"]),
        )

    def member_login(self, username="member-one", role="member", unit=None):
        unit = unit or self.unit
        result = self.change(
            "roster",
            dict(
                game_name=username,
                status="active",
                notes="PRIVATE STAFF NOTES",
                discord="example-user",
            ),
            unit=unit,
        )
        self.assertEqual(result.status_code, 200, result.json)
        member_id = result.json["id"]
        result = self.change(
            "staff",
            dict(
                username=username,
                role=role,
                create_account=True,
                password="test-password",
                link_member_id=member_id,
            ),
            unit=unit,
        )
        self.assertEqual(result.status_code, 200, result.json)
        return self.login(username), member_id

    def sop(self, **changes):
        data = dict(
            kind="sop",
            title="Procedure",
            category="General",
            body="# Purpose\nPublished guidance",
            status="published",
        )
        data.update(changes)
        response = self.change("library", data)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json["id"]

    def upload(self, data, files):
        payload = dict(
            kind="sop",
            title="Uploaded SOP",
            category="General",
            body="",
            status="draft",
            revision=self.detail()["unit"]["revision"],
        )
        payload.update(data)
        fields = {"data": json.dumps(payload)}
        for filename, contents in files:
            fields[uuid.uuid4().hex] = (io.BytesIO(contents), filename)
        return self.admin.post(
            f"/api/units/{self.unit}/library",
            data=fields,
            headers={"X-CSRF-Token": self.admin.get("/api/csrf").json["csrf"]},
        )

    def test_pdf_word_image_uploads_limits_and_private_files(self):
        member, _ = self.member_login()
        word = io.BytesIO()
        with zipfile.ZipFile(word, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
        response = self.upload(
            {},
            [
                ("manual.pdf", b"%PDF-1.4\nexample"),
                ("manual.docx", word.getvalue()),
                ("image.png", b"\x89PNG\r\n\x1a\nexample"),
            ],
        )
        self.assertEqual(response.status_code, 200, response.json)
        reference_id = response.json["id"]
        path = f"/api/units/{self.unit}/library/{reference_id}"
        document = self.admin.get(path).json
        self.assertEqual(len(document["files"]), 3)
        for file in document["files"]:
            url = f'/api/units/{self.unit}/library/files/{file["token"]}'
            response = self.admin.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            if not file["mime"].startswith("image/"):
                self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertEqual(member.get(url).status_code, 404)
        bad = self.upload({}, [("bad.pdf", b"not a PDF")])
        self.assertEqual(bad.status_code, 400)
        too_big = self.upload(
            {}, [("large.png", b"\x89PNG\r\n\x1a\n" + b"x" * (4 * 1024 * 1024))]
        )
        self.assertEqual(too_big.status_code, 400)
        self.assertEqual(
            len(self.admin.get(f"/api/units/{self.unit}/library").json["items"]), 1
        )
        self.assertEqual(
            self.admin.post(
                f"/api/units/{self.unit}/library", data={"data": "{}"}
            ).status_code,
            403,
        )

    def test_draft_attachment_is_not_exposed_through_published_copy(self):
        member, _ = self.member_login()
        first = self.upload(
            dict(status="published"), [("first.pdf", b"%PDF-1.4 first")]
        )
        self.assertEqual(first.status_code, 200, first.json)
        reference = first.json["id"]
        path = f"/api/units/{self.unit}/library/{reference}"
        original = member.get(path).json["files"]
        self.assertEqual(len(original), 1)
        changed = self.upload(dict(id=reference), [("draft.pdf", b"%PDF-1.4 draft")])
        self.assertEqual(changed.status_code, 200, changed.json)
        working = self.admin.get(path).json["files"]
        new = next(f for f in working if f["token"] != original[0]["token"])
        self.assertEqual(len(member.get(path).json["files"]), 1)
        self.assertEqual(
            member.get(
                f'/api/units/{self.unit}/library/files/{new["token"]}'
            ).status_code,
            404,
        )
        self.sop(id=reference, body="Updated publication")
        self.assertEqual(len(member.get(path).json["files"]), 2)
        self.assertEqual(
            member.get(
                f'/api/units/{self.unit}/library/files/{new["token"]}'
            ).status_code,
            200,
        )

    def test_template_copy_keeps_private_files_and_distinct_attachment_ids(self):
        member, _ = self.member_login()
        template = self.upload(
            dict(status="template", title="Template"),
            [("reference.pdf", b"%PDF-1.4 reference")],
        )
        self.assertEqual(template.status_code, 200, template.json)
        source = template.json["id"]
        path = f"/api/units/{self.unit}/library"
        original = self.admin.get(path + f"/{source}").json["files"][0]
        clone = self.change(
            "library",
            dict(
                kind="sop",
                title="From template",
                category="General",
                body="",
                template_id=source,
                status="draft",
            ),
        )
        self.assertEqual(clone.status_code, 200, clone.json)
        copied = self.admin.get(path + f'/{clone.json["id"]}').json["files"][0]
        self.assertNotEqual(original["token"], copied["token"])
        self.assertEqual(original["size"], copied["size"])
        self.assertEqual(member.get(path + f"/{source}").status_code, 404)
        self.assertEqual(member.get(path + f'/{clone.json["id"]}').status_code, 404)

    def test_published_copy_drafts_revisions_restore_and_related_isolation(self):
        member, _ = self.member_login()
        reference = self.sop()
        path = f"/api/units/{self.unit}/library/{reference}"
        published = member.get(path).json["item"]["body"]
        self.sop(id=reference, body="# Secret draft", status="draft")
        self.assertEqual(member.get(path).json["item"]["body"], published)
        self.assertEqual(self.admin.get(path).json["item"]["body"], "# Secret draft")
        self.assertNotIn(
            "Secret draft", member.get(f"/api/units/{self.unit}/library?q=Secret").text
        )
        history = self.admin.get(path).json["history"]
        self.assertEqual(
            member.get(path + f'/versions/{history[0]["id"]}').status_code, 403
        )
        first = history[-1]["id"]
        version = self.admin.get(path + f"/versions/{first}").json
        self.assertEqual(version["item"]["body"], published)
        restore = self.post(
            self.admin,
            path + f"/versions/{first}/restore",
            dict(revision=self.detail()["unit"]["revision"]),
        )
        self.assertEqual(restore.status_code, 200, restore.json)
        self.assertEqual(self.admin.get(path).json["item"]["status"], "draft")
        self.assertEqual(member.get(path).json["item"]["body"], published)
        foreign = self.change(
            "library",
            dict(
                kind="sop",
                title="Foreign",
                category="General",
                body="Other unit",
                status="published",
            ),
            unit=self.other,
        ).json["id"]
        invalid = self.change(
            "library",
            dict(
                kind="sop",
                title="Bad link",
                category="General",
                body="Text",
                related=[dict(kind="sop", id=foreign)],
            ),
        )
        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(
            member.get(f"/api/units/{self.other}/library").status_code, 404
        )
        self.assertEqual(
            member.get(f"/api/units/{self.other}/member-home").status_code, 404
        )

    def test_member_profile_and_staff_account_creation_are_scoped(self):
        administrator, _ = self.member_login("unit-admin", "admin")
        result = self.change(
            "staff",
            dict(
                username="created-by-unit",
                role="member",
                create_account=True,
                password="test-password",
            ),
            client=administrator,
        )
        self.assertEqual(result.status_code, 200, result.json)
        new_member = self.login("created-by-unit")
        self.assertEqual(new_member.get("/").location, "/units")
        self.assertFalse(new_member.get("/api/units").json["hosting_access"])
        self.assertIsNone(
            new_member.get(f"/api/units/{self.unit}/my-profile").json["member"]
        )
        member, member_id = self.member_login()
        for endpoint in (
            "roster.csv",
            "roster-tools",
            f"roster/{member_id}/record",
            "attendance",
            "analytics",
            "health",
        ):
            self.assertEqual(
                member.get(f"/api/units/{self.unit}/{endpoint}").status_code,
                403,
                endpoint,
            )
        detail = self.detail(client=member)
        self.assertEqual(detail["roster"], [])
        profile = member.get(f"/api/units/{self.unit}/my-profile")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json["member"]["game_name"], "member-one")
        self.assertNotIn("notes", profile.json["member"])
        self.assertNotIn("PRIVATE STAFF NOTES", profile.text)
        self.assertEqual(
            self.change(
                "staff",
                dict(
                    username="illegal",
                    role="admin",
                    create_account=True,
                    password="test-password",
                ),
                client=member,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.change(
                "staff",
                dict(
                    username="other-unit",
                    role="member",
                    create_account=True,
                    password="test-password",
                ),
                unit=self.other,
                client=administrator,
            ).status_code,
            404,
        )

    def test_required_reading_acks_match_current_published_version(self):
        member, _ = self.member_login()
        reference = self.sop()
        path = f"/api/units/{self.unit}/library/{reference}"
        result = self.change(
            f"library/{reference}/rules",
            dict(targets=[dict(kind="all")], review_on="2030-01-01"),
        )
        self.assertEqual(result.status_code, 200, result.json)
        home = member.get(f"/api/units/{self.unit}/member-home").json
        assignment = home["reading"][0]
        self.assertIsNone(assignment["acknowledged_at"])
        shown = member.get(path).json["acknowledgement"]
        self.assertEqual(shown["publication"], assignment["publication"])
        ack_path = f"/api/units/{self.unit}/reading/{reference}/acknowledge"
        self.assertEqual(
            self.post(
                member, ack_path, dict(publication=shown["publication"])
            ).status_code,
            200,
        )
        self.assertIsNotNone(
            member.get(f"/api/units/{self.unit}/member-home").json["reading"][0][
                "acknowledged_at"
            ]
        )
        self.sop(id=reference, body="New publication")
        self.assertEqual(
            self.post(
                member, ack_path, dict(publication=shown["publication"])
            ).status_code,
            409,
        )
        self.assertIsNone(
            member.get(f"/api/units/{self.unit}/member-home").json["reading"][0][
                "acknowledged_at"
            ]
        )
        self.assertEqual(member.get(path + "/rules").status_code, 403)
        progress = self.admin.get(path + "/rules").json["progress"]
        self.assertTrue(
            any(
                p["name"] == "member-one" and p["acknowledged_at"] is None
                for p in progress
            )
        )

    def test_reading_targets_match_each_assigned_position_and_qualification(self):
        member, member_id = self.member_login()
        result = self.change(
            "catalog",
            dict(
                catalog=dict(
                    certificates=["First aid"],
                    positions=["Medic", "Leader"],
                    rank_structures=[],
                )
            ),
        )
        self.assertEqual(result.status_code, 200, result.json)
        row = next(r for r in self.detail()["roster"] if r["id"] == member_id)
        row.update(position="Medic;Leader", certificates="First aid", archived=False)
        saved = self.change("roster", row)
        self.assertEqual(saved.status_code, 200, saved.json)
        reference = self.sop()
        for audience in (
            dict(kind="position", name="Medic"),
            dict(kind="position", name="Leader"),
            dict(kind="qualification", name="First aid"),
        ):
            result = self.change(f"library/{reference}/rules", dict(targets=[audience]))
            self.assertEqual(result.status_code, 200, result.json)
            home = member.get(f"/api/units/{self.unit}/member-home").json
            self.assertEqual([r["id"] for r in home["reading"]], [reference], audience)

    def test_rsvp_never_changes_attendance_and_event_edits_invalidate_it(self):
        member, member_id = self.member_login()
        start = datetime.now(timezone.utc) + timedelta(hours=2)
        event = self.change(
            "events",
            dict(
                name="Operation",
                timezone="UTC",
                starts=start.strftime("%Y-%m-%dT%H:%M"),
                duration=60,
                server_id="",
                tracked=True,
                briefing="Public briefing",
            ),
        )
        self.assertEqual(event.status_code, 200, event.json)
        home_path = f"/api/units/{self.unit}/member-home"
        current = member.get(home_path).json["events"][0]
        path = f'/api/units/{self.unit}/member-events/{current["id"]}/rsvp'
        result = self.post(
            member, path, dict(answer="attending", version=current["version"])
        )
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(member.get(home_path).json["events"][0]["rsvp"], "attending")
        self.assertNotIn("responses", member.get(home_path).json["events"][0])
        self.assertEqual(
            self.admin.get(home_path).json["events"][0]["responses"][0]["game_name"],
            "member-one",
        )
        with self.module.operator_tools.store.connect() as conn:
            saved = conn.execute(
                "SELECT outcome,expected FROM unit_event_members WHERE event_id=? AND member_id=?",
                (current["id"], member_id),
            ).fetchone()
            self.assertIsNone(saved["outcome"])
            self.assertEqual(saved["expected"], 1)
            conn.execute(
                "UPDATE unit_events SET version=version+1 WHERE id=?", (current["id"],)
            )
        self.assertIsNone(member.get(home_path).json["events"][0]["rsvp"])
        self.assertEqual(
            self.post(
                member, path, dict(answer="attending", version=current["version"])
            ).status_code,
            409,
        )
        outsider, _ = self.member_login("outsider", unit=self.other)
        self.assertEqual(
            self.post(
                outsider, path, dict(answer="attending", version=current["version"] + 1)
            ).status_code,
            404,
        )

    def test_announcements_and_review_reminders_obey_member_privacy(self):
        member, _ = self.member_login()
        announcement = self.change(
            "announcements", dict(title="Notice", body="Read the SOP", pinned=True)
        )
        self.assertEqual(announcement.status_code, 200, announcement.json)
        reference = self.sop()
        rules = self.change(
            f"library/{reference}/rules",
            dict(targets=[], reviewed_on="2020-01-01", review_on="2020-02-01"),
        )
        self.assertEqual(rules.status_code, 200, rules.json)
        home = member.get(f"/api/units/{self.unit}/member-home").json
        self.assertEqual(home["announcements"][0]["title"], "Notice")
        self.assertEqual(home["reviews"], [])
        self.assertEqual(home["announcement_history"], [])
        self.assertFalse(home["can_manage"])
        self.assertEqual(
            self.admin.get(f"/api/units/{self.unit}/member-home").json["review_due"], 1
        )
        self.assertEqual(
            self.change(
                "announcements", dict(title="Forbidden", body="No"), client=member
            ).status_code,
            403,
        )

    def test_http_login_cookie_session_and_published_resource(self):
        import http.cookiejar
        import threading
        import urllib.error
        import urllib.request
        from werkzeug.serving import WSGIRequestHandler, make_server

        self.member_login()
        reference = self.sop()

        class QuietHandler(WSGIRequestHandler):
            def log_request(self, *args, **kwargs):
                pass

        server = make_server(
            "127.0.0.1", 0, self.module.app, request_handler=QuietHandler
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        try:
            login = urllib.request.Request(
                base + "/login",
                data=json.dumps(
                    dict(username="member-one", password="test-password")
                ).encode(),
                headers={"Content-Type": "application/json"},
            )
            with opener.open(login, timeout=5) as response:
                self.assertTrue(json.load(response)["ok"])
            with opener.open(base + "/units", timeout=5) as response:
                self.assertIn("unit-sidebar", response.read().decode())
            with opener.open(
                base + f"/api/units/{self.unit}/library/{reference}", timeout=5
            ) as response:
                self.assertEqual(json.load(response)["item"]["title"], "Procedure")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                opener.open(base + f"/api/units/{self.other}/library", timeout=5)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_navigation_pages_and_deployed_script_assets(self):
        member, _ = self.member_login()
        units = member.get("/units")
        self.addCleanup(units.close)
        self.assertEqual(units.status_code, 200)
        self.assertIn('id="unit-sidebar"', units.text)
        self.assertNotIn("unit-nav-groups", units.text)
        self.assertEqual(member.get("/servers").location, "/units")
        landing = self.admin.get("/servers")
        self.addCleanup(landing.close)
        self.assertEqual(landing.status_code, 200)
        self.assertNotIn('id="fleet-sidebar"', landing.text)
        self.assertIn('id="overview-alerts"', landing.text)
        for name in (
            "unit-ux.js",
            "units.js",
            "unit-resources.js",
            "unit-members.js",
            "panel.css",
        ):
            with self.admin.get("/static/" + name + "?v=cleanup-2") as response:
                self.assertEqual(response.status_code, 200, name)


if __name__ == "__main__":
    unittest.main()
