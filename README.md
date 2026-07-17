# 🎵 Coco Music — Playlist Downloader

A local web app that lets you download music from **Spotify**, **Apple Music**, **YouTube**, or by searching a song name — and saves everything as high-quality **320 kbps MP3** files directly to your computer.

> ⚠️ **Educational Purpose Only** — See disclaimer at the bottom.

---

## Screenshots

| Input a playlist URL | Live download progress | Downloaded files |
|---|---|---|
| Paste any Spotify / Apple Music / YouTube URL | Real-time output per track | All MP3s listed with size & date |

---

## Features

- 🎧 Supports **Spotify playlists & albums**
- 🍎 Supports **Apple Music playlists & albums**
- ▶️ Supports **YouTube videos & playlists**
- 🔍 **Search by song/artist name** (no URL needed)
- ⚡ **Parallel downloads** — higher default concurrency for faster batch downloads
- 📁 All files saved to a local `downloads/` folder
- 📊 **Live progress** streamed to the browser in real-time
- 🎨 Dark responsive UI — works on desktop and mobile

---

## Requirements

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.9+ | Runtime |
| FFmpeg | Any recent | Audio conversion |
| spotdl | 4.x | Spotify & Apple Music |
| yt-dlp | Latest | YouTube & search |
| Flask | 3.x | Web server |

---

## Installation

### 1. Clone the repository
```bash
git clone https://github.com/your-username/coco-music.git
cd coco-music
```

### 2. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 3. Install FFmpeg

**Option A — Let spotdl handle it (easiest):**
```bash
spotdl --download-ffmpeg
```

**Option B — Windows (winget):**
```bash
winget install Gyan.FFmpeg
```

**Option C — macOS:**
```bash
brew install ffmpeg
```

**Option D — Linux:**
```bash
sudo apt install ffmpeg
```

### 4. Run the app
```bash
python app.py
```

### Optional: tune concurrency for your network/CPU
```bash
# Windows PowerShell
$env:SPOTDL_THREADS="16"
$env:SPOTDL_RETRY_THREADS="6"
$env:SPOTDL_MAX_RETRIES="10"
$env:YTDLP_CONCURRENT_FRAGMENTS="16"
python app.py
```

```bash
# macOS / Linux
SPOTDL_THREADS=16 SPOTDL_RETRY_THREADS=6 SPOTDL_MAX_RETRIES=10 YTDLP_CONCURRENT_FRAGMENTS=16 python app.py
```

Notes:
- `SPOTDL_THREADS` controls how many tracks `spotdl` processes in parallel (Spotify/Apple).
- `SPOTDL_RETRY_THREADS` is used automatically when request failures are detected.
- `SPOTDL_MAX_RETRIES` controls Spotify metadata retry attempts.
- `YTDLP_CONCURRENT_FRAGMENTS` controls per-track fragment concurrency for `yt-dlp`.
- Both values are clamped to `1..64`.

Open **http://localhost:5000** in your browser.

---

## Usage

1. Paste a URL or type a song/artist name into the input box
2. Click **Download**
3. Watch the live output as each track downloads
4. Find your MP3 files in the `downloads/` folder
5. Copy the folder to your pen drive

### Supported URL formats

```
https://open.spotify.com/playlist/...
https://open.spotify.com/album/...
https://music.apple.com/playlist/...
https://music.apple.com/album/...
https://www.youtube.com/playlist?list=...
https://www.youtube.com/watch?v=...
Adele Hello              ← plain text search also works
```

---

## Project Structure

```
downloader/
├── app.py               # Flask backend & download logic
├── requirements.txt     # Python dependencies
├── templates/
│   └── index.html       # Frontend UI
├── static/
│   ├── css/style.css    # Styles
│   └── js/script.js     # Frontend logic
└── downloads/           # MP3 files saved here
```

---

## Credits & Open-Source Libraries Used

This project is built on top of the following open-source tools and libraries. Full credit goes to their respective authors and contributors.

| Project | Repository | License | Purpose |
|---|---|---|---|
| **spotdl** | [github.com/spotDL/spotify-downloader](https://github.com/spotDL/spotify-downloader) | MIT | Spotify & Apple Music downloading |
| **yt-dlp** | [github.com/yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense | YouTube downloading & audio extraction |
| **Flask** | [github.com/pallets/flask](https://github.com/pallets/flask) | BSD-3-Clause | Python web framework |
| **Flask-CORS** | [github.com/corydolphin/flask-cors](https://github.com/corydolphin/flask-cors) | MIT | Cross-origin request handling |
| **FFmpeg** | [ffmpeg.org](https://ffmpeg.org) / [github.com/FFmpeg/FFmpeg](https://github.com/FFmpeg/FFmpeg) | LGPL-2.1+ | Audio encoding & conversion |
| **Inter Font** | [github.com/rsms/inter](https://github.com/rsms/inter) | OFL-1.1 | UI typography |

---

## Disclaimer & Legal Notice

> ### ⚠️ For Educational Purposes Only
>
> This project was created **strictly for educational and personal learning purposes** to demonstrate how Python web applications, server-sent events, and command-line tool integration work.
>
> - This project is **NOT intended for commercial use**.
> - This project is **NOT affiliated with** Spotify, Apple, YouTube, or any music rights holder.
> - Downloading copyrighted music without the rights holder's permission **may be illegal** in your country.
> - The author(s) of this repository are **not responsible** for any misuse of this software.
> - You are solely responsible for ensuring your use complies with the **Terms of Service** of Spotify, Apple Music, YouTube, and applicable copyright law.
>
> If you enjoy an artist's music, **please support them** by purchasing their music or subscribing to a licensed streaming service.

---

## License

This repository is for **educational and personal use only**. No commercial use permitted.
