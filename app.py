#!/usr/bin/env python3
"""
وب‌اپ ترجمه زیرنویس انیمه
Flask backend with real-time translation
"""
import os
import json
import uuid
import threading
from flask import Flask, render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename
from srt_parser import parse_srt, blocks_to_srt
from ssa_parser import parse_ass, blocks_to_ass, is_ass_filename
from translator import (
    translate_subtitles, load_config, save_config,
    get_api_key, get_all_api_keys
)

app = Flask(__name__)
app.secret_key = os.urandom(24)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ذخیره وضعیت ترجمه در حافظه
translation_jobs = {}


@app.route("/")
def index():
    return render_template("index.html", config=load_config())


@app.route("/api/config", methods=["GET"])
def get_config():
    config = load_config()
    # مخفی کردن کلیدها
    safe_config = config.copy()
    safe_config["api_keys"] = [k[:8] + "..." + k[-4:] if len(k) > 12 else "***" for k in config.get("api_keys", [])]
    safe_config["has_api_key"] = bool(get_api_key())
    return jsonify(safe_config)


@app.route("/api/config", methods=["POST"])
def update_config():
    data = request.json
    config = load_config()

    if "api_keys" in data:
        config["api_keys"] = data["api_keys"]
    if "base_url" in data:
        config["base_url"] = data["base_url"]
    if "default_model" in data:
        config["default_model"] = data["default_model"]
    if "batch_size" in data:
        config["batch_size"] = int(data["batch_size"])

    save_config(config)
    return jsonify({"ok": True, "message": "تنظیمات ذخیره شد"})


@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "فایلی ارسال نشد"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "نام فایل خالی است"}), 400

    if not file.filename.lower().endswith(('.srt', '.ass', '.ssa')):
        return jsonify({"error": "فقط فایل SRT و ASS/SSA پشتیبانی میشود"}), 400

    # ذخیره فایل
    job_id = str(uuid.uuid4())[:8]
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_DIR, f"{job_id}_{filename}")
    file.save(filepath)

    # پارس کردن (تشخیص فرمت از روی پسوند)
    filetype = "ass" if is_ass_filename(filename) else "srt"
    header = ""
    try:
        with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
            content = f.read()
        if filetype == "ass":
            header, blocks, _ = parse_ass(content)
        else:
            blocks = parse_srt(content)
    except Exception as e:
        return jsonify({"error": f"خطا در خواندن فایل: {str(e)}"}), 400

    if not blocks:
        return jsonify({"error": "فایل خالی یا نامعتبر است"}), 400

    # ذخیره در حافظه
    translation_jobs[job_id] = {
        "blocks": blocks,
        "filename": filename,
        "filepath": filepath,
        "filetype": filetype,
        "header": header,
        "status": "uploaded",
        "progress": 0,
        "translated_count": 0,
        "total_lines": len(blocks)
    }

    # برگرداندن پیش‌نمایش (۲۰ خط اول)
    preview = []
    for b in blocks[:20]:
        preview.append({
            "index": b.index,
            "timestamp": b.timestamp,
            "text": b.text,
            "translation": "",
            "translated": False
        })

    return jsonify({
        "ok": True,
        "job_id": job_id,
        "filename": filename,
        "filetype": filetype,
        "total_lines": len(blocks),
        "preview": preview
    })


@app.route("/api/translate", methods=["POST"])
def start_translation():
    data = request.json
    job_id = data.get("job_id")

    if not job_id or job_id not in translation_jobs:
        return jsonify({"error": "کار یافت نشد"}), 404

    job = translation_jobs[job_id]

    if job["status"] == "translating":
        return jsonify({"error": "ترجمه در حال انجام است"}), 400

    api_key = data.get("api_key") or get_api_key()
    model = data.get("model") or load_config().get("default_model", "gpt-4o-mini")
    base_url = data.get("base_url") or load_config().get("base_url", "https://api.openai.com/v1")
    batch_size = int(data.get("batch_size") or load_config().get("batch_size", 20))

    if not api_key:
        return jsonify({"error": "کلید API تنظیم نشده"}), 400

    job["status"] = "translating"
    job["progress"] = 0
    job["translated_count"] = 0

    def progress_callback(current, total, translated, total_lines, error=None):
        job["progress"] = int((current / total) * 100) if total > 0 else 0
        job["translated_count"] = translated
        if error:
            job["status"] = "error"
            job["error"] = error
        elif current >= total:
            job["status"] = "completed"
            job["progress"] = 100

    def run_translation():
        try:
            translate_subtitles(
                blocks=job["blocks"],
                api_key=api_key,
                model=model,
                base_url=base_url,
                batch_size=batch_size,
                progress_callback=progress_callback
            )
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)

    thread = threading.Thread(target=run_translation)
    thread.daemon = True
    thread.start()

    return jsonify({"ok": True, "message": "ترجمه شروع شد"})


@app.route("/api/status/<job_id>")
def get_status(job_id):
    if job_id not in translation_jobs:
        return jsonify({"error": "کار یافت نشد"}), 404

    job = translation_jobs[job_id]
    return jsonify({
        "status": job["status"],
        "progress": job["progress"],
        "translated_count": job["translated_count"],
        "total_lines": job["total_lines"],
        "error": job.get("error")
    })


@app.route("/api/preview/<job_id>")
def get_preview(job_id):
    if job_id not in translation_jobs:
        return jsonify({"error": "کار یافت نشد"}), 404

    job = translation_jobs[job_id]
    page = int(request.args.get("page", 0))
    per_page = int(request.args.get("per_page", 50))
    start = page * per_page
    end = start + per_page

    items = []
    for b in job["blocks"][start:end]:
        items.append({
            "index": b.index,
            "timestamp": b.timestamp,
            "text": b.text,
            "translation": b.translation,
            "translated": b.translated
        })

    return jsonify({
        "items": items,
        "total": len(job["blocks"]),
        "page": page,
        "per_page": per_page,
        "total_pages": (len(job["blocks"]) + per_page - 1) // per_page
    })


@app.route("/api/edit/<job_id>", methods=["POST"])
def edit_translation(job_id):
    if job_id not in translation_jobs:
        return jsonify({"error": "کار یافت نشد"}), 404

    data = request.json
    index = data.get("index")
    translation = data.get("translation")

    job = translation_jobs[job_id]
    for b in job["blocks"]:
        if b.index == index:
            b.translation = translation
            b.translated = True
            break

    return jsonify({"ok": True})


@app.route("/api/download/<job_id>")
def download_sub(job_id):
    if job_id not in translation_jobs:
        return jsonify({"error": "کار یافت نشد"}), 404

    job = translation_jobs[job_id]
    filetype = job.get("filetype", "srt")

    if filetype == "ass":
        content = blocks_to_ass(job.get("header", ""), job["blocks"])
        ext = os.path.splitext(job["filename"])[1].lower() or ".ass"
        if ext not in (".ass", ".ssa"):
            ext = ".ass"
        mime = 'text/plain'
    else:
        content = blocks_to_srt(job["blocks"])
        ext = ".srt"
        mime = 'text/plain'

    # ذخیره موقت
    output_path = os.path.join(UPLOAD_DIR, f"{job_id}_translated{ext}")
    with open(output_path, 'w', encoding='utf-8-sig') as f:
        f.write(content)

    original_name = os.path.splitext(job["filename"])[0]
    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"{original_name}_fa{ext}",
        mimetype=mime
    )


@app.route("/api/keys", methods=["GET"])
def list_keys():
    config = load_config()
    keys = config.get("api_keys", [])
    # مخفی کردن
    safe = []
    for i, k in enumerate(keys):
        if k and len(k) > 12:
            safe.append({"index": i, "masked": k[:8] + "..." + k[-4:], "has_key": True})
        elif k:
            safe.append({"index": i, "masked": "***", "has_key": True})
    return jsonify({"keys": safe})


@app.route("/api/keys", methods=["POST"])
def add_key():
    data = request.json
    key = data.get("key", "").strip()
    if not key:
        return jsonify({"error": "کلید خالی است"}), 400

    config = load_config()
    if "api_keys" not in config:
        config["api_keys"] = []
    config["api_keys"].append(key)
    save_config(config)
    return jsonify({"ok": True, "message": "کلید اضافه شد"})


@app.route("/api/keys/<int:index>", methods=["DELETE"])
def delete_key(index):
    config = load_config()
    keys = config.get("api_keys", [])
    if 0 <= index < len(keys):
        keys.pop(index)
        config["api_keys"] = keys
        save_config(config)
        return jsonify({"ok": True})
    return jsonify({"error": "کلید یافت نشد"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
