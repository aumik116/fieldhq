"""Unit SOPs and loadouts: publishing, revisions and private attachments."""

from functools import partial
import io
import json
import re
import time
import uuid
import zipfile

from flask import abort, g, jsonify, request, send_file
from unit_common import (
    actor,
    archive,
    audit,
    decode_reference,
    get_row,
    is_member as unit_is_member,
    number,
    permissions as unit_permissions,
    publication_digest,
    text,
    url,
)


def install(api, db, access, revision, panel_admin, endpoints, required_reading):
    is_member = partial(unit_is_member, panel_admin=panel_admin)
    permissions = partial(unit_permissions, panel_admin=panel_admin)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS unit_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                kind TEXT NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '', image_url TEXT NOT NULL DEFAULT '',
                slots TEXT NOT NULL DEFAULT '[]', archived INTEGER NOT NULL DEFAULT 0,
                updated_by TEXT NOT NULL, updated_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_references_unit ON unit_references(unit_id,kind,archived,id);
            CREATE TABLE IF NOT EXISTS unit_reference_files (
                token TEXT PRIMARY KEY, unit_id INTEGER NOT NULL, reference_id INTEGER NOT NULL,
                filename TEXT NOT NULL, mime TEXT NOT NULL, content BLOB NOT NULL,
                created_by TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_reference_files_reference ON unit_reference_files(unit_id,reference_id);
        """
        )

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        columns = {
            r["name"] for r in conn.execute("PRAGMA table_info(unit_references)")
        }
        for name, definition in (
            ("folder", "TEXT NOT NULL DEFAULT ''"),
            ("status", "TEXT NOT NULL DEFAULT 'published'"),
            ("published_value", "TEXT NOT NULL DEFAULT ''"),
            ("related", "TEXT NOT NULL DEFAULT '[]'"),
            ("file_tokens", "TEXT NOT NULL DEFAULT '[]'"),
        ):
            if name not in columns:
                conn.execute(
                    f"ALTER TABLE unit_references ADD COLUMN {name} {definition}"
                )
        if "file_tokens" not in columns:
            for row in conn.execute(
                "SELECT id,unit_id FROM unit_references"
            ).fetchall():
                tokens = [
                    r[0]
                    for r in conn.execute(
                        "SELECT token FROM unit_reference_files WHERE unit_id=? AND reference_id=?",
                        (row["unit_id"], row["id"]),
                    )
                ]
                conn.execute(
                    "UPDATE unit_references SET file_tokens=? WHERE id=?",
                    (json.dumps(tokens), row["id"]),
                )
        # Preserve previously visible references as published when upgrading.
        for row in conn.execute(
            "SELECT * FROM unit_references WHERE status='published' AND published_value=''"
        ).fetchall():
            snapshot = dict(row)
            snapshot.pop("published_value", None)
            snapshot["file_tokens"] = [
                r[0]
                for r in conn.execute(
                    "SELECT token FROM unit_reference_files WHERE unit_id=? AND reference_id=?",
                    (row["unit_id"], row["id"]),
                )
            ]
            conn.execute(
                "UPDATE unit_references SET published_value=? WHERE id=?",
                (json.dumps(snapshot), row["id"]),
            )

    def snapshot(conn, unit_id, reference_id):
        row = get_row(conn, "unit_references", unit_id, reference_id)
        row.pop("published_value", None)
        row["file_tokens"] = [
            f["token"] for f in reference_files(conn, unit_id, reference_id)
        ]
        return row

    names = {
        "unit_library",
        "unit_reference",
        "unit_reference_save",
        "unit_reference_version",
        "unit_reference_restore",
        "unit_reference_file",
    }
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS

    MUTATIONS.update(
        {name: "view" for name in ("unit_reference_save", "unit_reference_restore")}
    )

    @api.app.get("/api/units/<int:unit_id>/library")
    def unit_library(unit_id):
        try:
            kind = request.args.get("kind", "sop")
            search = text(request.args.get("q", ""), "Search", 120)
            category = text(request.args.get("category", ""), "Category", 80)
            folder = text(request.args.get("folder", ""), "Folder", 160)
            status = request.args.get("status", "")
            if kind not in ("sop", "loadout") or status not in (
                "",
                "draft",
                "published",
                "template",
            ):
                raise ValueError("Choose a valid resource view")
            offset = number(int(request.args.get("offset", "0")), "Offset", 0, 1000000)
            ordering = {
                "title": "title COLLATE NOCASE,id",
                "updated": "updated_at DESC,id DESC",
                "oldest": "updated_at,id",
            }.get(request.args.get("sort", "title"))
            if ordering is None:
                raise ValueError("Choose a valid sort order")
            with db() as conn:
                unit = access(conn, unit_id)
                member = is_member(conn, unit_id)
                fields = [
                    "title",
                    "category",
                    "role",
                    "body",
                    "url",
                    "image_url",
                    "updated_by",
                    "updated_at",
                    "folder",
                ]
                if member:
                    source = (
                        "SELECT id,kind,"
                        + ",".join(
                            f"json_extract(published_value,'$.{key}') AS {key}"
                            for key in fields
                        )
                        + ",archived,'published' AS status,1 AS has_published FROM unit_references WHERE unit_id=? AND published_value!='' AND archived=0"
                    )
                else:
                    source = (
                        "SELECT id,kind,"
                        + ",".join(fields)
                        + ",archived,status,published_value!='' AS has_published FROM unit_references WHERE unit_id=?"
                    )
                visible = f"WITH visible AS ({source}) "
                rows = [
                    dict(r)
                    for r in conn.execute(
                        visible
                        + f"SELECT id,kind,title,category,role,substr(body,1,200) AS excerpt,url,image_url,archived,status,has_published,folder,updated_by,updated_at FROM visible WHERE kind=? AND archived=? AND (?='' OR category=?) AND (?='' OR folder=? OR substr(folder,1,length(?)+1)=?||'/') AND (?='' AND status!='template' OR status=?) AND (title LIKE ? OR body LIKE ? OR role LIKE ? OR category LIKE ?) ORDER BY {ordering} LIMIT 51 OFFSET ?",
                        (
                            unit_id,
                            kind,
                            0 if member else int(request.args.get("archived") == "1"),
                            category,
                            category,
                            folder,
                            folder,
                            folder,
                            folder,
                            "" if member else status,
                            "published" if member else status,
                            *["%" + search + "%"] * 4,
                            offset,
                        ),
                    )
                ]
                categories = [
                    r[0]
                    for r in conn.execute(
                        visible
                        + "SELECT DISTINCT category FROM visible WHERE kind=? ORDER BY category COLLATE NOCASE",
                        (unit_id, kind),
                    )
                ]
                folders = [
                    dict(r)
                    for r in conn.execute(
                        visible
                        + "SELECT folder,count(*) AS count FROM visible WHERE kind=? AND archived=0 AND status!='template' GROUP BY folder ORDER BY folder COLLATE NOCASE",
                        (unit_id, kind),
                    )
                ]
                documents = [
                    dict(r)
                    for r in conn.execute(
                        visible
                        + "SELECT id,title,folder FROM visible WHERE kind='sop' AND archived=0 AND status!='template' ORDER BY title COLLATE NOCASE LIMIT 1000",
                        (unit_id,),
                    )
                ]
                templates = (
                    []
                    if member
                    else [
                        dict(r)
                        for r in conn.execute(
                            "SELECT id,title FROM unit_references WHERE unit_id=? AND kind='sop' AND status='template' AND archived=0 ORDER BY title COLLATE NOCASE LIMIT 1000",
                            (unit_id,),
                        )
                    ]
                )
                events = (
                    []
                    if member
                    else [
                        dict(r)
                        for r in conn.execute(
                            "SELECT id,name FROM unit_events WHERE unit_id=? ORDER BY starts DESC LIMIT 1000",
                            (unit_id,),
                        )
                    ]
                )
                return jsonify(
                    events=events,
                    items=rows[:50],
                    next_offset=offset + 50 if len(rows) > 50 else None,
                    categories=categories,
                    folders=folders,
                    documents=documents,
                    templates=templates,
                    member=bool(member),
                    revision=unit["revision"],
                    permissions=permissions(conn, unit_id),
                )
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def reference_files(conn, unit_id, reference_id, tokens=None):
        if tokens is None:
            tokens = json.loads(
                get_row(conn, "unit_references", unit_id, reference_id)["file_tokens"]
            )
        return [
            dict(r)
            for r in conn.execute(
                "SELECT token,filename,mime,length(content) AS size FROM unit_reference_files WHERE unit_id=? AND reference_id=? ORDER BY created_at,token",
                (unit_id, reference_id),
            )
            if r["token"] in tokens
        ]

    @api.app.get("/api/units/<int:unit_id>/library/files/<token>")
    def unit_reference_file(unit_id, token):
        with db() as conn:
            access(conn, unit_id)
            row = conn.execute(
                "SELECT * FROM unit_reference_files WHERE unit_id=? AND token=?",
                (unit_id, token),
            ).fetchone()
            if not row:
                abort(404, description="File not found in this unit")
            if is_member(conn, unit_id):
                document = get_row(
                    conn, "unit_references", unit_id, row["reference_id"]
                )
                if (
                    document["archived"]
                    or not document["published_value"]
                    or token
                    not in json.loads(document["published_value"]).get(
                        "file_tokens", []
                    )
                ):
                    abort(404, description="Published file not found")
        response = send_file(
            io.BytesIO(row["content"]),
            mimetype=row["mime"],
            download_name=row["filename"],
            as_attachment=not row["mime"].startswith("image/"),
            max_age=0,
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def uploaded_files():
        files = list(request.files.items(multi=True))
        if len(files) > 10:
            raise ValueError("Upload at most 10 files at a time")
        result = []
        for token, upload in files:
            if not re.fullmatch(r"[a-f0-9]{32}", token) or any(
                f[0] == token for f in result
            ):
                raise ValueError("Invalid attachment identifier")
            filename = (
                text(upload.filename, "Filename", 200, True)
                .replace("\\", "/")
                .rsplit("/", 1)[-1]
            )
            content = upload.stream.read(20 * 1024 * 1024 + 1)
            if not content or len(content) > 20 * 1024 * 1024:
                raise ValueError("Each file must be between 1 byte and 20 MB")
            extension = filename.rsplit(".", 1)[-1].lower()
            mime = None
            if extension == "pdf" and content.startswith(b"%PDF-"):
                mime = "application/pdf"
            elif extension == "doc" and content.startswith(
                bytes.fromhex("d0cf11e0a1b11ae1")
            ):
                mime = "application/msword"
            elif extension == "docx":
                try:
                    with zipfile.ZipFile(io.BytesIO(content)) as archive:
                        names = set(archive.namelist())
                        if {
                            "[Content_Types].xml",
                            "word/document.xml",
                        } <= names and not any(
                            name.lower().endswith("vbaproject.bin") for name in names
                        ):
                            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                except zipfile.BadZipFile:
                    pass
            elif extension == "png" and content.startswith(b"\x89PNG\r\n\x1a\n"):
                mime = "image/png"
            elif extension in ("jpg", "jpeg") and content.startswith(b"\xff\xd8\xff"):
                mime = "image/jpeg"
            elif (
                extension == "webp"
                and content[:4] == b"RIFF"
                and content[8:12] == b"WEBP"
            ):
                mime = "image/webp"
            if mime is None:
                raise ValueError(
                    "Upload a PDF, Word (.doc/.docx), PNG, JPEG or WebP file"
                )
            if mime.startswith("image/") and len(content) > 4 * 1024 * 1024:
                raise ValueError("Images must be 4 MB or smaller")
            result.append((token, filename, mime, content))
        if sum(len(f[3]) for f in result) > 50 * 1024 * 1024:
            raise ValueError("Upload at most 50 MB per save")
        return result

    def related_details(conn, unit_id, row, member=False):
        result = []
        qualifications = set(
            json.loads(
                conn.execute(
                    "SELECT catalog FROM units WHERE id=?", (unit_id,)
                ).fetchone()[0]
            ).get("certificates", [])
        )
        for entry in json.loads(row.get("related", "[]")):
            item = dict(entry)
            if item["kind"] == "sop":
                target = conn.execute(
                    "SELECT title,published_value,archived FROM unit_references WHERE unit_id=? AND id=?",
                    (unit_id, item["id"]),
                ).fetchone()
                if (
                    not target
                    or target["archived"]
                    or member
                    and not target["published_value"]
                ):
                    continue
                item["title"] = (
                    json.loads(target["published_value"])["title"]
                    if member
                    else target["title"]
                )
            elif item["kind"] == "event":
                if member:
                    continue
                target = conn.execute(
                    "SELECT name FROM unit_events WHERE unit_id=? AND id=?",
                    (unit_id, item["id"]),
                ).fetchone()
                if not target:
                    continue
                item["title"] = target["name"]
            else:
                if (
                    item["kind"] == "qualification"
                    and item["name"] not in qualifications
                ):
                    continue
                item["title"] = item["name"]
            result.append(item)
        return result

    @api.app.get("/api/units/<int:unit_id>/library/<int:reference_id>")
    def unit_reference(unit_id, reference_id):
        with db() as conn:
            unit = access(conn, unit_id)
            row = get_row(conn, "unit_references", unit_id, reference_id)
            member = is_member(conn, unit_id)
            shown_publication = publication_digest(row["published_value"])
            published_view = member or request.args.get("published") == "1"
            if published_view:
                if row["archived"] or not row["published_value"]:
                    abort(404, description="Published document not found")
                row = json.loads(row["published_value"])
            tokens = row.get("file_tokens", [])
            files = reference_files(
                conn,
                unit_id,
                reference_id,
                json.loads(tokens) if isinstance(tokens, str) else tokens,
            )
            row = decode_reference(row)
            history = (
                []
                if published_view
                else [
                    dict(r)
                    for r in conn.execute(
                        "SELECT id,actor,created_at,action,reason FROM unit_resource_audit WHERE unit_id=? AND object_kind='reference' AND object_id=? ORDER BY id DESC LIMIT 50",
                        (unit_id, reference_id),
                    )
                ]
            )
            events = (
                []
                if member
                else [
                    dict(r)
                    for r in conn.execute(
                        "SELECT id,name FROM unit_events WHERE unit_id=? ORDER BY starts DESC LIMIT 1000",
                        (unit_id,),
                    )
                ]
            )
            acknowledgement = (
                next(
                    (
                        r
                        for r in required_reading(conn, unit_id)
                        if r["id"] == reference_id
                    ),
                    None,
                )
                if published_view and row["kind"] == "sop"
                else None
            )
            if acknowledgement and acknowledgement["publication"] != shown_publication:
                acknowledgement = None
            return jsonify(
                item=row,
                acknowledgement=acknowledgement,
                published_view=published_view,
                files=files,
                related=related_details(conn, unit_id, row, member),
                events=events,
                history=history,
                revision=unit["revision"],
                permissions=permissions(conn, unit_id),
            )

    @api.app.get(
        "/api/units/<int:unit_id>/library/<int:reference_id>/versions/<int:version_id>"
    )
    def unit_reference_version(unit_id, reference_id, version_id):
        with db() as conn:
            unit = access(conn, unit_id)
            current = snapshot(conn, unit_id, reference_id)
            row = conn.execute(
                "SELECT actor,created_at,after_value FROM unit_resource_audit WHERE unit_id=? AND object_kind='reference' AND object_id=? AND id=?",
                (unit_id, reference_id, version_id),
            ).fetchone()
            if not row:
                abort(404, description="Revision not found in this unit")
            item = json.loads(row["after_value"])
            item = decode_reference(item)
            files = reference_files(
                conn, unit_id, reference_id, item.get("file_tokens", [])
            )
            return jsonify(
                item=item,
                files=files,
                current=current,
                current_files=reference_files(conn, unit_id, reference_id),
                revision=unit["revision"],
                permissions=permissions(conn, unit_id),
                actor=row["actor"],
                created_at=row["created_at"],
            )

    @api.app.post(
        "/api/units/<int:unit_id>/library/<int:reference_id>/versions/<int:version_id>/restore"
    )
    def unit_reference_restore(unit_id, reference_id, version_id):
        try:
            data = request.get_json()
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "references")
                revision(conn, unit_id, data)
                old = snapshot(conn, unit_id, reference_id)
                saved = conn.execute(
                    "SELECT after_value FROM unit_resource_audit WHERE unit_id=? AND object_kind='reference' AND object_id=? AND id=?",
                    (unit_id, reference_id, version_id),
                ).fetchone()
                if not saved:
                    abort(404, description="Revision not found")
                source = json.loads(saved["after_value"])
                keys = (
                    "title",
                    "category",
                    "role",
                    "body",
                    "url",
                    "image_url",
                    "slots",
                )
                values = [source[key] for key in keys] + [
                    source.get("folder", ""),
                    source.get("related", "[]"),
                    json.dumps(source.get("file_tokens", [])),
                    actor(conn, unit_id),
                    time.time(),
                    reference_id,
                ]
                conn.execute(
                    "UPDATE unit_references SET title=?,category=?,role=?,body=?,url=?,image_url=?,slots=?,folder=?,related=?,file_tokens=?,updated_by=?,updated_at=?,status='draft' WHERE id=?",
                    values,
                )
                audit(
                    conn,
                    unit_id,
                    "reference",
                    reference_id,
                    "restored as draft",
                    old,
                    snapshot(conn, unit_id, reference_id),
                    reason=f"Restored revision {version_id}",
                )
            g.audit_details = dict(
                unit_id=unit_id,
                reference_id=reference_id,
                change="SOP revision restored as draft",
            )
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post("/api/units/<int:unit_id>/library")
    def unit_reference_save(unit_id):
        try:
            data = (
                request.get_json()
                if request.is_json
                else json.loads(request.form.get("data", "{}"))
            )
            if not isinstance(data, dict):
                raise ValueError("Choose valid SOP details")
            files = uploaded_files()
            kind = data.get("kind")
            if kind not in ("sop", "loadout"):
                raise ValueError("Choose SOP or loadout")
            title = text(data.get("title"), "Title", 120, True)
            category = text(data.get("category", "General"), "Category", 80, True)
            role = text(data.get("role", ""), "Role", 120)
            body = text(
                data.get("body", ""), "Content", 100000 if kind == "sop" else 20000
            )
            link = url(data.get("url", ""), "Reference link")
            image = url(data.get("image_url", ""), "Image URL")
            folder = "/".join(
                part.strip()
                for part in text(data.get("folder", ""), "Folder", 160).split("/")
                if part.strip()
            )
            if any(part in (".", "..") for part in folder.split("/")):
                raise ValueError("Use folder names without . or .. segments")
            status = data.get("status", "draft" if kind == "sop" else "published")
            if (
                status not in ("draft", "published", "template")
                or kind != "sop"
                and status == "template"
            ):
                raise ValueError("Choose Draft, Published or Template")
            related = data.get("related", [])
            if not isinstance(related, list) or len(related) > 30:
                raise ValueError("Choose at most 30 related items")
            slots = data.get("slots", [])
            if not isinstance(slots, list) or len(slots) > 40:
                raise ValueError("Keep at most 40 loadout slots")
            clean = []
            for slot in slots:
                if not isinstance(slot, dict):
                    raise ValueError("Choose valid loadout slots")
                clean.append(
                    {
                        key: text(
                            slot.get(key, ""),
                            key,
                            120 if key == "slot" else 2000,
                            key == "slot",
                        )
                        for key in ("slot", "standard", "alternatives", "notes")
                    }
                )
            if files and kind != "sop":
                raise ValueError("Attachments are available for SOPs")
            if kind == "sop":
                clean = []
                if (
                    not body
                    and not link
                    and not files
                    and not data.get("id")
                    and not data.get("template_id")
                ):
                    raise ValueError(
                        "Enter SOP content, a reference link or an attachment"
                    )
            elif not body and not clean and not link and not image:
                raise ValueError("Enter loadout slots, notes or a reference link")
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                access(conn, unit_id, "references")
                revision(conn, unit_id, data)
                old = (
                    get_row(conn, "unit_references", unit_id, data["id"])
                    if "id" in data
                    else None
                )
                if old and old["kind"] != kind:
                    raise ValueError("The reference type cannot be changed")
                if (
                    not old
                    and conn.execute(
                        "SELECT count(*) FROM unit_references WHERE unit_id=?",
                        (unit_id,),
                    ).fetchone()[0]
                    >= 1000
                ):
                    raise ValueError("Keep at most 1000 references per unit")
                normalized_related = []
                catalog = json.loads(
                    conn.execute(
                        "SELECT catalog FROM units WHERE id=?", (unit_id,)
                    ).fetchone()[0]
                )
                for entry in related:
                    if not isinstance(entry, dict) or entry.get("kind") not in (
                        "sop",
                        "event",
                        "qualification",
                        "position",
                    ):
                        raise ValueError("Choose a valid related item")
                    target_kind = entry["kind"]
                    if target_kind in ("sop", "event"):
                        target_id = number(
                            entry.get("id"), "Related item", 1, 9223372036854775807
                        )
                        table = (
                            "unit_references" if target_kind == "sop" else "unit_events"
                        )
                        target = get_row(conn, table, unit_id, target_id)
                        if target_kind == "sop" and (
                            target["kind"] != "sop"
                            or target["status"] == "template"
                            or old
                            and target_id == old["id"]
                        ):
                            raise ValueError("Choose another SOP as a related document")
                        normalized_related.append(dict(kind=target_kind, id=target_id))
                    else:
                        name = text(entry.get("name"), "Related name", 120, True)
                        if name not in catalog.get(
                            (
                                "certificates"
                                if target_kind == "qualification"
                                else "positions"
                            ),
                            [],
                        ):
                            raise ValueError(
                                "Choose an existing qualification or position"
                            )
                        normalized_related.append(dict(kind=target_kind, name=name))
                template_id = data.get("template_id")
                if template_id is not None:
                    if old:
                        raise ValueError("Use templates when creating a new SOP")
                    source = get_row(conn, "unit_references", unit_id, template_id)
                    if (
                        source["status"] != "template"
                        or source["archived"]
                        or source["kind"] != "sop"
                    ):
                        raise ValueError("Choose an active SOP template")
                    for attachment in conn.execute(
                        "SELECT * FROM unit_reference_files WHERE unit_id=? AND reference_id=?",
                        (unit_id, template_id),
                    ).fetchall():
                        if attachment["token"] not in json.loads(source["file_tokens"]):
                            continue
                        token = uuid.uuid4().hex
                        body = body.replace(
                            "attachment:" + attachment["token"], "attachment:" + token
                        )
                        files.append(
                            (
                                token,
                                attachment["filename"],
                                attachment["mime"],
                                attachment["content"],
                            )
                        )
                values = (
                    kind,
                    title,
                    category,
                    role,
                    body,
                    link,
                    image,
                    json.dumps(clean),
                    archive(data),
                    actor(conn, unit_id),
                    time.time(),
                )
                if old:
                    conn.execute(
                        "UPDATE unit_references SET kind=?,title=?,category=?,role=?,body=?,url=?,image_url=?,slots=?,archived=?,updated_by=?,updated_at=? WHERE id=?",
                        (*values, old["id"]),
                    )
                    reference_id = old["id"]
                else:
                    reference_id = conn.execute(
                        "INSERT INTO unit_references(unit_id,kind,title,category,role,body,url,image_url,slots,archived,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (unit_id, *values),
                    ).lastrowid
                if files:
                    used = conn.execute(
                        "SELECT coalesce(sum(length(content)),0) FROM unit_reference_files WHERE unit_id=?",
                        (unit_id,),
                    ).fetchone()[0]
                    count = conn.execute(
                        "SELECT count(*) FROM unit_reference_files WHERE unit_id=? AND reference_id=?",
                        (unit_id, reference_id),
                    ).fetchone()[0]
                    if (
                        used + sum(len(f[3]) for f in files) > 200 * 1024 * 1024
                        or count + len(files) > 50
                    ):
                        raise ValueError(
                            "Keep attachments below 200 MB per unit and 50 files per document"
                        )
                    for token, filename, mime, content in files:
                        if conn.execute(
                            "SELECT 1 FROM unit_reference_files WHERE token=?", (token,)
                        ).fetchone():
                            raise ValueError(
                                "Attachment already exists; reload before saving"
                            )
                        conn.execute(
                            "INSERT INTO unit_reference_files VALUES(?,?,?,?,?,?,?,?)",
                            (
                                token,
                                unit_id,
                                reference_id,
                                filename,
                                mime,
                                content,
                                actor(conn, unit_id),
                                time.time(),
                            ),
                        )
                active_files = (json.loads(old["file_tokens"]) if old else []) + [
                    f[0] for f in files
                ]
                conn.execute(
                    "UPDATE unit_references SET folder=?,status=?,related=?,file_tokens=? WHERE id=?",
                    (
                        folder,
                        status,
                        json.dumps(normalized_related),
                        json.dumps(active_files),
                        reference_id,
                    ),
                )
                saved = snapshot(conn, unit_id, reference_id)
                if kind == "sop" and not body and not link and not saved["file_tokens"]:
                    raise ValueError(
                        "Enter SOP content, a reference link or an attachment"
                    )
                if status == "template":
                    conn.execute(
                        "UPDATE unit_references SET published_value='' WHERE id=?",
                        (reference_id,),
                    )
                if status == "published":
                    conn.execute(
                        "UPDATE unit_references SET published_value=? WHERE id=?",
                        (json.dumps(saved), reference_id),
                    )
                audit(
                    conn,
                    unit_id,
                    "reference",
                    reference_id,
                    (
                        "published"
                        if status == "published"
                        else "updated" if old else "created"
                    ),
                    old,
                    saved,
                )
            g.audit_details = dict(
                unit_id=unit_id, reference_id=reference_id, change="reference saved"
            )
            return jsonify(ok=True, id=reference_id)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
