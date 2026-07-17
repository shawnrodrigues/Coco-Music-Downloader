/* ===== Platform detection ===== */
const PLATFORM_ICONS = {
  spotify: `<svg viewBox="0 0 24 24" width="18" height="18" fill="#1ed760"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>`,
  apple:   `<svg viewBox="0 0 24 24" width="18" height="18" fill="#fc3c44"><path d="M12.152 6.896c-.948 0-2.415-1.078-3.96-1.04-2.04.027-3.91 1.183-4.961 3.014-2.117 3.675-.546 9.103 1.519 12.09 1.013 1.454 2.208 3.09 3.792 3.039 1.52-.065 2.09-.987 3.935-.987 1.831 0 2.35.987 3.96.948 1.637-.026 2.676-1.48 3.676-2.948 1.156-1.688 1.636-3.325 1.662-3.415-.039-.013-3.182-1.221-3.22-4.857-.026-3.04 2.48-4.494 2.597-4.559-1.429-2.09-3.623-2.324-4.39-2.376-2-.156-3.675 1.09-4.61 1.09zM15.53 3.83c.843-1.012 1.4-2.427 1.245-3.83-1.207.052-2.662.805-3.532 1.818-.78.896-1.454 2.338-1.273 3.714 1.338.104 2.715-.688 3.559-1.701"/></svg>`,
  youtube: `<svg viewBox="0 0 24 24" width="18" height="18" fill="#ff4e45"><path d="M23.495 6.205a3.007 3.007 0 0 0-2.088-2.088c-1.87-.501-9.396-.501-9.396-.501s-7.507-.01-9.396.501A3.007 3.007 0 0 0 .527 6.205a31.247 31.247 0 0 0-.522 5.805 31.247 31.247 0 0 0 .522 5.783 3.007 3.007 0 0 0 2.088 2.088c1.868.502 9.396.502 9.396.502s7.506 0 9.396-.502a3.007 3.007 0 0 0 2.088-2.088 31.247 31.247 0 0 0 .5-5.783 31.247 31.247 0 0 0-.5-5.805zM9.609 15.601V8.408l6.264 3.602z"/></svg>`,
  search:  `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>`,
};

function detectPlatform(value) {
  const v = value.toLowerCase();
  if (v.includes('spotify.com'))     return 'spotify';
  if (v.includes('music.apple.com')) return 'apple';
  if (v.includes('youtube.com') || v.includes('youtu.be')) return 'youtube';
  return 'search';
}

/* ===== DOM refs ===== */
const urlInput      = document.getElementById('urlInput');
const downloadBtn   = document.getElementById('downloadBtn');
const downloadText  = document.getElementById('downloadBtnText');
const stopBtn       = document.getElementById('stopBtn');
const clearBtn      = document.getElementById('clearBtn');
const clearLogBtn   = document.getElementById('clearLogBtn');
const progressPanel = document.getElementById('progressPanel');
const progressLog   = document.getElementById('progressLog');
const platformIcon  = document.getElementById('platformIcon');
const inputWrapper  = document.getElementById('inputWrapper');
const tracker       = document.getElementById('tracker');
const trackerCurrent= document.getElementById('trackerCurrent');
const trackerTotal  = document.getElementById('trackerTotal');
const trackerBar    = document.getElementById('trackerBar');
const trackerTitle  = document.getElementById('trackerTitle');
const refreshBtn    = document.getElementById('refreshBtn');
const filesList     = document.getElementById('filesList');

let activeSource = null;  // active EventSource
let activeSessionId = null;

/* ===== Input handling ===== */
urlInput.addEventListener('input', () => {
  const val = urlInput.value.trim();
  clearBtn.style.display = val ? 'flex' : 'none';
  const platform = detectPlatform(val);
  platformIcon.innerHTML = PLATFORM_ICONS[platform];
});

clearBtn.addEventListener('click', () => {
  urlInput.value = '';
  clearBtn.style.display = 'none';
  platformIcon.innerHTML = PLATFORM_ICONS['search'];
  urlInput.focus();
});

urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') downloadBtn.click();
});

clearLogBtn.addEventListener('click', () => {
  progressLog.innerHTML = '';
});

/* ===== Append log line ===== */
let currentProgressBar = null;

function appendLog(type, message) {
  // For progress events, update or create a progress bar row
  if (type === 'progress') {
    const percent = parseFloat(message.match(/([\d.]+)%/)?.[1] || 0);
    if (!currentProgressBar) {
      const row = document.createElement('div');
      row.className = 'log-line log-progress';
      row.innerHTML = `
        <span class="log-dot"></span>
        <div style="flex:1;">
          <span class="log-text">${escapeHtml(message)}</span>
          <div class="progress-bar-wrap"><div class="progress-bar-fill" style="width:${percent}%"></div></div>
        </div>`;
      progressLog.appendChild(row);
      currentProgressBar = row;
    } else {
      currentProgressBar.querySelector('.log-text').textContent = message;
      currentProgressBar.querySelector('.progress-bar-fill').style.width = percent + '%';
    }
    if (percent >= 100) currentProgressBar = null;
    progressLog.scrollTop = progressLog.scrollHeight;
    return;
  }

  currentProgressBar = null; // reset on any non-progress line

  const row = document.createElement('div');
  row.className = `log-line log-${type}`;
  row.innerHTML = `<span class="log-dot"></span><span class="log-text">${escapeHtml(message)}</span>`;
  progressLog.appendChild(row);
  progressLog.scrollTop = progressLog.scrollHeight;
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* ===== Download ===== */
async function requestStop(sessionId) {
  if (!sessionId) return;
  await fetch(`/stop/${sessionId}`, { method: 'POST' });
}

stopBtn.addEventListener('click', async () => {
  if (!activeSessionId) return;

  stopBtn.disabled = true;
  try {
    await requestStop(activeSessionId);
    appendLog('info', 'Stopping download...');
  } catch {
    appendLog('error', 'Could not send stop request.');
    stopBtn.disabled = false;
  }
});

downloadBtn.addEventListener('click', async () => {
  const url = urlInput.value.trim();
  if (!url) {
    urlInput.focus();
    urlInput.style.outline = '2px solid #f87171';
    setTimeout(() => urlInput.style.outline = '', 800);
    return;
  }

  // Cancel any active stream/session before starting a new one
  if (activeSource) { activeSource.close(); activeSource = null; }
  if (activeSessionId) {
    try {
      await requestStop(activeSessionId);
    } catch {
      // best effort
    }
    activeSessionId = null;
  }

  // Show panel, reset log, reset tracker
  progressPanel.style.display = 'block';
  progressLog.innerHTML = '';
  currentProgressBar = null;
  tracker.style.display = 'none';
  trackerCurrent.textContent = '0';
  trackerTotal.textContent = '—';
  trackerBar.style.width = '0%';
  trackerTitle.textContent = '';

  // Disable button
  downloadBtn.disabled = true;
  downloadText.textContent = 'Downloading…';

  let sessionId;
  try {
    const res = await fetch('/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) {
      appendLog('error', data.error || 'Failed to start download.');
      resetBtn();
      return;
    }
    sessionId = data.session_id;
    activeSessionId = sessionId;
    stopBtn.disabled = false;
  } catch (err) {
    appendLog('error', 'Could not reach the server. Is it running?');
    resetBtn();
    return;
  }

  // Open SSE stream
  const es = new EventSource(`/progress/${sessionId}`);
  activeSource = es;

  es.onmessage = (ev) => {
    const item = JSON.parse(ev.data);

    if (item.type === 'tracker') {
      tracker.style.display = 'block';
      trackerCurrent.textContent = item.current;
      if (item.total > 0) {
        trackerTotal.textContent = item.total;
        const pct = Math.round((item.current / item.total) * 100);
        trackerBar.style.width = pct + '%';
      }
      if (item.title) trackerTitle.textContent = item.title;
      return;
    }

    if (item.type === 'end') {
      es.close();
      activeSource = null;
      activeSessionId = null;
      resetBtn();
      loadFiles();
      return;
    }

    if (item.type === 'done') {
      appendLog('done', item.message);
      return;
    }

    if (item.type === 'stopped') {
      appendLog('stopped', item.message);
      return;
    }

    appendLog(item.type, item.message);
  };

  es.onerror = () => {
    // Only treat as fatal if the stream was never started or has fully ended
    if (es.readyState === EventSource.CLOSED) {
      es.close();
      activeSource = null;
      activeSessionId = null;
      resetBtn();
      loadFiles();
    }
    // If readyState is CONNECTING the browser auto-reconnects — do nothing
  };
});

function resetBtn() {
  downloadBtn.disabled = false;
  downloadText.textContent = 'Download';
  stopBtn.disabled = true;
}

/* ===== Files list ===== */
function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function formatDate(ts) {
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function getExt(name) {
  return name.split('.').pop().toLowerCase();
}

async function loadFiles() {
  refreshBtn.classList.add('spinning');
  try {
    const res = await fetch('/files');
    const files = await res.json();

    if (!files.length) {
      filesList.innerHTML = `
        <div class="files-empty">
          <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
          <p>No files downloaded yet</p>
        </div>`;
      return;
    }

    filesList.innerHTML = files.map(f => `
      <div class="file-item">
        <div class="file-icon">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
        </div>
        <div class="file-info">
          <div class="file-name" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</div>
          <div class="file-meta">${formatSize(f.size)} &nbsp;·&nbsp; ${formatDate(f.modified)}</div>
        </div>
        <span class="file-ext">${getExt(f.name)}</span>
      </div>`
    ).join('');
  } catch {
    // silently ignore
  } finally {
    refreshBtn.classList.remove('spinning');
  }
}

refreshBtn.addEventListener('click', loadFiles);

/* ===== Init ===== */
loadFiles();
