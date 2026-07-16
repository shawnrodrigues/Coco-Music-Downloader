from flask import Flask, render_template, request, jsonify, Response, stream_with_context, stream_with_context
from flask_cors import CORS
import subprocess
import threading
import queue
import os
import json
import re
from pathlib import Path

app = Flask(__name__)
CORS(app)

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# In-memory store for active download sessions
progress_queues = {}


def detect_source(url: str) -> str:
    url_lower = url.lower()
    if "spotify.com" in url_lower:
        return "spotify"
    if "music.apple.com" in url_lower:
        return "apple"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    return "search"


def build_command(url_or_query: str, source: str) -> list[str]:
    out = str(DOWNLOADS_DIR / "%(title)s.%(ext)s")

    if source in ("spotify", "apple"):
        return [
            "spotdl",
            url_or_query,
            "--output", str(DOWNLOADS_DIR),
            "--format", "mp3",
            "--bitrate", "320k",
            "--threads", "8",
            "--log-level", "INFO",
        ]

    yt_base = [
        "yt-dlp",
        "--format", "bestaudio/best",
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--concurrent-fragments", "8",
        "--no-embed-thumbnail",
        "--newline",
        "--progress",
        "--no-part",
        "-o", out,
    ]

    if source == "youtube":
        return yt_base + [url_or_query]

    # plain text search → search YouTube
    return yt_base + [f"ytsearch1:{url_or_query}"]


def parse_line(line: str) -> dict:
    """Turn raw tool output into a structured progress event."""
    m = re.search(r"\[download\]\s+([\d.]+)%", line)
    if m:
        return {"type": "progress", "percent": float(m.group(1)), "message": line}

    if "[ExtractAudio]" in line or "[ffmpeg]" in line:
        return {"type": "converting", "message": line}

    if "Downloaded" in line or "Skipping" in line:
        return {"type": "track", "message": line}

    if "error" in line.lower() or "failed" in line.lower():
        return {"type": "error", "message": line}

    return {"type": "log", "message": line}


def extract_tracker(line: str, state: dict) -> dict | None:
    """
    Parse tracker info from a line of output.
    Returns a tracker event dict or None.
    state keys: total, downloaded
    """
    # spotdl: "Downloading 25 songs"
    m = re.search(r"Downloading (\d+) songs?", line, re.IGNORECASE)
    if m:
        state["total"] = int(m.group(1))
        return {"type": "tracker", "current": state["downloaded"], "total": state["total"], "title": ""}

    # spotdl: Downloaded "Song Name" by Artist  /  Skipping "Song Name"
    m = re.search(r'(?:Downloaded|Skipping)\s+"(.+?)"', line)
    if m:
        state["downloaded"] += 1
        return {"type": "tracker", "current": state["downloaded"], "total": state["total"], "title": m.group(1)}

    # yt-dlp playlist: [download] Downloading item 3 of 25
    m = re.search(r"\[download\] Downloading item (\d+) of (\d+)", line)
    if m:
        state["total"] = int(m.group(2))
        state["downloaded"] = int(m.group(1)) - 1
        return {"type": "tracker", "current": state["downloaded"], "total": state["total"], "title": ""}

    # yt-dlp: audio extracted → one track done
    m = re.search(r"\[ExtractAudio\] Destination:\s*(.+)", line)
    if m:
        state["downloaded"] += 1
        title = Path(m.group(1).strip()).stem
        return {"type": "tracker", "current": state["downloaded"], "total": state["total"], "title": title}

    # yt-dlp single video title
    m = re.search(r"\[info\] (.+): Downloading", line)
    if m and state["total"] <= 1:
        state["total"] = 1
        return {"type": "tracker", "current": 0, "total": 1, "title": m.group(1)}

    return None


def run_download(session_id: str, url_or_query: str, pq: queue.Queue):
    source = detect_source(url_or_query)
    pq.put({"type": "info", "message": f"Detected source: {source.upper()}"})
    pq.put({"type": "info", "message": "Starting download…"})

    cmd = build_command(url_or_query, source)
    tracker_state = {"total": 0, "downloaded": 0}

    # Force unbuffered output from child Python processes (spotdl / yt-dlp)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )

        for raw_line in iter(process.stdout.readline, ""):
            stripped = raw_line.strip()
            if not stripped:
                continue

            tracker_event = extract_tracker(stripped, tracker_state)
            if tracker_event:
                pq.put(tracker_event)

            pq.put(parse_line(stripped))

        process.wait()

        if process.returncode == 0:
            pq.put({"type": "done", "message": "All downloads finished successfully!"})
        else:
            pq.put({"type": "error", "message": f"Process exited with code {process.returncode}."})

    except FileNotFoundError:
        tool = "spotdl" if source in ("spotify", "apple") else "yt-dlp"
        pq.put({
            "type": "error",
            "message": (
                f"'{tool}' not found. "
                "Run: pip install spotdl yt-dlp  and also install FFmpeg."
            ),
        })
    except Exception as exc:
        pq.put({"type": "error", "message": f"Unexpected error: {exc}"})
    finally:
        pq.put(None)  # sentinel → stream ends


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/download", methods=["POST"])
def start_download():
    data = request.get_json(silent=True) or {}
    url_or_query = (data.get("url") or "").strip()

    if not url_or_query:
        return jsonify({"error": "No URL or search query provided."}), 400

    session_id = os.urandom(8).hex()
    pq: queue.Queue = queue.Queue()
    progress_queues[session_id] = pq

    t = threading.Thread(target=run_download, args=(session_id, url_or_query, pq), daemon=True)
    t.start()

    return jsonify({"session_id": session_id})


@app.route("/progress/<session_id>")
def progress_stream(session_id: str):
    def generate():
        if session_id not in progress_queues:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Invalid session.'})}\n\n"
            return

        pq = progress_queues[session_id]
        try:
            while True:
                try:
                    item = pq.get(timeout=15)
                except queue.Empty:
                    # heartbeat — keeps connection alive through proxies/browser timeouts
                    yield ": heartbeat\n\n"
                    continue
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            progress_queues.pop(session_id, None)
            yield f"data: {json.dumps({'type': 'end'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/files")
def list_files():
    audio_exts = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus"}
    files = []
    for f in DOWNLOADS_DIR.iterdir():
        if f.suffix.lower() in audio_exts:
            stat = f.stat()
            files.append({
                "name": f.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
    files.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify(files)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
