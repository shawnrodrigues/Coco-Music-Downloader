from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import subprocess
import threading
import queue
import os
import json
import re
import signal
from urllib.request import Request, urlopen
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

app = Flask(__name__)
CORS(app)

DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# In-memory store for active download sessions
progress_queues = {}
session_cancel_events = {}
session_processes = {}
session_lock = threading.Lock()


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read an int from env with safe clamping and fallback."""
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


# Tunable concurrency for faster downloads on high-bandwidth connections.
SPOTDL_THREADS = env_int("SPOTDL_THREADS", default=16, minimum=1, maximum=64)
SPOTDL_RETRY_THREADS = env_int("SPOTDL_RETRY_THREADS", default=6, minimum=1, maximum=32)
SPOTDL_MAX_RETRIES = env_int("SPOTDL_MAX_RETRIES", default=10, minimum=1, maximum=20)
SPOTDL_ENABLE_OFFICIAL_API_FALLBACK = os.environ.get("SPOTDL_ENABLE_OFFICIAL_API_FALLBACK", "1") != "0"
YTDLP_CONCURRENT_FRAGMENTS = env_int("YTDLP_CONCURRENT_FRAGMENTS", default=16, minimum=1, maximum=64)


def detect_source(url: str) -> str:
    url_lower = url.lower()
    if "spotify.com" in url_lower:
        return "spotify"
    if "music.apple.com" in url_lower:
        return "apple"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    return "search"


def normalize_input(url_or_query: str, source: str) -> str:
    """Normalize known URL patterns that can accidentally force single-track downloads."""
    if source not in ("apple", "spotify"):
        return url_or_query

    try:
        parsed = urlparse(url_or_query)
    except Exception:
        return url_or_query

    netloc_lower = parsed.netloc.lower()
    path_lower = parsed.path.lower()

    if source == "apple":
        if "music.apple.com" not in netloc_lower:
            return url_or_query
        if "/playlist/" not in path_lower and "/album/" not in path_lower:
            return url_or_query

        query_items = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() != "i"]
        normalized = parsed._replace(query=urlencode(query_items, doseq=True))
        return urlunparse(normalized)

    # Spotify share URLs often include query params like ?si=...&utm_source=...
    # which are unnecessary for playlist/album resolution.
    if source == "spotify":
        if "spotify.com" not in netloc_lower:
            return url_or_query
        if "/playlist/" in path_lower or "/album/" in path_lower or "/track/" in path_lower:
            return urlunparse(parsed._replace(query="", fragment=""))

    return url_or_query


def is_apple_playlist_url(url_or_query: str) -> bool:
    try:
        parsed = urlparse(url_or_query)
    except Exception:
        return False
    return "music.apple.com" in parsed.netloc.lower() and "/playlist/" in parsed.path.lower()


def decode_json_string_fragment(value: str) -> str:
    """Decode a JSON string fragment like \u0026 and escaped quotes."""
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value


def extract_apple_playlist_queries(playlist_url: str) -> list[str]:
    """Extract artist-title search queries from Apple Music playlist page metadata."""
    parsed = urlparse(playlist_url)
    playlist_id = parsed.path.rstrip("/").split("/")[-1]

    req = Request(
        playlist_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        },
    )

    with urlopen(req, timeout=25) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    item_pattern = re.compile(
        rf'"id":"track-lockup - {re.escape(playlist_id)} - [^\"]+".*?'
        r'"title":"(?P<title>[^\"]+)".*?'
        r'"artistName":"(?P<artist>[^\"]+)"',
        re.DOTALL,
    )

    seen: set[str] = set()
    queries: list[str] = []

    for match in item_pattern.finditer(html):
        title = decode_json_string_fragment(match.group("title")).strip()
        artist = decode_json_string_fragment(match.group("artist")).strip()
        if not title:
            continue

        query = f"{artist} - {title}" if artist else title
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(query)

    return queries


def build_command(
    url_or_query: str,
    source: str,
    spotdl_audio: list[str] | None = None,
    spotdl_threads: int | None = None,
    spotdl_retries: int | None = None,
    use_official_api: bool = False,
) -> list[str]:
    out = str(DOWNLOADS_DIR / "%(title)s.%(ext)s")

    if source in ("spotify", "apple"):
        audio_sources = spotdl_audio or ["youtube", "youtube-music"]
        threads = spotdl_threads or SPOTDL_THREADS
        retries = spotdl_retries or SPOTDL_MAX_RETRIES
        cmd = [
            "spotdl",
            url_or_query,
            "--output", str(DOWNLOADS_DIR),
            "--format", "mp3",
            "--bitrate", "320k",
            "--threads", str(threads),
            "--max-retries", str(retries),
            "--audio", *audio_sources,
            "--simple-tui",
            "--log-level", "INFO",
        ]
        if use_official_api:
            cmd.append("--use-official-api")
        return cmd

    yt_base = [
        "yt-dlp",
        "--format", "bestaudio/best",
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--concurrent-fragments", str(YTDLP_CONCURRENT_FRAGMENTS),
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

    if "failed to complete request" in line.lower() or "reinitializing song" in line.lower():
        return {"type": "warning", "message": line}

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


def run_command_stream(
    session_id: str,
    cmd: list[str],
    pq: queue.Queue,
    tracker_state: dict,
    env: dict,
) -> tuple[int, list[str]]:
    """Run a subprocess and stream structured progress events to the queue."""
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
        creationflags=creationflags,
    )

    with session_lock:
        session_processes[session_id] = process

    lines: list[str] = []
    try:
        for raw_line in iter(process.stdout.readline, ""):
            stripped = raw_line.strip()
            if not stripped:
                continue

            lines.append(stripped)
            tracker_event = extract_tracker(stripped, tracker_state)
            if tracker_event:
                pq.put(tracker_event)

            pq.put(parse_line(stripped))

        process.wait()
        return process.returncode, lines
    finally:
        with session_lock:
            session_processes.pop(session_id, None)


def stop_session(session_id: str) -> bool:
    with session_lock:
        cancel_event = session_cancel_events.get(session_id)
        process = session_processes.get(session_id)

    if cancel_event:
        cancel_event.set()

    if process and process.poll() is None:
        if os.name == "nt":
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:
                process.terminate()
        else:
            process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
        return True

    return False


def needs_spotdl_fallback(output_lines: list[str]) -> bool:
    merged = "\n".join(output_lines).lower()
    return (
        "audioprovidererror" in merged
        or "yt-dlp download error" in merged
        or "failed to complete request" in merged
    )


def spotdl_request_failures(output_lines: list[str]) -> int:
    return sum(1 for line in output_lines if "failed to complete request" in line.lower())


def is_spotify_rate_limited(output_lines: list[str]) -> bool:
    merged = "\n".join(output_lines).lower()
    return "reached a rate/request limit" in merged


def needs_official_api_retry(output_lines: list[str]) -> bool:
    merged = "\n".join(output_lines).lower()
    return (
        "failed to complete request" in merged
        or "requesterror" in merged
        or "could not get playlist hashes" in merged
        or "spotapi" in merged
    ) and not is_spotify_rate_limited(output_lines)


def run_apple_playlist_fallback(
    session_id: str,
    playlist_url: str,
    pq: queue.Queue,
    cancel_event: threading.Event,
    env: dict,
) -> bool:
    """Download Apple playlist tracks by scraping page metadata and searching YouTube."""
    try:
        queries = extract_apple_playlist_queries(playlist_url)
    except Exception as exc:
        pq.put({"type": "error", "message": f"Could not read Apple playlist tracks: {exc}"})
        return False

    if not queries:
        pq.put({
            "type": "error",
            "message": "Could not extract tracks from this Apple playlist URL.",
        })
        return False

    total = len(queries)
    completed = 0
    failed = 0
    pq.put({"type": "info", "message": f"Apple playlist detected: {total} tracks found."})
    pq.put({"type": "tracker", "current": 0, "total": total, "title": ""})

    for idx, query in enumerate(queries, start=1):
        if cancel_event.is_set():
            break

        pq.put({"type": "info", "message": f"[{idx}/{total}] Searching: {query}"})
        item_tracker_state = {"total": 0, "downloaded": 0}
        cmd = build_command(query, "search")
        return_code, _ = run_command_stream(session_id, cmd, pq, item_tracker_state, env)

        if return_code == 0:
            completed += 1
        else:
            failed += 1
            pq.put({"type": "warning", "message": f"Failed: {query}"})

        pq.put({"type": "tracker", "current": idx, "total": total, "title": query})

    if cancel_event.is_set():
        pq.put({"type": "stopped", "message": "Download stopped by user."})
        return True

    if completed == 0:
        pq.put({"type": "error", "message": "No tracks were downloaded from Apple playlist fallback."})
        return False

    if failed > 0:
        pq.put({"type": "done", "message": f"Finished with partial success: {completed}/{total} tracks."})
    else:
        pq.put({"type": "done", "message": "All downloads finished successfully!"})
    return True


def run_download(session_id: str, url_or_query: str, pq: queue.Queue, cancel_event: threading.Event):
    source = detect_source(url_or_query)
    normalized_input = normalize_input(url_or_query, source)

    if normalized_input != url_or_query:
        if source == "apple":
            pq.put({"type": "info", "message": "Detected Apple track parameter; using full playlist/album URL."})
        elif source == "spotify":
            pq.put({"type": "info", "message": "Cleaned Spotify share URL parameters for better reliability."})

    pq.put({"type": "info", "message": f"Detected source: {source.upper()}"})
    pq.put({"type": "info", "message": "Starting download…"})

    if cancel_event.is_set():
        pq.put({"type": "stopped", "message": "Download stopped by user."})
        pq.put(None)
        return

    cmd = build_command(normalized_input, source)
    tracker_state = {"total": 0, "downloaded": 0}

    # Force unbuffered output from child Python processes (spotdl / yt-dlp)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        if source == "apple" and is_apple_playlist_url(normalized_input):
            handled = run_apple_playlist_fallback(session_id, normalized_input, pq, cancel_event, env)
            if handled:
                return

        return_code, output_lines = run_command_stream(session_id, cmd, pq, tracker_state, env)

        request_failures = spotdl_request_failures(output_lines)
        missing_tracks = tracker_state["total"] > 0 and tracker_state["downloaded"] < tracker_state["total"]
        should_retry_missing = source in ("spotify", "apple") and request_failures >= 3 and missing_tracks

        if should_retry_missing and not cancel_event.is_set():
            pq.put({
                "type": "info",
                "message": (
                    "Detected repeated request failures. Retrying with safer settings "
                    f"(threads={SPOTDL_RETRY_THREADS}, retries={max(SPOTDL_MAX_RETRIES, 8)})."
                ),
            })
            retry_tracker_state = {"total": 0, "downloaded": 0}
            retry_cmd = build_command(
                normalized_input,
                source,
                spotdl_audio=["youtube", "youtube-music"],
                spotdl_threads=SPOTDL_RETRY_THREADS,
                spotdl_retries=max(SPOTDL_MAX_RETRIES, 8),
            )
            return_code, retry_lines = run_command_stream(session_id, retry_cmd, pq, retry_tracker_state, env)
            output_lines.extend(retry_lines)

        if (
            return_code != 0
            and not cancel_event.is_set()
            and source == "spotify"
            and SPOTDL_ENABLE_OFFICIAL_API_FALLBACK
            and needs_official_api_retry(output_lines)
        ):
            pq.put({
                "type": "info",
                "message": "Metadata backend failed. Retrying with Spotify official API mode...",
            })
            retry_tracker_state = {"total": 0, "downloaded": 0}
            retry_cmd = build_command(
                normalized_input,
                source,
                spotdl_audio=["youtube", "youtube-music"],
                spotdl_threads=SPOTDL_RETRY_THREADS,
                spotdl_retries=max(SPOTDL_MAX_RETRIES, 8),
                use_official_api=True,
            )
            return_code, retry_lines = run_command_stream(session_id, retry_cmd, pq, retry_tracker_state, env)
            output_lines.extend(retry_lines)

        if (
            return_code != 0
            and not cancel_event.is_set()
            and source in ("spotify", "apple")
            and needs_spotdl_fallback(output_lines)
        ):
            pq.put({"type": "info", "message": "Retrying with alternate audio provider (YouTube)…"})
            retry_tracker_state = {"total": 0, "downloaded": 0}
            retry_cmd = build_command(
                normalized_input,
                source,
                spotdl_audio=["youtube"],
                spotdl_threads=SPOTDL_RETRY_THREADS,
                spotdl_retries=max(SPOTDL_MAX_RETRIES, 8),
            )
            return_code, retry_lines = run_command_stream(session_id, retry_cmd, pq, retry_tracker_state, env)
            output_lines.extend(retry_lines)

        if cancel_event.is_set():
            pq.put({"type": "stopped", "message": "Download stopped by user."})
        elif return_code == 0:
            pq.put({"type": "done", "message": "All downloads finished successfully!"})
        else:
            pq.put({"type": "error", "message": f"Process exited with code {return_code}."})
            if source == "spotify" and is_spotify_rate_limited(output_lines):
                pq.put({
                    "type": "error",
                    "message": (
                        "Spotify API rate limit reached. Wait for reset, or set "
                        "SPOTDL_ENABLE_OFFICIAL_API_FALLBACK=0 to avoid official API retry."
                    ),
                })
            if any("yt-dlp" in line.lower() for line in output_lines):
                pq.put({
                    "type": "error",
                    "message": "Tip: update spotdl/yt-dlp (pip install -U spotdl yt-dlp) and try again.",
                })

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
        with session_lock:
            session_cancel_events.pop(session_id, None)
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
    cancel_event = threading.Event()
    progress_queues[session_id] = pq
    with session_lock:
        session_cancel_events[session_id] = cancel_event

    t = threading.Thread(target=run_download, args=(session_id, url_or_query, pq, cancel_event), daemon=True)
    t.start()

    return jsonify({"session_id": session_id})


@app.route("/stop/<session_id>", methods=["POST"])
def stop_download(session_id: str):
    if session_id not in progress_queues and session_id not in session_cancel_events:
        return jsonify({"error": "Invalid session."}), 404

    stopped = stop_session(session_id)
    pq = progress_queues.get(session_id)
    if pq:
        pq.put({"type": "info", "message": "Stop requested. Finishing current operation..."})

    return jsonify({"status": "stopping" if stopped else "already_stopped"})


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
