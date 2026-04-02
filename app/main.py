import os
import time
import uuid
import logging
import smtplib
import requests
import threading
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="../static", template_folder="../templates")
CORS(app)

# ── Config from env ────────────────────────────────────────────────────────────
PROWLARR_URL    = os.environ.get("PROWLARR_URL", "").rstrip("/")
PROWLARR_APIKEY = os.environ.get("PROWLARR_APIKEY", "")
DOWNLOAD_DIR    = os.environ.get("DOWNLOAD_DIR", "/downloads")
KINDLE_EMAIL    = os.environ.get("KINDLE_EMAIL", "")
SMTP_HOST       = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER       = os.environ.get("SMTP_USER", "")
SMTP_PASS       = os.environ.get("SMTP_PASS", "")
SMTP_FROM       = os.environ.get("SMTP_FROM", SMTP_USER)
POLL_TIMEOUT    = int(os.environ.get("POLL_TIMEOUT", "300"))   # seconds to wait for file
POLL_INTERVAL   = int(os.environ.get("POLL_INTERVAL", "10"))   # seconds between checks

EBOOK_EXTENSIONS = {".epub", ".mobi", ".azw3", ".pdf"}

# ── Health ─────────────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# ── Config endpoint (read-only, so frontend can show what's set) ───────────────
@app.route("/api/config")
def get_config():
    return jsonify({
        "prowlarr_url":   PROWLARR_URL,
        "prowlarr_ready": bool(PROWLARR_URL and PROWLARR_APIKEY),
        "kindle_email":   KINDLE_EMAIL,
        "smtp_ready":     bool(SMTP_HOST and SMTP_USER and SMTP_PASS and KINDLE_EMAIL),
        "download_dir":   DOWNLOAD_DIR,
    })


# ── Search ─────────────────────────────────────────────────────────────────────
@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "query required"}), 400

    if not PROWLARR_URL or not PROWLARR_APIKEY:
        return jsonify({"error": "Prowlarr not configured (check env vars)"}), 503

    params = {
        "query":  query,
        "type":   "book",
        "limit":  100,
        "apikey": PROWLARR_APIKEY,
    }
    try:
        r = requests.get(f"{PROWLARR_URL}/api/v1/search", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.ConnectionError:
        return jsonify({"error": f"Cannot reach Prowlarr at {PROWLARR_URL}"}), 502
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"Prowlarr error: {e.response.status_code}"}), 502
    except Exception as e:
        log.exception("Search failed")
        return jsonify({"error": str(e)}), 500

    return jsonify(data)


# ── Download + Send ────────────────────────────────────────────────────────────
@app.route("/api/send", methods=["POST"])
def send():
    body = request.get_json(force=True)
    guid      = body.get("guid")
    indexer_id = body.get("indexerId")
    title     = body.get("title", "ebook")

    if not guid or not indexer_id:
        return jsonify({"error": "guid and indexerId required"}), 400

    if not SMTP_USER or not SMTP_PASS or not KINDLE_EMAIL:
        return jsonify({"error": "SMTP / Kindle email not configured"}), 503

    # Push to Prowlarr download client
    try:
        r = requests.post(
            f"{PROWLARR_URL}/api/v1/download",
            params={"apikey": PROWLARR_APIKEY},
            json={"guid": guid, "indexerId": indexer_id},
            timeout=15,
        )
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"Download push failed: {e.response.status_code} {e.response.text[:120]}"}), 502
    except Exception as e:
        return jsonify({"error": f"Download push failed: {e}"}), 502

    log.info("Download pushed for: %s", title)

    # Kick off background watcher
    job_id = str(uuid.uuid4())
    thread = threading.Thread(
        target=_watch_and_send,
        args=(title, job_id),
        daemon=True,
    )
    thread.start()

    return jsonify({"status": "queued", "job_id": job_id, "message": "Download queued. File will be emailed to Kindle when ready."})


# ── Job status store (simple in-memory) ───────────────────────────────────────
_jobs: dict[str, dict] = {}

@app.route("/api/jobs")
def list_jobs():
    return jsonify(list(_jobs.values()))

@app.route("/api/jobs/<job_id>")
def job_status(job_id):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


# ── Background: watch download dir, then email ────────────────────────────────
def _watch_and_send(title: str, job_id: str):
    _jobs[job_id] = {"id": job_id, "title": title, "status": "downloading", "message": "Waiting for download..."}

    dl_path = Path(DOWNLOAD_DIR)
    deadline = time.time() + POLL_TIMEOUT
    found_file = None

    # Snapshot existing ebook files before we start polling
    existing = _ebook_snapshot(dl_path)
    log.info("[%s] Watching %s for new ebook files (timeout %ds)", job_id, dl_path, POLL_TIMEOUT)

    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        current = _ebook_snapshot(dl_path)
        new_files = current - existing
        if new_files:
            # Prefer epub, then mobi, then anything
            for ext in [".epub", ".mobi", ".azw3", ".pdf"]:
                match = [f for f in new_files if f.suffix.lower() == ext]
                if match:
                    found_file = match[0]
                    break
            if not found_file:
                found_file = list(new_files)[0]
            break

    if not found_file:
        msg = f"Timed out after {POLL_TIMEOUT}s waiting for download."
        log.warning("[%s] %s", job_id, msg)
        _jobs[job_id] = {"id": job_id, "title": title, "status": "timeout", "message": msg}
        return

    log.info("[%s] Found file: %s", job_id, found_file)
    _jobs[job_id]["status"] = "sending"
    _jobs[job_id]["message"] = f"Sending {found_file.name} to Kindle..."

    # Wait a moment to ensure file is fully written
    time.sleep(3)

    try:
        _send_to_kindle(found_file, title)
        _jobs[job_id] = {"id": job_id, "title": title, "status": "done", "message": f"Sent {found_file.name} to {KINDLE_EMAIL}"}
        log.info("[%s] Delivered %s to %s", job_id, found_file.name, KINDLE_EMAIL)
    except Exception as e:
        msg = f"Email failed: {e}"
        log.exception("[%s] %s", job_id, msg)
        _jobs[job_id] = {"id": job_id, "title": title, "status": "error", "message": msg}


def _ebook_snapshot(path: Path) -> set[Path]:
    """Return set of all ebook files recursively under path."""
    result = set()
    try:
        for p in path.rglob("*"):
            if p.is_file() and p.suffix.lower() in EBOOK_EXTENSIONS:
                result.add(p)
    except Exception:
        pass
    return result


def _send_to_kindle(filepath: Path, title: str):
    msg = MIMEMultipart()
    msg["From"]    = SMTP_FROM or SMTP_USER
    msg["To"]      = KINDLE_EMAIL
    msg["Subject"] = "convert"   # Kindle converts epub->mobi when subject is "convert"

    msg.attach(MIMEText(f"Delivery of: {title}", "plain"))

    part = MIMEBase("application", "octet-stream")
    with open(filepath, "rb") as f:
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filepath.name}"')
    msg.attach(part)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.sendmail(SMTP_FROM or SMTP_USER, KINDLE_EMAIL, msg.as_string())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
