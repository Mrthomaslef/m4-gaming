#!/usr/bin/env python3
import http.server
import json
import os
import subprocess
import urllib.parse

PORT = 8765

ICON_PATH = "/Users/thomaslefevre/ES-DE/scripts/app_icon.png"
AUDIO_SWITCHER = "/Users/thomaslefevre/ES-DE/scripts/audio_switcher"
BETTERDISPLAY_CLI = "/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay"

STEAM_PROCESSES = [
    "steam_osx",
    "Steam Helper",
    "ipcserver",
    "Whisky",
    "wine64-preloader",
    "wineserver",
    "steam.exe",
    "steamwebhelper.exe",
]

EMULATOR_PROCESSES = [
    "RetroArch",
    "Ryujinx",
    "Dolphin",
    "PCSX2-v2.8.2",
    "PCSX2",
    "RPCS3",
    "Cemu",
    "Azahar",
    "PPSSPP",
    "DuckStation",
    "Flycast",
    "mGBA",
    "melonDS",
]

GAMING_PROCESSES = ["ES-DE"] + STEAM_PROCESSES + EMULATOR_PROCESSES

HTML_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="M4 Gaming">
<link rel="apple-touch-icon" sizes="512x512" href="/apple-touch-icon.png">
<link rel="apple-touch-icon-precomposed" href="/apple-touch-icon-precomposed.png">
<link rel="icon" type="image/png" href="/icon.png">
<title>M4 Gaming</title>
<style>
  :root {
    --bg-dark: #07090e;
    --card-bg: rgba(255, 255, 255, 0.06);
    --card-border: rgba(255, 255, 255, 0.12);
    --text-main: #f8fafc;
    --text-muted: #94a3b8;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; user-select: none; -webkit-user-select: none; }
  body {
    margin: 0;
    padding: calc(env(safe-area-inset-top, 20px) + 14px) 18px calc(env(safe-area-inset-bottom, 20px) + 20px) 18px;
    background-color: var(--bg-dark);
    background-image:
      radial-gradient(circle at 50% -10%, rgba(59, 130, 246, 0.3) 0%, transparent 55%),
      radial-gradient(circle at 85% 25%, rgba(99, 102, 241, 0.16) 0%, transparent 45%);
    color: var(--text-main);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  .container {
    width: 100%;
    max-width: 395px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  /* Header & App Logo */
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 2px 2px 4px 2px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 13px;
  }
  .logo-wrap {
    width: 50px;
    height: 50px;
    border-radius: 15px;
    overflow: hidden;
    box-shadow: 0 8px 24px rgba(59, 130, 246, 0.4), inset 0 0 0 1px rgba(255,255,255,0.22);
    flex-shrink: 0;
  }
  .logo-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .brand-text h1 {
    font-size: 21px;
    font-weight: 800;
    margin: 0;
    letter-spacing: -0.5px;
    background: linear-gradient(135deg, #ffffff 0%, #93c5fd 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .brand-text p {
    font-size: 12px;
    color: var(--text-muted);
    margin: 2px 0 0 0;
    font-weight: 500;
  }
  .status-pill {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 12px;
    border-radius: 999px;
    background: rgba(16, 185, 129, 0.13);
    border: 1px solid rgba(16, 185, 129, 0.3);
    font-size: 11.5px;
    font-weight: 700;
    color: #34d399;
  }
  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #10b981;
    box-shadow: 0 0 8px #10b981;
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.85); }
  }

  /* Main Action Cards */
  .main-btn {
    width: 100%;
    border-radius: 20px;
    padding: 16px 16px;
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
    transition: transform 0.14s ease, box-shadow 0.2s ease;
    text-align: left;
  }
  .main-btn:active {
    transform: scale(0.96);
  }
  .btn-tv-ready {
    border: 1px solid rgba(16, 185, 129, 0.55);
    background: linear-gradient(135deg, #059669 0%, #0d9488 50%, #2563eb 100%);
    box-shadow: 0 14px 32px -8px rgba(16, 185, 129, 0.5), inset 0 1px 1px rgba(255, 255, 255, 0.38);
  }
  .btn-esde {
    border: 1px solid rgba(96, 165, 250, 0.45);
    background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
    box-shadow: 0 12px 28px -8px rgba(37, 99, 235, 0.5), inset 0 1px 1px rgba(255, 255, 255, 0.32);
  }
  .btn-steam {
    border: 1px solid rgba(56, 189, 248, 0.35);
    background: linear-gradient(135deg, #1b2838 0%, #2a475e 100%);
    box-shadow: 0 12px 28px -8px rgba(27, 40, 56, 0.65), inset 0 1px 1px rgba(255, 255, 255, 0.2);
  }
  .btn-steam-win {
    border: 1px solid rgba(14, 165, 233, 0.35);
    background: linear-gradient(135deg, rgba(14, 165, 233, 0.22) 0%, rgba(37, 99, 235, 0.25) 100%);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
  }
  .btn-left {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .btn-icon {
    width: 46px;
    height: 46px;
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.16);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  .btn-icon svg {
    width: 25px;
    height: 25px;
    fill: #ffffff;
  }
  .btn-title {
    font-size: 16.5px;
    font-weight: 800;
    letter-spacing: -0.3px;
    display: block;
  }
  .btn-sub {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.82);
    font-weight: 500;
    margin-top: 2px;
    display: block;
  }
  .btn-arrow {
    font-size: 16px;
    font-weight: 800;
    opacity: 0.8;
    padding-left: 8px;
  }

  /* Section Cards (Display & Audio) */
  .section-card {
    border: 1px solid var(--card-border);
    border-radius: 18px;
    padding: 11px 12px;
    background: var(--card-bg);
    display: flex;
    flex-direction: column;
    gap: 9px;
  }
  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 4px;
    font-size: 11.5px;
    font-weight: 700;
    color: var(--text-muted);
    letter-spacing: 0.3px;
  }
  .section-current {
    color: #60a5fa;
    font-weight: 800;
  }
  .section-current.tv-active {
    color: #34d399;
  }
  .mode-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 9px;
  }
  .mode-btn {
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 13px;
    padding: 11px 8px;
    background: rgba(255,255,255,0.05);
    color: var(--text-main);
    font-size: 13.5px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    cursor: pointer;
    transition: transform 0.12s ease, background 0.15s ease, border-color 0.15s ease;
  }
  .mode-btn:active {
    transform: scale(0.95);
    background: rgba(255,255,255,0.14);
  }
  .mode-btn.active {
    background: rgba(59, 130, 246, 0.22);
    border-color: rgba(96, 165, 250, 0.55);
    color: #93c5fd;
  }
  .mode-btn.active-tv {
    background: rgba(16, 185, 129, 0.22);
    border-color: rgba(52, 211, 153, 0.55);
    color: #6ee7b7;
  }

  /* Volume Bar */
  .vol-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }
  .vol-btn {
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 11px;
    padding: 9px 6px;
    background: rgba(255,255,255,0.04);
    color: var(--text-main);
    font-size: 12.5px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    cursor: pointer;
  }
  .vol-btn:active {
    transform: scale(0.95);
    background: rgba(255,255,255,0.12);
  }

  /* Quit Everything Button */
  .quit-all-btn {
    width: 100%;
    margin-top: 2px;
    border: 1px solid rgba(239, 68, 68, 0.45);
    border-radius: 18px;
    padding: 15px 16px;
    background: linear-gradient(135deg, rgba(220, 38, 38, 0.24) 0%, rgba(153, 27, 27, 0.28) 100%);
    color: #fecaca;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 9px;
    font-size: 14.5px;
    font-weight: 800;
    letter-spacing: -0.2px;
    cursor: pointer;
    transition: transform 0.14s ease, background 0.15s ease;
  }
  .quit-all-btn:active {
    transform: scale(0.96);
    background: rgba(220, 38, 38, 0.42);
  }

  /* Toast Notification */
  #toast {
    position: fixed;
    bottom: calc(env(safe-area-inset-bottom, 16px) + 16px);
    left: 50%;
    transform: translateX(-50%) translateY(20px);
    background: rgba(15, 23, 42, 0.96);
    border: 1px solid rgba(255,255,255,0.18);
    color: #fff;
    padding: 12px 20px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    box-shadow: 0 12px 28px rgba(0,0,0,0.55);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease, transform 0.2s ease;
    white-space: nowrap;
    z-index: 100;
  }
  #toast.show {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }

    /* Pull-to-Refresh Bar */
    html, body { overscroll-behavior-y: contain; }
    #ptr-bar {
      position: fixed;
      top: env(safe-area-inset-top, 0px);
      left: 0;
      right: 0;
      height: 0px;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 9999;
      pointer-events: none;
      opacity: 0;
      transition: height 0.22s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.18s ease;
    }
    #ptr-bar.dragging { transition: none; }
    #ptr-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.94);
      border: 1px solid rgba(255, 255, 255, 0.16);
      color: #f8fafc;
      font-size: 12px;
      font-weight: 700;
      box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    }
    @keyframes ptrSpin { to { transform: rotate(360deg); } }
    .ptr-spin { animation: ptrSpin 0.8s linear infinite; }

</style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <div class="header">
      <div class="brand">
        <div class="logo-wrap">
          <img src="/icon.png" alt="M4 Gaming">
        </div>
        <div class="brand-text">
          <h1>M4 Gaming</h1>
          <p>Télécommande Mac mini</p>
        </div>
      </div>
      <div class="status-pill">
        <span class="status-dot"></span>
        <span id="status-text">Prêt</span>
      </div>
    </div>

    <!-- 0. Bouton Prêt à jouer sur la Télé (Allume TV + Résolution TV 1080p HiDPI) -->
    <button class="main-btn btn-tv-ready" onclick="trigger('/tv-gaming')">
      <div class="btn-left">
        <div class="btn-icon">
          <svg viewBox="0 0 24 24"><path d="M21 3H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h5v2h8v-2h5c1.1 0 1.99-.9 1.99-2L23 5c0-1.1-.9-2-2-2zm0 14H3V5h18v12zM10 8v6l5-3-5-3z"/></svg>
        </div>
        <div>
          <span class="btn-title">Allumer la Télé & Mode TV</span>
          <span class="btn-sub">Allume la TV + Résolution 16:9 TV + Prêt à jouer</span>
        </div>
      </div>
      <span class="btn-arrow">📺</span>
    </button>

    <!-- 1. ES-DE Mode Console (Ferme Steam automatiquement) -->
    <button class="main-btn btn-esde" onclick="trigger('/launch')">
      <div class="btn-left">
        <div class="btn-icon">
          <svg viewBox="0 0 24 24"><path d="M21 6H3c-1.1 0-2 .9-2 2v8c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-10 7H8v3H6v-3H3v-2h3V8h2v3h3v2zm4.5 2c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm4-3c-.83 0-1.5-.67-1.5-1.5S18.67 9 19.5 9s1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/></svg>
        </div>
        <div>
          <span class="btn-title">EmulationStation</span>
          <span class="btn-sub">Bascule sur ES-DE (ferme Steam)</span>
        </div>
      </div>
      <span class="btn-arrow">▶</span>
    </button>

    <!-- 2. Steam Big Picture Mac (Ferme ES-DE automatiquement) -->
    <button class="main-btn btn-steam" onclick="trigger('/steam')">
      <div class="btn-left">
        <div class="btn-icon">
          <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12c0 4.84 3.44 8.87 8 9.8V15H8v-3h2V9.5C10 7.57 11.57 6 13.5 6H16v3h-2c-.55 0-1 .45-1 1v2h3v3h-3v6.95c5.05-.5 9-4.76 9-9.95 0-5.52-4.48-10-10-10z"/></svg>
        </div>
        <div>
          <span class="btn-title">Steam Big Picture</span>
          <span class="btn-sub">Bascule sur Steam (ferme ES-DE)</span>
        </div>
      </div>
      <span class="btn-arrow">▶</span>
    </button>

    <!-- 3. Steam Windows Whisky (Ferme ES-DE & Steam Mac) -->
    <button class="main-btn btn-steam-win" onclick="trigger('/steam-win')">
      <div class="btn-left">
        <div class="btn-icon">
          <svg viewBox="0 0 24 24"><path d="M3 5.55L10.95 4.4v7.15H3V5.55zm0 12.9l7.95 1.15v-7.15H3v6zm8.85 1.28L21 21v-8.55h-9.15v7.38zm0-15.46v7.28H21V3l-9.15 1.27z"/></svg>
        </div>
        <div>
          <span class="btn-title">Steam Windows</span>
          <span class="btn-sub">Jeux PC via Whisky (ferme ES-DE)</span>
        </div>
      </div>
      <span class="btn-arrow">▶</span>
    </button>

    <!-- 4. Écran & Résolution (Mode Télévision 16:9 vs Mode MacBook 16:10) -->
    <div class="section-card">
      <div class="section-header">
        <span>AFFICHAGE & RÉSOLUTION</span>
        <span class="section-current" id="display-mode-label">1680×1050 (MacBook)</span>
      </div>
      <div class="mode-grid">
        <button class="mode-btn" id="btn-disp-tv" onclick="trigger('/display?mode=tv')">
          <span>📺</span>
          <span>Mode Télé (1080p)</span>
        </button>
        <button class="mode-btn" id="btn-disp-mac" onclick="trigger('/display?mode=mac')">
          <span>💻</span>
          <span>Mode MacBook</span>
        </button>
      </div>
    </div>

    <!-- 5. Audio Output Switcher (HomePod / AirPods) & Volume -->
    <div class="section-card">
      <div class="section-header">
        <span>SORTIE AUDIO</span>
        <span class="section-current" id="audio-out-label">AirPods Pro</span>
      </div>
      <div class="mode-grid">
        <button class="mode-btn" id="btn-airpods" onclick="trigger('/audio?out=airpods')">
          <span>🎧</span>
          <span>AirPods</span>
        </button>
        <button class="mode-btn" id="btn-homepod" onclick="trigger('/audio?out=homepod')">
          <span>🔊</span>
          <span>HomePod / Salon</span>
        </button>
      </div>
      <div class="vol-grid">
        <button class="vol-btn" onclick="trigger('/vol?dir=down')">🔉 Vol -</button>
        <button class="vol-btn" onclick="trigger('/vol?dir=mute')">🔇 Mute</button>
        <button class="vol-btn" onclick="trigger('/vol?dir=up')">🔊 Vol +</button>
      </div>
    </div>

    <!-- 6. Quit Gaming Mode (Closes ES-DE, Steam, Whisky & all emulators) -->
    <button class="quit-all-btn" onclick="trigger('/quit')">
      <span>⏹️</span>
      <span>Quitter le Mode Gaming (Tout fermer)</span>
    </button>
  </div>

  <div id="toast"></div>

  <script>
    let toastTimer = null;
    function showToast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => t.classList.remove('show'), 3000);
    }

    async function trigger(path) {
      showToast('Envoi au Mac mini...');
      try {
        const r = await fetch(path);
        const d = await r.json();
        showToast(d.message || 'OK');
        setTimeout(updateStatus, 400);
      } catch (e) {
        showToast('Erreur de connexion');
      }
    }

    async function updateStatus() {
      try {
        const r = await fetch('/status');
        const d = await r.json();
        document.getElementById('status-text').textContent = d.active || 'Prêt';
        if (d.audio) {
          document.getElementById('audio-out-label').textContent = d.audio;
          const isAirpods = d.audio.toLowerCase().includes('airpods');
          document.getElementById('btn-airpods').classList.toggle('active', isAirpods);
          document.getElementById('btn-homepod').classList.toggle('active', !isAirpods);
        }
        if (d.display) {
          const dispLabel = document.getElementById('display-mode-label');
          const isTv = d.display.includes('1920x1080') || d.display.includes('3840x2160');
          dispLabel.textContent = isTv ? '📺 Mode Télé (1080p 4K)' : '💻 MacBook (' + d.display + ')';
          dispLabel.classList.toggle('tv-active', isTv);
          document.getElementById('btn-disp-tv').classList.toggle('active-tv', isTv);
          document.getElementById('btn-disp-mac').classList.toggle('active', !isTv);
        }
      } catch (e) {}
    }
    updateStatus();
    setInterval(updateStatus, 4000);
  </script>

  <div id="ptr-bar">
    <div id="ptr-pill">
      <svg id="ptr-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="transition: transform 0.15s ease;">
        <path d="M19 14l-7 7m0 0l-7-7m7 7V3"/>
      </svg>
      <span id="ptr-text">Tirer pour actualiser</span>
    </div>
  </div>
  <script>
    (function() {
      const bar = document.getElementById("ptr-bar");
      const icon = document.getElementById("ptr-icon");
      const text = document.getElementById("ptr-text");
      const THRESHOLD = 64, MAX_PULL = 110;
      let startY = 0, pull = 0, pulling = false, refreshing = false;
      const isAtTop = () => (window.scrollY || document.documentElement.scrollTop || 0) <= 2;
      const onStart = (y) => { if (!refreshing && isAtTop()) { startY = y; pull = 0; pulling = true; } };
      const onMove = (y, ev) => {
        if (!pulling || refreshing) return;
        const delta = y - startY;
        if (delta <= 0 || !isAtTop()) {
          if (pull > 0) { bar.style.height = "0px"; bar.style.opacity = "0"; pull = 0; }
          return;
        }
        pull = Math.min(MAX_PULL, Math.pow(delta, 0.82) * 1.55);
        if (pull > 8 && ev && ev.cancelable) ev.preventDefault();
        bar.classList.add("dragging");
        bar.style.height = pull + "px";
        bar.style.opacity = String(Math.min(1, pull / 55));
        if (pull >= THRESHOLD) {
          icon.style.transform = "rotate(180deg)";
          text.textContent = "Relâcher pour actualiser";
        } else {
          icon.style.transform = "rotate(0deg)";
          text.textContent = "Tirer pour actualiser";
        }
      };
      const onEnd = async () => {
        if (!pulling || refreshing) return;
        pulling = false;
        bar.classList.remove("dragging");
        if (pull >= THRESHOLD) {
          refreshing = true;
          bar.style.height = "52px";
          bar.style.opacity = "1";
          icon.style.transform = "rotate(0deg)";
          icon.classList.add("ptr-spin");
          text.textContent = "Actualisation M4...";
          if (navigator.vibrate) navigator.vibrate(12);
          await updateStatus();
          setTimeout(() => {
            text.textContent = "Statut à jour ✓";
            icon.classList.remove("ptr-spin");
            setTimeout(() => {
              bar.style.height = "0px";
              bar.style.opacity = "0";
              refreshing = false;
            }, 350);
          }, 300);
        } else {
          bar.style.height = "0px";
          bar.style.opacity = "0";
        }
        pull = 0;
      };
      window.addEventListener("touchstart", (e) => { if (e.touches.length === 1) onStart(e.touches[0].clientY); }, { passive: true });
      window.addEventListener("touchmove", (e) => { if (e.touches.length === 1) onMove(e.touches[0].clientY, e); }, { passive: false });
      window.addEventListener("touchend", onEnd, { passive: true });
      window.addEventListener("touchcancel", onEnd, { passive: true });
      window.addEventListener("mousedown", (e) => { if (e.button === 0 && !["BUTTON"].includes(e.target.tagName)) onStart(e.clientY); });
      window.addEventListener("mousemove", (e) => { if (pulling) onMove(e.clientY, null); });
      window.addEventListener("mouseup", onEnd);
    })();
  </script>

</body>
</html>
"""

def wake_mac():
    subprocess.Popen(["/usr/bin/caffeinate", "-u", "-t", "5"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def ensure_betterdisplay():
    res = subprocess.run(["/usr/bin/pgrep", "-x", "BetterDisplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode != 0:
        subprocess.run(["/usr/bin/open", "-g", "-a", "/Applications/BetterDisplay.app"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_current_display():
    if os.path.exists(BETTERDISPLAY_CLI):
        ensure_betterdisplay()
        res = subprocess.run([BETTERDISPLAY_CLI, "get", "-tagID=10", "-resolution"], capture_output=True, text=True)
        out = res.stdout.strip()
        if out and "Failed" not in out:
            return out
    return "1680x1050"

def set_tv_mode(wake_tv=True):
    wake_mac()
    if os.path.exists(BETTERDISPLAY_CLI):
        ensure_betterdisplay()
        if wake_tv:
            # Envoie le signal HDMI-CEC Wake + bascule de source HDMI vers le Mac mini + réveil de tous les écrans
            subprocess.Popen([BETTERDISPLAY_CLI, "perform", "-sendCEC=wake"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.Popen([BETTERDISPLAY_CLI, "perform", "-sendCEC=input:mac"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.Popen([BETTERDISPLAY_CLI, "set", "-tagID=10", "-hardwareBacklight=on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.Popen([BETTERDISPLAY_CLI, "perform", "-connectAllDisplays"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Passe la résolution en 1920x1080 HiDPI (4K 3840x2160 natif 60Hz 16:9 Mode Télévision)
        subprocess.run([BETTERDISPLAY_CLI, "set", "-tagID=10", "-displayModeNumber=34"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([BETTERDISPLAY_CLI, "set", "-tagID=2", "-resolution=1920x1080"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def set_macbook_mode():
    wake_mac()
    if os.path.exists(BETTERDISPLAY_CLI):
        ensure_betterdisplay()
        # Repasse en 1680x1050 (16:10) pour le partage d'écran MacBook Air
        subprocess.run([BETTERDISPLAY_CLI, "set", "-tagID=10", "-displayModeNumber=31"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_current_audio():
    if os.path.exists(AUDIO_SWITCHER):
        res = subprocess.run([AUDIO_SWITCHER, "current"], capture_output=True, text=True)
        out = res.stdout.strip()
        if out:
            return out
    return "Mac mini"

def get_active_status():
    for proc, label in [
        ("ES-DE", "ES-DE Actif"),
        ("steam_osx", "Steam Actif"),
        ("wine64-preloader", "Steam Win Actif"),
        ("Ryujinx", "Jeu Switch"),
        ("Dolphin", "Jeu GC/Wii"),
        ("PCSX2-v2.8.2", "Jeu PS2"),
        ("RPCS3", "Jeu PS3"),
        ("Cemu", "Jeu Wii U"),
        ("Azahar", "Jeu 3DS"),
        ("RetroArch", "RetroArch Actif"),
    ]:
        res = subprocess.run(["/usr/bin/pgrep", "-f", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            return label
    return "Prêt • M4"

def close_processes(proc_list):
    for proc in proc_list:
        subprocess.run(["/usr/bin/killall", "-9", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

class GamingHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ("/icon.png", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/favicon.ico"):
            if os.path.exists(ICON_PATH):
                with open(ICON_PATH, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if path == "/status":
            return self.send_json({
                "status": "ok",
                "active": get_active_status(),
                "audio": get_current_audio(),
                "display": get_current_display(),
            })

        if path == "/tv-gaming":
            set_tv_mode(wake_tv=True)
            # Bascule aussi le son sur le salon / TV si disponible, et lance ES-DE si rien ne tourne
            active = get_active_status()
            if active == "Prêt • M4":
                subprocess.Popen(["/usr/bin/open", "-a", "/Applications/ES-DE.app"])
                subprocess.Popen(["/usr/bin/osascript", "-e", 'tell application "ES-DE" to activate'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self.send_json({"status": "ok", "message": "📺 Télé allumée • Résolution TV 1080p (4K) • ES-DE prêt !"})
            return self.send_json({"status": "ok", "message": "📺 Télé allumée & Résolution TV 1080p (4K) activée !"})

        if path == "/display":
            mode = qs.get("mode", ["tv"])[0]
            if mode == "tv":
                set_tv_mode(wake_tv=True)
                return self.send_json({"status": "ok", "message": "📺 Télé allumée & Résolution TV (1920×1080 HiDPI) activée !"})
            elif mode == "mac":
                set_macbook_mode()
                return self.send_json({"status": "ok", "message": "💻 Résolution MacBook (1680×1050) restaurée !"})

        if path in ("/launch", "/gaming"):
            set_tv_mode(wake_tv=True)
            # Ferme Steam Mac & Steam Windows avant de lancer ES-DE
            close_processes(STEAM_PROCESSES)
            subprocess.Popen(["/usr/bin/open", "-a", "/Applications/ES-DE.app"])
            subprocess.Popen(["/usr/bin/osascript", "-e", 'tell application "ES-DE" to activate'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return self.send_json({"status": "ok", "message": "🎮 TV en 1080p + ES-DE lancé !"})

        if path == "/steam":
            set_tv_mode(wake_tv=True)
            # Ferme ES-DE et les émulateurs avant de lancer Steam Big Picture
            close_processes(["ES-DE"] + EMULATOR_PROCESSES)
            subprocess.Popen(["/Applications/Steam Big Picture.app/Contents/MacOS/SteamBigPicture"])
            return self.send_json({"status": "ok", "message": "🚀 TV en 1080p + Steam Big Picture lancé !"})

        if path == "/steam-win":
            set_tv_mode(wake_tv=True)
            # Ferme ES-DE, Steam Mac et les émulateurs avant de lancer Steam Windows
            close_processes(["ES-DE", "steam_osx", "Steam Helper", "ipcserver"] + EMULATOR_PROCESSES)
            subprocess.Popen(["/Applications/Steam Windows (Big Picture).app/Contents/MacOS/SteamWindowsBigPicture"])
            return self.send_json({"status": "ok", "message": "🪟 TV en 1080p + Steam Windows lancé !"})

        if path == "/audio":
            target = qs.get("out", [""])[0]
            if target == "airpods":
                res = subprocess.run([AUDIO_SWITCHER, "airpods"], capture_output=True, text=True).stdout.strip()
                if res.startswith("OK:"):
                    dev = res.split(":", 1)[1]
                    return self.send_json({"status": "ok", "message": f"🎧 Son basculé sur {dev}"})
                return self.send_json({"status": "ok", "message": "🎧 AirPods non détectés à proximité"})
            elif target == "homepod":
                subprocess.run(["/usr/bin/shortcuts", "run", "HomePod"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                res = subprocess.run([AUDIO_SWITCHER, "homepod"], capture_output=True, text=True).stdout.strip()
                if res.startswith("OK:"):
                    dev = res.split(":", 1)[1]
                    return self.send_json({"status": "ok", "message": f"🔊 Son basculé sur {dev}"})
                return self.send_json({"status": "ok", "message": "🔊 Bascule enceintes effectuée"})

        if path == "/vol":
            direction = qs.get("dir", [""])[0]
            if direction == "up":
                subprocess.Popen(["/usr/bin/osascript", "-e", "set volume output volume ((output volume of (get volume settings)) + 10)"])
                return self.send_json({"status": "ok", "message": "🔊 Volume +10%"})
            elif direction == "down":
                subprocess.Popen(["/usr/bin/osascript", "-e", "set volume output volume ((output volume of (get volume settings)) - 10)"])
                return self.send_json({"status": "ok", "message": "🔉 Volume -10%"})
            elif direction == "mute":
                subprocess.Popen(["/usr/bin/osascript", "-e", "set volume output muted not (output muted of (get volume settings))"])
                return self.send_json({"status": "ok", "message": "🔇 Audio basculé"})

        if path == "/quit":
            close_processes(GAMING_PROCESSES)
            set_macbook_mode()
            return self.send_json({"status": "ok", "message": "⏹️ Jeux fermés & Résolution MacBook restaurée"})

        body = HTML_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), GamingHandler)
    server.serve_forever()
