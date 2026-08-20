import os
import secrets
import shutil
import time
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory, session

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

TTL_HOURS = float(os.environ.get("TTL_HOURS", "6"))
BUCKET_PASSWORD = os.environ.get("BUCKET_PASSWORD")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-insecure-secret-change-me")

if not BUCKET_PASSWORD:
    print(
        "WARNING: BUCKET_PASSWORD is not set — uploads/deletes will be "
        "rejected until it is configured.",
        flush=True,
    )


def sweep_expired():
    """Delete any upload folder older than TTL_HOURS. Called on every read
    so no separate cron/scheduler is needed for the few-hour lifespan."""
    cutoff = time.time() - TTL_HOURS * 3600
    for entry in DATA_DIR.iterdir():
        if entry.is_dir() and entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry, ignore_errors=True)


def list_files():
    sweep_expired()
    files = []
    for entry in sorted(DATA_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not entry.is_dir():
            continue
        children = [c for c in entry.iterdir() if c.is_file()]
        if not children:
            continue
        f = children[0]
        uploaded_at = entry.stat().st_mtime
        files.append(
            {
                "slug": entry.name,
                "filename": f.name,
                "size": f.stat().st_size,
                "uploaded_at": uploaded_at,
                "expires_at": uploaded_at + TTL_HOURS * 3600,
            }
        )
    return files


def is_unlocked():
    return session.get("unlocked") is True


@app.route("/")
def index():
    return render_template("index.html", ttl_hours=TTL_HOURS)


@app.route("/api/files")
def api_files():
    return jsonify({"files": list_files(), "unlocked": is_unlocked(), "ttl_hours": TTL_HOURS})


@app.route("/api/login", methods=["POST"])
def api_login():
    if not BUCKET_PASSWORD:
        return jsonify({"error": "server has no password configured"}), 503
    data = request.get_json(silent=True) or {}
    if data.get("password") == BUCKET_PASSWORD:
        session["unlocked"] = True
        session.permanent = True
        return jsonify({"ok": True})
    return jsonify({"error": "wrong password"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("unlocked", None)
    return jsonify({"ok": True})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if not is_unlocked():
        abort(401)
    uploaded = request.files.getlist("file")
    if not uploaded:
        return jsonify({"error": "no file"}), 400
    for f in uploaded:
        if not f.filename:
            continue
        slug = secrets.token_urlsafe(9)
        folder = DATA_DIR / slug
        folder.mkdir(parents=True, exist_ok=True)
        safe_name = os.path.basename(f.filename)
        f.save(folder / safe_name)
    return jsonify({"ok": True, "files": list_files()})


@app.route("/api/files/<slug>", methods=["DELETE"])
def api_delete(slug):
    if not is_unlocked():
        abort(401)
    folder = DATA_DIR / slug
    if folder.is_dir() and folder.parent == DATA_DIR:
        shutil.rmtree(folder, ignore_errors=True)
    return jsonify({"ok": True, "files": list_files()})


@app.route("/api/clear", methods=["POST"])
def api_clear():
    if not is_unlocked():
        abort(401)
    for entry in DATA_DIR.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
    return jsonify({"ok": True, "files": []})


@app.route("/f/<slug>/<path:filename>")
def download(slug, filename):
    sweep_expired()
    folder = DATA_DIR / slug
    if not folder.is_dir():
        abort(404)
    return send_from_directory(folder, filename, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5400))
    app.run(host="0.0.0.0", port=port)
