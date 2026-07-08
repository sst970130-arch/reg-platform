"""
사내 제약 R&D 규제 통합 플랫폼 - 메인 애플리케이션
실행 방법: python3 app.py  (기본 접속 주소: http://localhost:8000)

이 파일은 화면(라우트) 연결만 담당합니다.
실제 로직은 modules/ 폴더의 db.py, extract.py, search.py, ai_analysis.py, mfds_sync.py 를 참고하세요.
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from dotenv import load_dotenv

from modules import db, extract, search, ai_analysis, mfds_sync

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
app.jinja_env.globals["get_latest_note"] = db.get_latest_note

ALLOWED_EXTENSIONS = {".pdf", ".pptx", ".ppt", ".txt"}


@app.template_filter("category_label")
def category_label(cat):
    return db.CATEGORY_LABELS.get(cat, cat)


@app.template_filter("is_new")
def is_new_filter(upload_date):
    return db.is_new(upload_date)


@app.template_filter("fmt_date")
def fmt_date(value):
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d")
    except Exception:
        return value or ""


@app.template_filter("from_json")
def from_json_filter(value):
    try:
        return json.loads(value) if value else []
    except (TypeError, ValueError):
        return []


@app.template_filter("revision_preview")
def revision_preview_filter(text, length=160):
    """목록에서 '개정이유/주요내용'을 자동 추출해 짧게 보여주기 위한 필터. 해당 형식이 아니면 None."""
    info = search.extract_revision_info(text)
    if not info:
        return None
    content = (info["summary"] or info["reason"] or "").strip()
    if not content:
        return None
    return content[:length] + ("..." if len(content) > length else "")


@app.context_processor
def inject_globals():
    return {
        "recent_docs": db.get_recent_documents(),
        "doc_count": db.document_count(),
        "ai_enabled": ai_analysis.is_configured(),
    }


@app.route("/")
def index():
    counts = db.category_counts()
    return render_template(
        "dashboard.html",
        counts=counts,
        guide_count=db.guide_note_count(),
        recent_docs=db.get_recent_documents(limit=12),
        last_sync=mfds_sync.get_last_sync_info(),
    )


@app.route("/search")
def do_search():
    query = request.args.get("q", "").strip()
    if not query:
        return redirect(url_for("index"))

    matched = search.search_documents(query, top_k=8)
    matched_guides = search.search_guide_notes(query, top_k=3)

    ai_result = ai_analysis.analyze(query, matched)

    # 우측 컬럼용: 카테고리별로 정리
    notices = [m for m in matched if m["doc"]["category"] == "notice"]
    qnas = [m for m in matched if m["doc"]["category"] == "qna"]

    for m in notices:
        m["snippet"] = search.extract_snippet(m["doc"]["extracted_text"], query)

    qna_pairs_by_doc = []
    for m in qnas:
        pairs = search.extract_qna_pairs(m["doc"]["extracted_text"])
        qna_pairs_by_doc.append({"doc": m["doc"], "pairs": pairs})

    related_seminars = search.find_related_seminars(matched)

    return render_template(
        "search_results.html",
        query=query,
        results=matched,
        ai_result=ai_result,
        matched_guides=matched_guides,
        notices=notices,
        qna_pairs_by_doc=qna_pairs_by_doc,
        related_seminars=related_seminars,
    )


@app.route("/category/<cat>")
def category_list(cat):
    if cat not in db.CATEGORY_LABELS:
        return "존재하지 않는 분류입니다.", 404
    docs = db.get_all_documents(category=cat)
    return render_template("document_list.html", cat=cat, docs=docs)


@app.route("/document/<int:doc_id>")
def document_detail(doc_id):
    doc = db.get_document(doc_id)
    if not doc:
        return "해당 문서를 찾을 수 없습니다.", 404
    revision_info = search.extract_revision_info(doc["extracted_text"])
    candidates = [d for d in db.get_all_documents(category=doc["category"]) if d["id"] != doc_id]
    other_docs = search.find_related_versions(doc, candidates)
    attachments = db.get_attachments(doc_id)
    action_items = search.suggest_action_items(doc["board_name"], doc["category"])
    notes = db.get_notes(doc_id)
    return render_template(
        "document_detail.html", doc=doc, revision_info=revision_info,
        other_docs=other_docs, attachments=attachments, action_items=action_items, notes=notes,
    )


@app.route("/document/<int:doc_id>/note", methods=["POST"])
def document_note_add(doc_id):
    if not db.get_document(doc_id):
        return "해당 문서를 찾을 수 없습니다.", 404
    note_text = request.form.get("note_text", "").strip()
    if note_text:
        db.insert_note(doc_id, note_text)
        flash("스티커 메모를 추가했습니다.", "success")
    return redirect(url_for("document_detail", doc_id=doc_id))


@app.route("/note/<int:note_id>/edit", methods=["POST"])
def note_edit(note_id):
    note = db.get_note(note_id)
    if not note:
        return "해당 메모를 찾을 수 없습니다.", 404
    note_text = request.form.get("note_text", "").strip()
    if note_text:
        db.update_note(note_id, note_text)
        flash("스티커 메모를 수정했습니다.", "success")
    return redirect(url_for("document_detail", doc_id=note["document_id"]))


@app.route("/note/<int:note_id>/delete", methods=["POST"])
def note_delete(note_id):
    note = db.get_note(note_id)
    if not note:
        return "해당 메모를 찾을 수 없습니다.", 404
    doc_id = note["document_id"]
    db.delete_note(note_id)
    flash("스티커 메모를 삭제했습니다.", "success")
    return redirect(url_for("document_detail", doc_id=doc_id))


@app.route("/document/<int:doc_id>/diff/upload", methods=["POST"])
def document_diff_upload(doc_id):
    """자동으로 이전 버전을 못 찾았을 때, 직접 갖고 있는 파일을 올려서 바로 비교할 수 있게 합니다."""
    doc = db.get_document(doc_id)
    if not doc:
        return "해당 문서를 찾을 수 없습니다.", 404
    file = request.files.get("file")
    if not file or not file.filename:
        flash("비교할 파일을 선택해 주세요.", "error")
        return redirect(url_for("document_detail", doc_id=doc_id))
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        flash(f"지원하지 않는 파일 형식입니다: {ext} (PDF, PPTX, TXT만 가능)", "error")
        return redirect(url_for("document_detail", doc_id=doc_id))

    safe_name = f"{uuid.uuid4().hex}{ext}"
    stored_path_abs = os.path.join(db.UPLOAD_DIR, safe_name)
    file.save(stored_path_abs)
    extracted_text = extract.extract_text(stored_path_abs)

    uploaded_doc_id = db.insert_document(
        category=doc["category"],
        title=f"{doc['title']} (이전판 - 직접 업로드: {file.filename})",
        extracted_text=extracted_text,
        original_filename=file.filename,
        stored_path=safe_name,
        origin="manual",
        board_name=doc["board_name"],
    )
    return redirect(url_for("document_diff", doc_id=doc_id, **{"with": uploaded_doc_id}))


@app.route("/document/<int:doc_id>/diff")
def document_diff(doc_id):
    doc = db.get_document(doc_id)
    other_id = request.args.get("with", type=int)
    other = db.get_document(other_id) if other_id else None
    if not doc or not other:
        return "비교할 문서를 찾을 수 없습니다.", 404

    MAX_LINES = 1500
    lines_a = search.to_diff_lines(doc["extracted_text"])
    lines_b = search.to_diff_lines(other["extracted_text"])
    truncated = len(lines_a) > MAX_LINES or len(lines_b) > MAX_LINES
    lines_a = lines_a[:MAX_LINES]
    lines_b = lines_b[:MAX_LINES]

    MAX_ROWS = 300
    rows = search.build_side_by_side_diff(lines_a, lines_b)
    diff_capped = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    return render_template(
        "document_diff.html", doc=doc, other=other, rows=rows,
        truncated=truncated, diff_capped=diff_capped,
    )


@app.route("/guide")
def guide_list():
    notes = db.get_all_guide_notes()
    return render_template("guide_list.html", notes=notes)


@app.route("/guide/<int:note_id>")
def guide_detail(note_id):
    note = db.get_guide_note(note_id)
    if not note:
        return "해당 해설 노트를 찾을 수 없습니다.", 404
    qna = json.loads(note["qna_json"]) if note["qna_json"] else []
    return render_template("guide_detail.html", note=note, qna=qna)


@app.route("/admin", methods=["GET"])
def admin():
    docs = db.get_all_documents()
    return render_template("admin_upload.html", docs=docs, last_sync=mfds_sync.get_last_sync_info())


@app.route("/admin/upload", methods=["POST"])
def admin_upload():
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "notice")
    team_tag = request.form.get("team_tag") or None
    uploader = request.form.get("uploader") or None
    presenter = request.form.get("presenter") or None
    event_date = request.form.get("event_date") or None
    source_url = request.form.get("source_url") or None
    file = request.files.get("file")
    manual_text = request.form.get("manual_text", "").strip()

    if not title:
        flash("문서 제목을 입력해 주세요.", "error")
        return redirect(url_for("admin"))

    stored_path = None
    original_filename = None
    extracted_text = manual_text

    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            flash(f"지원하지 않는 파일 형식입니다: {ext} (PDF, PPTX, TXT만 가능)", "error")
            return redirect(url_for("admin"))
        original_filename = file.filename
        safe_name = f"{uuid.uuid4().hex}{ext}"
        stored_path_abs = os.path.join(db.UPLOAD_DIR, safe_name)
        file.save(stored_path_abs)
        stored_path = safe_name
        extracted_from_file = extract.extract_text(stored_path_abs)
        extracted_text = (extracted_text + "\n" + extracted_from_file).strip() if extracted_text else extracted_from_file

    if not extracted_text:
        flash("파일 업로드 또는 텍스트 붙여넣기 중 하나는 필요합니다.", "error")
        return redirect(url_for("admin"))

    doc_id = db.insert_document(
        category=category,
        title=title,
        extracted_text=extracted_text,
        team_tag=team_tag,
        uploader=uploader,
        presenter=presenter,
        event_date=event_date,
        source_url=source_url,
        original_filename=original_filename,
        stored_path=stored_path,
    )
    flash(f"'{title}' 문서가 등록되었습니다. (ID: {doc_id})", "success")
    return redirect(url_for("admin"))


@app.route("/admin/guides", methods=["GET"])
def admin_guides():
    notes = db.get_all_guide_notes()
    edit_id = request.args.get("edit", type=int)
    edit_note = db.get_guide_note(edit_id) if edit_id else None
    edit_qna = json.loads(edit_note["qna_json"]) if edit_note and edit_note["qna_json"] else []
    return render_template("admin_guides.html", notes=notes, edit_note=edit_note, edit_qna=edit_qna)


@app.route("/admin/guides/save", methods=["POST"])
def admin_guides_save():
    note_id = request.form.get("note_id") or None
    topic_category = request.form.get("topic_category", "validation").strip()
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    status = request.form.get("status", "draft")

    questions = request.form.getlist("qna_question")
    answers = request.form.getlist("qna_answer")
    qna = [
        {"question": q.strip(), "answer": a.strip()}
        for q, a in zip(questions, answers)
        if q.strip() and a.strip()
    ]
    qna_json = json.dumps(qna, ensure_ascii=False)

    if not title or not body:
        flash("제목과 본문은 필수입니다.", "error")
        return redirect(url_for("admin_guides"))

    if note_id:
        db.update_guide_note(int(note_id), topic_category, title, body, qna_json, status)
        flash(f"'{title}' 해설 노트를 수정했습니다.", "success")
    else:
        db.insert_guide_note(topic_category, title, body, qna_json, status)
        flash(f"'{title}' 해설 노트를 등록했습니다.", "success")
    return redirect(url_for("admin_guides"))


@app.route("/download/<int:doc_id>")
def download(doc_id):
    doc = db.get_document(doc_id)
    if not doc or not doc["stored_path"]:
        return "파일을 찾을 수 없습니다.", 404
    return send_from_directory(
        db.UPLOAD_DIR, doc["stored_path"], as_attachment=True, download_name=doc["original_filename"]
    )


@app.route("/view/<int:doc_id>")
def view_inline(doc_id):
    """업로드된 원문을 모달 iframe 안에서 바로 볼 수 있도록 다운로드가 아닌 인라인으로 제공합니다."""
    doc = db.get_document(doc_id)
    if not doc or not doc["stored_path"]:
        return "파일을 찾을 수 없습니다.", 404
    return send_from_directory(db.UPLOAD_DIR, doc["stored_path"], as_attachment=False)


@app.route("/attachment/<int:att_id>")
def attachment_view(att_id):
    """식약처 원문 첨부파일(자동 다운로드분)을 보여줍니다. PDF는 브라우저에서 바로 열리고,
    HWP/ZIP 등은 브라우저가 알아서 다운로드로 처리합니다."""
    att = db.get_attachment(att_id)
    if not att:
        return "첨부파일을 찾을 수 없습니다.", 404
    return send_from_directory(
        db.UPLOAD_DIR, att["stored_path"], as_attachment=False, download_name=att["filename"]
    )


def _periodic_sync(interval_minutes):
    while True:
        try:
            n = mfds_sync.sync_all()
            if n:
                print(f"[mfds_sync] 신규 {n}건 자동 등록됨")
        except Exception as e:
            print(f"[mfds_sync] 동기화 중 오류(다음 주기에 재시도): {e}")
        time.sleep(max(interval_minutes, 1) * 60)


def start_background_sync():
    if os.environ.get("MFDS_SYNC_ENABLED", "true").lower() not in ("1", "true", "yes"):
        return
    interval = int(os.environ.get("MFDS_SYNC_INTERVAL_MINUTES", "30"))
    thread = threading.Thread(target=_periodic_sync, args=(interval,), daemon=True)
    thread.start()


if __name__ == "__main__":
    db.init_db()
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    # 디버그 모드는 리로더 때문에 프로세스가 두 번 뜨는데, 실제 요청을 처리하는 자식 프로세스에서만
    # (WERKZEUG_RUN_MAIN=true) 동기화를 시작해 중복 실행을 방지합니다.
    if (not debug_mode) or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background_sync()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
