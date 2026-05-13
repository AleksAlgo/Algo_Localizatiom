"""
Jerome 1.1 — Flask web server with Google OAuth 2.0.
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
import os
import secrets
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json as _json

from flask import Flask, jsonify, redirect, request, send_file, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

import drive_client
import jerome_engine

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # allow http://localhost

OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

app = Flask(__name__, static_folder="static", template_folder="static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

_job: dict = {"status": "idle", "files": [], "log": []}
_job_lock = threading.Lock()

LANG_PAIRS = [
    {"label": "Русский → Английский", "src": "ru", "tgt": "en"},
    {"label": "Английский → Испанский", "src": "en", "tgt": "es"},
]


def _set_job(**kwargs):
    with _job_lock:
        _job.update(kwargs)


def _log(msg: str):
    with _job_lock:
        _job["log"].append(msg)
    print(msg, flush=True)


def _get_oauth_creds() -> Credentials | None:
    token_data = session.get("oauth_token")
    if not token_data:
        return None
    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        session["oauth_token"] = _creds_to_dict(creds)
    return creds


def _creds_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }


def _get_oauth_client_config() -> dict:
    if drive_client.OAUTH_CLIENT_FILE.exists():
        return _json.loads(drive_client.OAUTH_CLIENT_FILE.read_text())
    raw = os.environ.get("GOOGLE_OAUTH_CLIENT_JSON")
    if raw:
        return _json.loads(raw)
    raise RuntimeError("oauth_client.json not found and GOOGLE_OAUTH_CLIENT_JSON not set")


# ── OAuth routes ──────────────────────────────────────────────────────────────

@app.route("/oauth/login")
def oauth_login():
    import traceback
    try:
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()

        flow = Flow.from_client_config(
            _get_oauth_client_config(),
            scopes=OAUTH_SCOPES,
            redirect_uri=url_for("oauth_callback", _external=True),
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )
        session["oauth_state"] = state
        session["code_verifier"] = code_verifier
        return redirect(auth_url)
    except Exception as e:
        tb = traceback.format_exc()
        print(tb, flush=True)
        return f"<pre style='color:red'>OAuth login error:\n{tb}</pre>", 500


@app.route("/oauth/callback")
def oauth_callback():
    import traceback
    try:
        state = session.get("oauth_state")
        code_verifier = session.get("code_verifier")
        flow = Flow.from_client_config(
            _get_oauth_client_config(),
            scopes=OAUTH_SCOPES,
            state=state,
            redirect_uri=url_for("oauth_callback", _external=True),
        )
        flow.fetch_token(authorization_response=request.url, code_verifier=code_verifier)
        session["oauth_token"] = _creds_to_dict(flow.credentials)
        return redirect("/")
    except Exception as e:
        tb = traceback.format_exc()
        print(tb, flush=True)
        return f"<pre style='color:red'>OAuth error:\n{tb}</pre>", 500


@app.route("/oauth/logout")
def oauth_logout():
    session.pop("oauth_token", None)
    return redirect("/")


@app.route("/api/auth_status")
def api_auth_status():
    creds = _get_oauth_creds()
    return jsonify({"authenticated": creds is not None and creds.valid})


# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/lang_pairs")
def api_lang_pairs():
    return jsonify(LANG_PAIRS)


@app.route("/api/list_folder", methods=["POST"])
def api_list_folder():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL не указан"}), 400
    try:
        folder_id = drive_client.get_folder_id_from_url(url)
        files = drive_client.list_folder(folder_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    supported_mimes = {
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.presentation",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/x-xliff+xml",
        "application/xliff+xml",
        "text/xml",
    }
    files = [f for f in files if f.get("mimeType") in supported_mimes]

    result_files = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for f in files:
            try:
                local = drive_client.download_file(f["id"], f["name"], f["mimeType"], tmp_path)
                n_words = jerome_engine.count_file_words(local)
            except Exception:
                n_words = 0
            result_files.append({"id": f["id"], "name": f["name"],
                                  "mimeType": f["mimeType"], "words": n_words})

    return jsonify({"folder_id": folder_id, "files": result_files})


@app.route("/api/start", methods=["POST"])
def api_start():
    creds = _get_oauth_creds()
    if not creds or not creds.valid:
        return jsonify({"error": "Требуется авторизация Google"}), 401

    data = request.get_json()
    src_url = data.get("src_url", "").strip()
    dst_url = data.get("dst_url", "").strip()
    lang_pair = data.get("lang_pair", {})
    selected_ids = set(data.get("selected_ids", []))

    if not src_url:
        return jsonify({"error": "Укажите исходную папку"}), 400
    if not dst_url:
        return jsonify({"error": "Укажите конечную папку"}), 400
    if not lang_pair:
        return jsonify({"error": "Выберите языковую пару"}), 400

    with _job_lock:
        if _job["status"] == "running":
            return jsonify({"error": "Задача уже выполняется"}), 409

    src_folder_id = drive_client.get_folder_id_from_url(src_url)
    dst_folder_id = drive_client.get_folder_id_from_url(dst_url)
    all_files = drive_client.list_folder(src_folder_id)
    file_list = [f for f in all_files if f["id"] in selected_ids]

    if not file_list:
        return jsonify({"error": "Нет выбранных файлов"}), 400

    token_snapshot = session.get("oauth_token")

    _set_job(
        status="running",
        files=[{"name": f["name"], "status": "pending", "score": None} for f in file_list],
        log=[], results=[], work_dir=None, error="",
        overall_score=None, overall_label="",
    )

    def _run():
        tmp_dir = tempfile.mkdtemp(prefix="jerome_")
        _set_job(work_dir=tmp_dir)
        work_path = Path(tmp_dir)
        _log(f"Рабочая директория: {tmp_dir}")

        # Restore OAuth creds from snapshot (thread has no session)
        oauth_creds = Credentials(
            token=token_snapshot["token"],
            refresh_token=token_snapshot.get("refresh_token"),
            token_uri=token_snapshot["token_uri"],
            client_id=token_snapshot["client_id"],
            client_secret=token_snapshot["client_secret"],
            scopes=token_snapshot["scopes"],
        )

        def _prog(stage: str):
            _log(stage)
            for i, f in enumerate(file_list):
                if f["name"] in stage:
                    with _job_lock:
                        if "переведено" in stage:
                            _job["files"][i]["status"] = "translated"
                        elif "перевод" in stage:
                            _job["files"][i]["status"] = "translating"
                        elif "скачивание" in stage:
                            _job["files"][i]["status"] = "downloading"

        def _upload(folder_id, local_path):
            return drive_client.upload_file(folder_id, local_path, oauth_creds)

        try:
            pipeline_result = jerome_engine.run_pipeline(
                file_list=file_list,
                src_folder_id=src_folder_id,
                dst_folder_id=dst_folder_id,
                src_lang=lang_pair["src"],
                tgt_lang=lang_pair["tgt"],
                work_dir=work_path,
                drive_download_fn=drive_client.download_file,
                drive_upload_fn=_upload,
                progress_cb=_prog,
            )
            with _job_lock:
                for i, r in enumerate(pipeline_result["files"]):
                    if i < len(_job["files"]):
                        _job["files"][i]["status"] = "done"
                _job["overall_score"] = pipeline_result.get("overall_score")
                _job["overall_label"] = pipeline_result.get("overall_label", "")
                _job["results"] = pipeline_result
                _job["status"] = "done"
        except Exception as e:
            import traceback
            _log(f"ОШИБКА: {e}")
            _log(traceback.format_exc())
            _set_job(status="error", error=str(e))

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    with _job_lock:
        return jsonify({
            "status": _job["status"],
            "files": _job.get("files", []),
            "overall_score": _job.get("overall_score"),
            "overall_label": _job.get("overall_label", ""),
            "log": _job.get("log", [])[-30:],
            "error": _job.get("error", ""),
        })


@app.route("/api/download_reports")
def api_download_reports():
    with _job_lock:
        work_dir = _job.get("work_dir")
        if not work_dir or _job["status"] != "done":
            return jsonify({"error": "Нет готовых результатов"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in Path(work_dir).glob("*.md"):
            zf.write(p, p.name)
        for p in Path(work_dir).glob("*.xlsx"):
            zf.write(p, p.name)
        for p in Path(work_dir).glob("*_reviewed.*"):
            if p.suffix not in (".md", ".xlsx"):
                zf.write(p, p.name)
        for p in Path(work_dir).glob("*_translated.*"):
            if p.suffix not in (".md", ".xlsx"):
                zf.write(p, p.name)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name="jerome_qa_reports.zip")


@app.route("/debug/env")
def debug_env():
    return jsonify({
        "has_GOOGLE_OAUTH_CLIENT_JSON": "GOOGLE_OAUTH_CLIENT_JSON" in os.environ,
        "has_GOOGLE_SERVICE_ACCOUNT_JSON": "GOOGLE_SERVICE_ACCOUNT_JSON" in os.environ,
        "has_ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY" in os.environ,
        "has_OPENROUTER_API_KEY": "OPENROUTER_API_KEY" in os.environ,
        "has_SECRET_KEY": "SECRET_KEY" in os.environ,
    })


@app.route("/")
def index():
    return app.send_static_file("index.html")


if __name__ == "__main__":
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("WARNING: OPENROUTER_API_KEY not set", flush=True)
    app.run(host="0.0.0.0", port=5001, debug=False)
