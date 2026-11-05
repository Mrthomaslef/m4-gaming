#!/usr/bin/env python3
import http.server
import json
import os
import queue
import re
import subprocess
import threading
import time
import urllib.parse

PORT = 8765

ICON_PATH = "/Users/thomaslefevre/ES-DE/scripts/app_icon.png"
AUDIO_SWITCHER = "/Users/thomaslefevre/ES-DE/scripts/audio_switcher"
BETTERDISPLAY_CLI = "/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay"
# HDMI-CEC via le tunnel DPCD (USB-C/DP -> HDMI, disp0) : Image View On + Active Source 2.0.0.0 (HDMI 2).
# BetterDisplay `perform -tagID=2 -sendCEC=wake` répond "Failed." sur cette config (alors que -CECReport marche),
# et sans -tagID la commande ne cible aucun écran (no-op silencieux) -> on utilise ce petit helper natif.
DPCD_CEC = "/Users/thomaslefevre/ES-DE/scripts/dpcd_cec/dpcd_cec"
# macOS 26 : la Samsung (EDID "TV") est traitée comme une cible "Recopie de l'écran" (feature WindowServer
# WindowMirroring). Au branchement / réveil HDMI, SkyLight envoie `tvConnected` à Control Center, l'écran
# reste HORS LIGNE (CGDisplayIsOnline=0) et Control Center affiche le "Screen Mirroring shield"
# ("Indiquez si vous souhaitez effectuer une recopie ou étendre l'affichage..."). Ce helper pilote
# l'UI de Control Center via Accessibilité : Recopie de l'écran > Choisir du contenu > Tout l'écran >
# Commencer la recopie. Codes retour : 0 TV affichée, 1 échec, 2 TV absente, 3 pas d'Accessibilité, 4 en attente.
TV_MIRROR = "/Users/thomaslefevre/ES-DE/scripts/tv_mirror/tv_mirror"
# Lancé via run_disclaimed : tv_mirror devient son propre "processus responsable" TCC, donc c'est SON
# autorisation d'Accessibilité qui compte (python3 lancé par launchd n'en a pas).
TV_MIRROR_LAUNCHER = "/Users/thomaslefevre/ES-DE/scripts/tv_mirror/run_disclaimed"
TV_VENDOR_ID = "19501"   # SAMSUNG (CGDisplayVendorNumber)
TV_TAG_ID = "2"          # SAMSUNG (disp0, USB-C -> HDMI)
DUMMY_TAG_ID = "10"      # 4k60-1080@240 (dummy HDMI)
TV_PHYS_ADDR = "2.0.0.0"  # HDMI 2 de la TV

STEAM_PROCESSES = [
    "steam_osx",
    "Steam Helper",
    "ipcserver",
    "Whisky",
    "WhiskyCmd",
    "wine",
    "wine64",
    "wine64-preloader",
    "wineloader",
    "wineserver",
]

# CrossOver renomme ses processus avec le chemin Windows : ni killall ni un nom Unix ne les voient.
WINE_PROCESS_PATTERN = r"^[A-Za-z]:\\"
CROSSOVER_BIN = "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin"
CROSSOVER_BOTTLE = "/Users/thomaslefevre/Library/Application Support/CrossOver/Bottles/Steam"

EMULATOR_PROCESSES = [
    "RetroArch",
    "Ryujinx", "ryujinx_shader_hud", "wine_fps_hud",
    "Dolphin",
    "PCSX2-v2.8.2",
    "PCSX2",
    "RPCS3",
    "Cemu",
    "Azahar", "azahar",
    "PPSSPP", "PPSSPPSDL",
    "DuckStation",
    "Eden",
    "Flycast",
    "mGBA",
    "melonDS",
    "wwhd",
    "wind-waker-hd",
    "BotW",
    "totk-native-botw190",
]

GAMING_PROCESSES = ["pegasus-fe", "ES-DE"] + STEAM_PROCESSES + EMULATOR_PROCESSES

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
<title>M4 Gaming — Télé & Lanceur de Jeux Mac mini</title>
<style>
  :root {
    --bg-dark: #06080f;
    --card-bg: rgba(255, 255, 255, 0.055);
    --card-border: rgba(255, 255, 255, 0.11);
    --text-main: #f8fafc;
    --text-muted: #94a3b8;
    --accent: #10b981;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; user-select: none; -webkit-user-select: none; }
  html, body { overscroll-behavior-y: contain; margin: 0; padding: 0; }
  body {
    padding: calc(env(safe-area-inset-top, 16px) + 12px) 16px calc(env(safe-area-inset-bottom, 20px) + 28px) 16px;
    background-color: var(--bg-dark);
    background-image:
      radial-gradient(circle at 20% 0%, rgba(16, 185, 129, 0.22) 0%, transparent 50%),
      radial-gradient(circle at 85% 10%, rgba(59, 130, 246, 0.22) 0%, transparent 50%),
      radial-gradient(circle at 50% 90%, rgba(139, 92, 246, 0.14) 0%, transparent 55%);
    color: var(--text-main);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", sans-serif;
    min-height: 100vh;
  }
  .container {
    width: 100%;
    max-width: 1120px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  /* Header */
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    padding: 4px 2px;
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
    box-shadow: 0 8px 24px rgba(16, 185, 129, 0.35), inset 0 0 0 1px rgba(255,255,255,0.22);
    flex-shrink: 0;
  }
  .logo-wrap img { width: 100%; height: 100%; object-fit: cover; }
  .brand-text h1 {
    margin: 0;
    font-size: 21px;
    font-weight: 800;
    letter-spacing: -0.5px;
    background: linear-gradient(135deg, #ffffff 0%, #a7f3d0 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .brand-text p {
    margin: 2px 0 0 0;
    font-size: 12.5px;
    color: var(--text-muted);
    font-weight: 600;
  }
  .header-right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .status-pill {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 7px 13px;
    border-radius: 999px;
    background: rgba(16, 185, 129, 0.14);
    border: 1px solid rgba(16, 185, 129, 0.35);
    font-size: 12px;
    font-weight: 700;
    color: #34d399;
  }
  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #10b981;
    box-shadow: 0 0 8px #10b981;
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.45; transform: scale(0.85); }
  }

  /* Quick TV Bar */
  .quick-tv-bar {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
  }
  @media (max-width: 640px) {
    .quick-tv-bar { grid-template-columns: repeat(2, 1fr); }
  }
  .qbtn {
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 15px;
    padding: 12px 12px;
    background: rgba(255,255,255,0.06);
    color: #fff;
    font-size: 13px;
    font-weight: 800;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    cursor: pointer;
    transition: transform 0.12s ease, background 0.15s ease;
  }
  .qbtn:active { transform: scale(0.96); }
  .qbtn-tv-on {
    background: linear-gradient(135deg, rgba(5, 150, 105, 0.85) 0%, rgba(37, 99, 235, 0.85) 100%);
    border-color: rgba(52, 211, 153, 0.5);
    box-shadow: 0 8px 20px -6px rgba(16, 185, 129, 0.45);
  }
  .qbtn-tv-off {
    background: rgba(30, 41, 59, 0.85);
    border-color: rgba(148, 163, 184, 0.3);
  }
  .qbtn-esde {
    background: linear-gradient(135deg, rgba(37, 99, 235, 0.75) 0%, rgba(79, 70, 229, 0.75) 100%);
    border-color: rgba(96, 165, 250, 0.45);
  }
  .qbtn-quit {
    background: rgba(220, 38, 38, 0.22);
    border-color: rgba(239, 68, 68, 0.45);
    color: #fecaca;
  }

  /* View Switcher Tabs */
  .view-tabs {
    display: flex;
    gap: 8px;
    background: rgba(255,255,255,0.04);
    padding: 5px;
    border-radius: 16px;
    border: 1px solid rgba(255,255,255,0.08);
  }
  .view-tab {
    flex: 1;
    border: none;
    background: transparent;
    color: var(--text-muted);
    padding: 11px 14px;
    border-radius: 12px;
    font-size: 13.5px;
    font-weight: 800;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    transition: all 0.15s ease;
  }
  .view-tab.active {
    background: rgba(16, 185, 129, 0.2);
    color: #6ee7b7;
    box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.45);
  }

  /* Search & Console Filter Bar */
  .catalog-toolbar {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .search-box {
    position: relative;
    width: 100%;
  }
  .search-box input {
    width: 100%;
    padding: 13px 40px 13px 42px;
    border-radius: 15px;
    border: 1px solid rgba(255,255,255,0.14);
    background: rgba(15, 23, 42, 0.75);
    color: #fff;
    font-size: 14px;
    font-weight: 600;
    outline: none;
    -webkit-user-select: text;
    user-select: text;
  }
  .search-box input:focus {
    border-color: #10b981;
    box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
  }
  .search-icon {
    position: absolute;
    left: 14px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 15px;
    opacity: 0.7;
    pointer-events: none;
  }
  .search-clear {
    position: absolute;
    right: 12px;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(255,255,255,0.12);
    border: none;
    color: #fff;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    font-size: 12px;
    cursor: pointer;
    display: none;
    align-items: center;
    justify-content: center;
  }

  .filter-pills {
    display: flex;
    gap: 7px;
    overflow-x: auto;
    padding-bottom: 4px;
    scrollbar-width: none;
  }
  .filter-pills::-webkit-scrollbar { display: none; }
  .fpill {
    border: 1px solid rgba(255,255,255,0.11);
    background: rgba(255,255,255,0.05);
    color: #cbd5e1;
    padding: 8px 13px;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 700;
    white-space: nowrap;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: all 0.14s ease;
  }
  .fpill.active {
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    color: #042f2e;
    border-color: #34d399;
    font-weight: 800;
  }
  .fpill-count {
    font-size: 10.5px;
    padding: 1px 6px;
    border-radius: 999px;
    background: rgba(0,0,0,0.25);
    color: inherit;
  }

  /* Games Grid */
  .games-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(155px, 1fr));
    gap: 12px;
  }
  @media (max-width: 480px) {
    .games-grid {
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
    }
  }
  .game-card {
    position: relative;
    border-radius: 18px;
    overflow: hidden;
    background: rgba(15, 23, 42, 0.85);
    border: 1px solid rgba(255,255,255,0.11);
    display: flex;
    flex-direction: column;
    cursor: pointer;
    transition: transform 0.16s cubic-bezier(0.22, 1, 0.36, 1), border-color 0.16s ease, box-shadow 0.2s ease;
    text-align: left;
    padding: 0;
    color: #fff;
  }
  .game-card:hover {
    transform: translateY(-3px);
    border-color: rgba(52, 211, 153, 0.65);
    box-shadow: 0 14px 30px -8px rgba(16, 185, 129, 0.35);
  }
  .game-card:active {
    transform: scale(0.96);
  }
  .game-card.running {
    border: 2px solid #10b981;
    box-shadow: 0 0 24px rgba(16, 185, 129, 0.5);
  }
  .game-cover-wrap {
    position: relative;
    width: 100%;
    aspect-ratio: 3 / 4;
    background: #0f172a;
    overflow: hidden;
  }
  .game-cover-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    transition: transform 0.25s ease;
  }
  .game-card:hover .game-cover-wrap img {
    transform: scale(1.04);
  }
  .game-badge {
    position: absolute;
    top: 8px;
    left: 8px;
    padding: 3px 8px;
    border-radius: 8px;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.4px;
    color: #fff;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    box-shadow: 0 4px 10px rgba(0,0,0,0.45);
  }
  .game-play-pill {
    position: absolute;
    bottom: 8px;
    right: 8px;
    padding: 5px 10px;
    border-radius: 999px;
    background: rgba(16, 185, 129, 0.94);
    color: #022c22;
    font-size: 10.5px;
    font-weight: 900;
    display: flex;
    align-items: center;
    gap: 4px;
    box-shadow: 0 6px 16px rgba(0,0,0,0.55);
  }
  .game-info {
    padding: 10px 11px 11px 11px;
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 1;
    justify-content: space-between;
  }
  .game-title {
    font-size: 13px;
    font-weight: 800;
    line-height: 1.28;
    color: #f8fafc;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .game-sub {
    font-size: 11px;
    color: #94a3b8;
    font-weight: 600;
  }

  /* Remote View */
  .remote-wrap {
    max-width: 480px;
    width: 100%;
    margin: 0 auto;
    display: none;
    flex-direction: column;
    gap: 12px;
  }
  .remote-wrap.active { display: flex; }
  .catalog-wrap { display: none; flex-direction: column; gap: 12px; }
  .catalog-wrap.active { display: flex; }

  /* Main Action Cards (Remote) */
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
  .main-btn:active { transform: scale(0.96); }
  .btn-tv-ready {
    border: 1px solid rgba(16, 185, 129, 0.55);
    background: linear-gradient(135deg, #059669 0%, #0d9488 50%, #2563eb 100%);
    box-shadow: 0 14px 32px -8px rgba(16, 185, 129, 0.5), inset 0 1px 1px rgba(255, 255, 255, 0.38);
  }
  .btn-tv-off {
    border: 1px solid rgba(148, 163, 184, 0.38);
    background: linear-gradient(135deg, #1e293b 0%, #334155 50%, #0f172a 100%);
  }
  .btn-esde {
    border: 1px solid rgba(96, 165, 250, 0.45);
    background: linear-gradient(135deg, #2563eb 0%, #4f46e5 100%);
  }
  .btn-steam {
    border: 1px solid rgba(56, 189, 248, 0.35);
    background: linear-gradient(135deg, #1b2838 0%, #2a475e 100%);
  }
  .btn-steam-win {
    border: 1px solid rgba(14, 165, 233, 0.35);
    background: linear-gradient(135deg, rgba(14, 165, 233, 0.22) 0%, rgba(37, 99, 235, 0.25) 100%);
  }
  .btn-left { display: flex; align-items: center; gap: 14px; }
  .btn-icon {
    width: 46px; height: 46px; border-radius: 14px;
    background: rgba(255, 255, 255, 0.16);
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
  }
  .btn-icon svg { width: 25px; height: 25px; fill: #ffffff; }
  .btn-title { font-size: 16.5px; font-weight: 800; letter-spacing: -0.3px; display: block; }
  .btn-sub { font-size: 12px; color: rgba(255, 255, 255, 0.82); font-weight: 500; margin-top: 2px; display: block; }
  .btn-arrow { font-size: 16px; font-weight: 800; opacity: 0.8; padding-left: 8px; }

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
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 4px; font-size: 11.5px; font-weight: 700; color: var(--text-muted);
  }
  .section-current { color: #60a5fa; font-weight: 800; }
  .section-current.tv-active { color: #34d399; }
  .mode-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
  .mode-btn {
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 13px;
    padding: 11px 8px;
    background: rgba(255,255,255,0.05);
    color: var(--text-main);
    font-size: 13.5px;
    font-weight: 700;
    display: flex; align-items: center; justify-content: center; gap: 7px;
    cursor: pointer;
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
  .vol-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .vol-btn {
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 11px;
    padding: 13px 6px;
    background: rgba(255,255,255,0.05);
    color: var(--text-main);
    font-size: 13.5px;
    font-weight: 800;
    display: flex; align-items: center; justify-content: center; gap: 5px;
    cursor: pointer;
  }
  .vol-btn:active, .vol-btn.pressed {
    transform: scale(0.94);
    background: rgba(56,189,248,0.22);
    border-color: rgba(56,189,248,0.5);
  }
  button { touch-action: manipulation; }
  button.pending { opacity: 0.55; }

  .quit-all-btn {
    width: 100%;
    border: 1px solid rgba(239, 68, 68, 0.45);
    border-radius: 18px;
    padding: 15px 16px;
    background: linear-gradient(135deg, rgba(220, 38, 38, 0.24) 0%, rgba(153, 27, 27, 0.28) 100%);
    color: #fecaca;
    display: flex; align-items: center; justify-content: center; gap: 9px;
    font-size: 14.5px; font-weight: 800; cursor: pointer;
  }

  #toast {
    position: fixed;
    bottom: calc(env(safe-area-inset-bottom, 16px) + 16px);
    left: 50%;
    transform: translateX(-50%) translateY(20px);
    background: rgba(15, 23, 42, 0.96);
    border: 1px solid rgba(52, 211, 153, 0.4);
    color: #fff;
    padding: 12px 20px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    box-shadow: 0 12px 28px rgba(0,0,0,0.65);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease, transform 0.2s ease;
    max-width: 92vw;
    text-align: center;
    z-index: 1000;
  }
  #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
</style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <div class="header">
      <div class="brand">
        <div class="logo-wrap">
          <img src="icon.png" alt="M4 Gaming">
        </div>
        <div class="brand-text">
          <h1>M4 Gaming</h1>
          <p>Allume la Télé & Lance tes Jeux sur Mac mini M4</p>
        </div>
      </div>
      <div class="header-right">
        <div class="status-pill">
          <span class="status-dot"></span>
          <span id="status-text">Prêt • M4</span>
        </div>
      </div>
    </div>

    <!-- Barre d'actions rapides Télé & Console -->
    <div class="quick-tv-bar">
      <button class="qbtn qbtn-tv-on" onclick="trigger('/tv-gaming')">
        <span>📺</span>
        <span>Allumer Télé & Mode TV</span>
      </button>
      <button class="qbtn qbtn-esde" onclick="trigger('/launch')">
        <span>🎮</span>
        <span>Ouvrir Pegasus</span>
      </button>
      <button class="qbtn qbtn-tv-off" onclick="trigger('/tv-off')">
        <span>🌙</span>
        <span>Éteindre Télé (MacBook)</span>
      </button>
      <button class="qbtn qbtn-quit" onclick="trigger('/quit')">
        <span>⏹️</span>
        <span>Quitter le Jeu</span>
      </button>
    </div>

    <!-- Onglets : Bibliothèque de Jeux vs Télécommande TV/Audio -->
    <div class="view-tabs">
      <button class="view-tab active" id="tab-btn-games" onclick="switchView('games')">
        <span>🕹️</span>
        <span>Jeux avec Icônes (<span id="total-games-count">82</span>)</span>
      </button>
      <button class="view-tab" id="tab-btn-remote" onclick="switchView('remote')">
        <span>🎛️</span>
        <span>Télécommande TV, Son & Steam</span>
      </button>
    </div>

    <!-- VUE 1 : CATALOGUE DES JEUX AVEC ICÔNES (1-Tap TV + Launch) -->
    <div class="catalog-wrap active" id="view-games">
      <div class="catalog-toolbar">
        <div class="search-box">
          <span class="search-icon">🔍</span>
          <input type="text" id="game-search" placeholder="Rechercher un jeu (Wind Waker, Zelda, Mario, Pokémon, Metroid...)" oninput="onSearchInput()">
          <button class="search-clear" id="search-clear-btn" onclick="clearSearch()">✕</button>
        </div>
        <div class="filter-pills" id="filter-pills"></div>
      </div>

      <div class="games-grid" id="games-grid"></div>
    </div>

    <!-- VUE 2 : TÉLÉCOMMANDE TV, SON, RÉSOLUTION & STEAM -->
    <div class="remote-wrap" id="view-remote">
      <button class="main-btn btn-tv-ready" onclick="trigger('/tv-gaming')">
        <div class="btn-left">
          <div class="btn-icon">
            <svg viewBox="0 0 24 24"><path d="M21 3H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h5v2h8v-2h5c1.1 0 1.99-.9 1.99-2L23 5c0-1.1-.9-2-2-2zm0 14H3V5h18v12z"/></svg>
          </div>
          <div>
            <span class="btn-title">Allumer la Télé & Mode TV</span>
            <span class="btn-sub">Allume la TV Samsung + Résolution 16:9 TV + Prêt à jouer</span>
          </div>
        </div>
        <span class="btn-arrow">📺</span>
      </button>

      <button class="main-btn btn-tv-off" onclick="trigger('/tv-off')">
        <div class="btn-left">
          <div class="btn-icon">
            <svg viewBox="0 0 24 24"><path d="M13 3h-2v10h2V3zm4.83 2.17l-1.42 1.42C17.99 7.86 19 9.81 19 12c0 3.87-3.13 7-7 7s-7-3.13-7-7c0-2.19 1.01-4.14 2.58-5.42L6.17 5.17C4.23 6.82 3 9.26 3 12c0 4.97 4.03 9 9 9s9-4.03 9-9c0-2.74-1.23-5.18-3.17-6.83z"/></svg>
          </div>
          <div>
            <span class="btn-title">Éteindre la Télé & Mode MacBook</span>
            <span class="btn-sub">Éteint la TV + Passe en Mode MacBook (16:10)</span>
          </div>
        </div>
        <span class="btn-arrow">💻</span>
      </button>

      <button class="main-btn btn-esde" onclick="trigger('/launch')">
        <div class="btn-left">
          <div class="btn-icon">
            <svg viewBox="0 0 24 24"><path d="M21 6H3c-1.1 0-2 .9-2 2v8c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-10 7H8v3H6v-3H3v-2h3V8h2v3h3v2zm4.5 2c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm4-3c-.83 0-1.5-.67-1.5-1.5S18.67 9 19.5 9s1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/></svg>
          </div>
          <div>
            <span class="btn-title">Pegasus (Flixnet)</span>
            <span class="btn-sub">Interface Console Plein Écran (ferme Steam)</span>
          </div>
        </div>
        <span class="btn-arrow">▶</span>
      </button>

      <button class="main-btn btn-steam" onclick="trigger('/steam')">
        <div class="btn-left">
          <div class="btn-icon">
            <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12c0 4.84 3.44 8.87 8 9.8V15H8v-3h2V9.5C10 7.57 11.57 6 13.5 6H16v3h-2c-.55 0-1 .45-1 1v2h3v3h-3v6.95c5.05-.5 9-4.76 9-9.95 0-5.52-4.48-10-10-10z"/></svg>
          </div>
          <div>
            <span class="btn-title">Steam Big Picture</span>
            <span class="btn-sub">Bascule sur Steam Mac (ferme Pegasus)</span>
          </div>
        </div>
        <span class="btn-arrow">▶</span>
      </button>

      <button class="main-btn btn-steam-win" onclick="trigger('/steam-win')">
        <div class="btn-left">
          <div class="btn-icon">
            <svg viewBox="0 0 24 24"><path d="M3 5.55L10.95 4.4v7.15H3V5.55zm0 12.9l7.95 1.15v-7.15H3v6zm8.85 1.28L21 21v-8.55h-9.15v7.38zm0-15.46v7.28H21V3l-9.15 1.27z"/></svg>
          </div>
          <div>
            <span class="btn-title">Steam Windows (CrossOver)</span>
            <span class="btn-sub">Catalogue PC via CrossOver 26 (ferme Pegasus)</span>
          </div>
        </div>
        <span class="btn-arrow">▶</span>
      </button>

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

      <div class="section-card">
        <div class="section-header">
          <span>SORTIE AUDIO & VOLUME</span>
          <span class="section-current" id="audio-out-label">Mac mini</span>
        </div>
        <div class="mode-grid" style="grid-template-columns: repeat(3, 1fr);">
          <button class="mode-btn" id="btn-tvaudio" onclick="trigger('/audio?out=tv')">
            <span>📺</span>
            <span>TV / Mac (0 délai)</span>
          </button>
          <button class="mode-btn" id="btn-airpods" onclick="trigger('/audio?out=airpods')">
            <span>🎧</span>
            <span>AirPods</span>
          </button>
          <button class="mode-btn" id="btn-homepod" onclick="trigger('/audio?out=homepod')">
            <span>🔊</span>
            <span>HomePod Salon</span>
          </button>
        </div>
        <div class="vol-grid">
          <button class="vol-btn" data-vol="down">🔉 Vol -</button>
          <button class="vol-btn" data-vol="mute">🔇 Mute</button>
          <button class="vol-btn" data-vol="up">🔊 Vol +</button>
        </div>
      </div>

      <div class="section-card">
        <div class="section-header">
          <span>HUD TEST (FPS & SHADERS)</span>
          <span class="section-current" id="hud-status-label">Actif</span>
        </div>
        <div class="mode-grid">
          <button class="mode-btn active" id="btn-hud-on" onclick="trigger('/hud?mode=on')">
            <span>📊</span>
            <span>Afficher FPS & Shaders</span>
          </button>
          <button class="mode-btn" id="btn-hud-off" onclick="trigger('/hud?mode=off')">
            <span>🙈</span>
            <span>Masquer HUD</span>
          </button>
        </div>
      </div>

      <button class="quit-all-btn" onclick="trigger('/quit')">
        <span>⏹️</span>
        <span>Quitter le Mode Gaming (Tout fermer)</span>
      </button>
    </div>
  </div>

  <div id="toast"></div>

  <script>
    let ALL_GAMES = [];
    let CURRENT_FILTER = 'all';
    let SEARCH_QUERY = '';
    let ACTIVE_GAME_ID = '';
    let toastTimer = null;

    const FILTER_GROUPS = [
      { id: 'all', label: '📚 Tous les Jeux', match: () => true },
      { id: 'fav', label: '🔥 Favoris', match: g => g.featured },
      { id: 'recomp', label: '⛵ Recomp', match: g => g.system === 'recomp' },
      { id: 'pc', label: '💻 Jeux PC', match: g => g.system === 'pc' },
      { id: 'switch', label: '🔴 Switch', match: g => g.system === 'switch' },
      { id: 'wiiu', label: '🟦 Wii U', match: g => g.system === 'wiiu' },
      { id: 'wii', label: '🎾 Wii', match: g => g.system === 'wii' },
      { id: 'gc', label: '🟣 GameCube', match: g => g.system === 'gc' },
      { id: 'nds', label: '📱 Nintendo DS', match: g => g.system === 'nds' },
      { id: 'n64', label: '🕹️ Nintendo 64', match: g => g.system === 'n64' },
      { id: 'gba', label: '👾 GBA & Rétro', match: g => ['gba','snes','gbc','gb','nes'].includes(g.system) },
      { id: 'ps', label: '💿 PlayStation', match: g => ['psx','psp'].includes(g.system) },
    ];

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => t.classList.remove('show'), 3200);
    }

    function switchView(view) {
      document.getElementById('view-games').classList.toggle('active', view === 'games');
      document.getElementById('view-remote').classList.toggle('active', view === 'remote');
      document.getElementById('tab-btn-games').classList.toggle('active', view === 'games');
      document.getElementById('tab-btn-remote').classList.toggle('active', view === 'remote');
    }

    let API_BASE = "";
    let IS_STATIC_HOST = false;

    let LAN_FALLBACK_URL = "http://192.168.1.152:8765";

    async function detectApiBase() {
      if (location.port === "8765" || location.port === "8768") {
        API_BASE = "";
        return;
      }
      const candidates = [];
      try {
        const r = await fetch("./endpoint.json?t=" + Date.now(), { cache: "no-store" });
        if (r.ok) {
          const ep = await r.json();
          if (ep.lanUrl) LAN_FALLBACK_URL = ep.lanUrl;
          if (ep.tunnelUrl) candidates.push(ep.tunnelUrl);
          if (location.protocol === "http:" && ep.lanUrl) candidates.push(ep.lanUrl);
        }
      } catch (e) {}
      if (location.protocol === "http:") {
        candidates.push("http://127.0.0.1:8768", "http://192.168.1.152:8765", "http://192.168.1.152:8768");
      } else {
        candidates.push("http://127.0.0.1:8768");
      }
      for (const c of candidates) {
        try {
          const ctrl = new AbortController();
          const t = setTimeout(() => ctrl.abort(), 2200);
          const r = await fetch(c + "/status", { cache: "no-store", signal: ctrl.signal });
          clearTimeout(t);
          if (r.ok) { API_BASE = c; IS_STATIC_HOST = false; return; }
        } catch (e) {}
      }
      IS_STATIC_HOST = true;
    }

    function fetchJSON(path, ms) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), ms);
      const url = path.startsWith("http") || path.startsWith("./") ? path : (API_BASE + path);
      return fetch(url, { cache: 'no-store', signal: ctrl.signal })
        .then(r => r.json())
        .finally(() => clearTimeout(timer));
    }

    async function trigger(path) {
      const btn = (window.event && window.event.currentTarget) || null;
      if (btn && btn.classList.contains('pending')) return;
      if (btn) btn.classList.add('pending');
      const slow = setTimeout(() => showToast('Envoi au Mac mini M4...'), 250);
      if (IS_STATIC_HOST) {
        window.location.href = LAN_FALLBACK_URL + "/?action=" + encodeURIComponent(path);
        return;
      }
      try {
        const d = await fetchJSON(path, 45000);
        showToast(d.message || 'OK');
      } catch (e) {
        showToast(e.name === 'AbortError' ? 'Le Mac ne répond pas' : 'Erreur de connexion');
      } finally {
        clearTimeout(slow);
        if (btn) btn.classList.remove('pending');
        updateStatus();
        setTimeout(updateStatus, 1500);
      }
    }

    async function launchGame(gameId, gameName) {
      if (IS_STATIC_HOST) {
        window.location.href = LAN_FALLBACK_URL + "/?launch=" + encodeURIComponent(gameId);
        return;
      }
      ACTIVE_GAME_ID = gameId;
      renderGames();
      showToast('📺 Allumage Télé + Lancement de ' + gameName + '...');
      try {
        const d = await fetchJSON('/launch-game?id=' + encodeURIComponent(gameId), 45000);
        showToast(d.message || ('🎮 ' + gameName + ' lancé !'));
      } catch (e) {
        showToast('Erreur de connexion au Mac mini');
      } finally {
        updateStatus();
        setTimeout(updateStatus, 2000);
      }
    }

    function renderFilterPills() {
      const wrap = document.getElementById('filter-pills');
      wrap.innerHTML = FILTER_GROUPS.map(fg => {
        const count = ALL_GAMES.filter(fg.match).length;
        const active = CURRENT_FILTER === fg.id ? 'active' : '';
        return `<button class="fpill ${active}" onclick="setFilter('${fg.id}')">
          <span>${fg.label}</span>
          <span class="fpill-count">${count}</span>
        </button>`;
      }).join('');
    }

    function setFilter(fid) {
      CURRENT_FILTER = fid;
      renderFilterPills();
      renderGames();
    }

    function onSearchInput() {
      const input = document.getElementById('game-search');
      SEARCH_QUERY = (input.value || '').trim().toLowerCase();
      document.getElementById('search-clear-btn').style.display = SEARCH_QUERY ? 'flex' : 'none';
      renderGames();
    }

    function clearSearch() {
      const input = document.getElementById('game-search');
      input.value = '';
      SEARCH_QUERY = '';
      document.getElementById('search-clear-btn').style.display = 'none';
      renderGames();
    }

    function renderGames() {
      const grid = document.getElementById('games-grid');
      const fg = FILTER_GROUPS.find(g => g.id === CURRENT_FILTER) || FILTER_GROUPS[0];
      const filtered = ALL_GAMES.filter(g => {
        if (!fg.match(g)) return false;
        if (SEARCH_QUERY) {
          const hay = (g.name + ' ' + g.systemLabel + ' ' + g.badge).toLowerCase();
          return hay.includes(SEARCH_QUERY);
        }
        return true;
      });

      grid.innerHTML = filtered.map(g => {
        const isRunning = ACTIVE_GAME_ID === g.id ? 'running' : '';
        const safeName = g.name.replace(/'/g, "\'");
        return `<button class="game-card ${isRunning}" onclick="launchGame('${g.id}', '${safeName}')">
          <div class="game-cover-wrap">
            <img src="${IS_STATIC_HOST ? (g.staticCover || ('covers/' + g.id + '.jpg')) : (API_BASE + g.coverUrl)}" alt="${g.name.replace(/"/g, '&quot;')}" loading="lazy">
            <span class="game-badge" style="background: ${g.color || '#2563eb'};">${g.badge}</span>
            <span class="game-play-pill">📺 TV + JOUER</span>
          </div>
          <div class="game-info">
            <span class="game-title">${g.name}</span>
            <span class="game-sub">${g.systemLabel}</span>
          </div>
        </button>`;
      }).join('');
    }

    async function loadGames() {
      await detectApiBase();
      try {
        const res = await fetchJSON(IS_STATIC_HOST ? './games.json' : '/api/games', 8000);
        if (res && res.games) {
          ALL_GAMES = res.games;
          document.getElementById('total-games-count').textContent = String(ALL_GAMES.length);
          renderFilterPills();
          renderGames();
        }
      } catch (e) {}
      if (!IS_STATIC_HOST) {
        const params = new URLSearchParams(window.location.search);
        const autoLaunch = params.get("launch");
        const autoAction = params.get("action");
        if (autoLaunch) {
          history.replaceState({}, "", window.location.pathname);
          const g = ALL_GAMES.find(x => x.id === autoLaunch);
          setTimeout(() => launchGame(autoLaunch, g ? g.name : autoLaunch), 250);
        } else if (autoAction) {
          history.replaceState({}, "", window.location.pathname);
          setTimeout(() => trigger(autoAction), 250);
        }
      }
    }

    (function () {
      let inFlight = false, queued = null, holdTimer = null, repeatTimer = null;
      function send(dir) {
        if (inFlight) { queued = dir; return; }
        inFlight = true;
        fetchJSON('/vol?dir=' + dir, 4000)
          .then(d => { if (d && d.message) showToast(d.message); })
          .catch(() => showToast('Volume : pas de réponse'))
          .finally(() => {
            inFlight = false;
            if (queued) { const n = queued; queued = null; send(n); }
          });
      }
      function stopHold(btn) {
        if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; }
        if (repeatTimer) { clearInterval(repeatTimer); repeatTimer = null; }
        if (btn) btn.classList.remove('pressed');
      }
      document.querySelectorAll('[data-vol]').forEach(btn => {
        const dir = btn.dataset.vol;
        btn.addEventListener('pointerdown', e => {
          e.preventDefault();
          btn.classList.add('pressed');
          send(dir);
          if (dir !== 'mute') {
            holdTimer = setTimeout(() => { repeatTimer = setInterval(() => send(dir), 220); }, 380);
          }
        });
        ['pointerup', 'pointercancel', 'pointerleave'].forEach(ev =>
          btn.addEventListener(ev, () => stopHold(btn))
        );
      });
    })();

    async function updateStatus() {
      try {
        const d = await fetchJSON('/status', 5000);
        if (d.lastGame && d.lastGame.id) {
          ACTIVE_GAME_ID = d.lastGame.id;
        } else if (d.active === 'Prêt • M4') {
          ACTIVE_GAME_ID = '';
        }
        if (d.active) {
          const label = (d.lastGame && d.lastGame.name && d.active !== 'Prêt • M4')
            ? ('🎮 ' + d.lastGame.name)
            : d.active;
          document.getElementById('status-text').textContent = label;
        }
        if (d.audio) {
          document.getElementById('audio-out-label').textContent = d.audio;
          const a = d.audio.toLowerCase();
          document.getElementById('btn-tvaudio').classList.toggle('active', a.includes('samsung') || a.includes('mac') || a.includes('tv'));
          document.getElementById('btn-airpods').classList.toggle('active', a.includes('airpods'));
          document.getElementById('btn-homepod').classList.toggle('active', a.includes('homepod') || a.includes('salon'));
        }
        if (d.display) {
          const isTv = d.display.includes('1920') || d.display.includes('3840');
          const dispLabel = document.getElementById('display-mode-label');
          dispLabel.textContent = isTv ? '1920×1080 (Mode Télé 16:9)' : '1680×1050 (Mode MacBook 16:10)';
          dispLabel.classList.toggle('tv-active', isTv);
          document.getElementById('btn-disp-tv').classList.toggle('active-tv', isTv);
          document.getElementById('btn-disp-mac').classList.toggle('active', !isTv);
        }
        if (typeof d.hud === 'boolean') {
          const hudLabel = document.getElementById('hud-status-label');
          if (hudLabel) {
            hudLabel.textContent = d.hud ? 'Actif (FPS + Shaders)' : 'Masqué';
            hudLabel.classList.toggle('tv-active', d.hud);
            document.getElementById('btn-hud-on').classList.toggle('active-tv', d.hud);
            document.getElementById('btn-hud-on').classList.toggle('active', d.hud);
            document.getElementById('btn-hud-off').classList.toggle('active', !d.hud);
          }
        }
      } catch (e) {}
    }

    loadGames();
    updateStatus();
    setInterval(updateStatus, 4000);
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

def run_quiet(args, timeout=10):
    """Lance une commande avec timeout (BetterDisplay/CEC ne doivent jamais bloquer le serveur)."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None

def tv_power_state():
    """'on' | 'standby' | 'transitioning standby to on' | ... | 'unknown'"""
    if not os.path.exists(DPCD_CEC):
        return "unknown"
    res = run_quiet([DPCD_CEC, "power"], timeout=12)
    if res is None:
        return "unknown"
    for line in res.stdout.splitlines():
        if line.startswith("power="):
            return line[len("power="):].split(" (")[0].strip()
    return "unknown"

_tv_screen_lock = threading.Lock()
# tv_mirror (Recopie de l'écran) et audio_switcher (module Son) pilotent tous deux l'UI du Centre de
# contrôle par Accessibilité : on sérialise pour qu'ils ne s'ouvrent/ferment pas le panneau mutuellement.
_cc_ui_lock = threading.Lock()

def ensure_tv_screen(timeout=45, settle=6, wait=False):
    """Fait disparaître le "Screen Mirroring shield" et met la TV en recopie dès qu'elle apparaît.
    Surveille l'écran jusqu'à ce qu'il soit affiché de façon stable (le HPD de la TV peut rebondir
    pendant quelques secondes après le réveil CEC, et le shield réapparaître à chaque reconnexion)."""
    if not os.path.exists(TV_MIRROR):
        return
    # wait=True (après un réveil CEC) : attend la fin d'une surveillance courte déjà lancée par set_tv_mode
    if not (_tv_screen_lock.acquire(timeout=20) if wait else _tv_screen_lock.acquire(blocking=False)):
        return  # une surveillance est déjà en cours
    try:
        deadline = time.time() + timeout
        ok_since = None
        failures = 0
        while time.time() < deadline:
            launcher = [TV_MIRROR_LAUNCHER] if os.path.exists(TV_MIRROR_LAUNCHER) else []
            with _cc_ui_lock:
                res = run_quiet(launcher + [TV_MIRROR, "fix", "--vendor", TV_VENDOR_ID, "--mode", "mirror"], timeout=30)
            rc = res.returncode if res is not None else -1
            out = (res.stdout.strip().splitlines() or [""])[-1] if res is not None else "timeout"
            if rc == 0:
                if "already-up" not in out:
                    print(f"[tv] shield contourné -> {out}", flush=True)
                if ok_since is None:
                    ok_since = time.time()
                elif time.time() - ok_since >= settle:
                    return
            else:
                ok_since = None
                if rc == 3:
                    print("[tv] tv_mirror: Accessibilité refusée (Réglages > Confidentialité > Accessibilité)", flush=True)
                    return
                if rc == 1:
                    failures += 1
                    print(f"[tv] tv_mirror échec ({failures}) : {out}", flush=True)
                    if failures >= 3:
                        return
            time.sleep(1.5)
    finally:
        _tv_screen_lock.release()

_tv_wake_lock = threading.Lock()

def wake_tv_cec(wait_seconds=25):
    """Réveille la TV Samsung (HDMI-CEC Image View On) et bascule sur l'entrée du Mac (Active Source 2.0.0.0).
    Vérifie l'état d'alimentation et renvoie le réveil tant que la TV reste en veille."""
    if not _tv_wake_lock.acquire(blocking=False):
        return  # un réveil est déjà en cours
    try:
        if not os.path.exists(DPCD_CEC):
            # Repli : BetterDisplay (toujours avec -tagID, sinon aucun écran n'est ciblé)
            run_quiet([BETTERDISPLAY_CLI, "perform", "-tagID=" + TV_TAG_ID, "-sendCEC=wake"])
            run_quiet([BETTERDISPLAY_CLI, "perform", "-tagID=" + TV_TAG_ID, "-sendCEC=input:mac"])
            ensure_tv_screen(wait=True)
            return
        deadline = time.time() + wait_seconds
        attempt = 0
        while True:
            attempt += 1
            run_quiet([DPCD_CEC, "wake", "--pa", TV_PHYS_ADDR], timeout=12)
            time.sleep(4)
            state = tv_power_state()
            if state == "on" or state.startswith("transitioning standby"):
                # Re-affirme la source une fois la TV allumée (certaines Samsung ignorent la 1re pendant le boot)
                time.sleep(3)
                run_quiet([DPCD_CEC, "input", "--pa", TV_PHYS_ADDR], timeout=12)
                if os.path.exists(BETTERDISPLAY_CLI):
                    # La TV vient de (re)négocier le signal : ré-applique la résolution TV
                    run_quiet([BETTERDISPLAY_CLI, "set", "-tagID=" + TV_TAG_ID, "-resolution=1920x1080"], timeout=8)
                print(f"[tv] wake ok (attempt {attempt}, state={state})", flush=True)
                # Réveil HDMI -> macOS 26 peut afficher le "Screen Mirroring shield" : on le contourne.
                ensure_tv_screen(wait=True)
                return
            if time.time() > deadline or attempt >= 4:
                print(f"[tv] wake not confirmed (state={state})", flush=True)
                ensure_tv_screen(timeout=20, wait=True)
                return
    finally:
        _tv_wake_lock.release()

def set_tv_mode(wake_tv=True):
    wake_mac()
    if wake_tv:
        # Réveil TV en arrière-plan : la réponse HTTP reste instantanée pour l'iPhone
        threading.Thread(target=wake_tv_cec, daemon=True).start()
        # Si la TV était déjà allumée mais bloquée sur le shield, on le contourne tout de suite.
        threading.Thread(target=ensure_tv_screen, kwargs={"timeout": 12, "settle": 3}, daemon=True).start()
    if os.path.exists(BETTERDISPLAY_CLI):
        ensure_betterdisplay()
        if wake_tv:
            run_quiet([BETTERDISPLAY_CLI, "set", "-tagID=6", "-connected=on"], timeout=8)
            run_quiet([BETTERDISPLAY_CLI, "set", "-tagID=" + DUMMY_TAG_ID, "-hardwareBacklight=on"], timeout=8)
            run_quiet([BETTERDISPLAY_CLI, "perform", "-connectAllDisplays"], timeout=8)
        # Passe la résolution en 1920x1080 HiDPI (4K 3840x2160 natif 60Hz 16:9 Mode Télévision)
        run_quiet([BETTERDISPLAY_CLI, "set", "-tagID=" + DUMMY_TAG_ID, "-displayModeNumber=34"], timeout=8)
        run_quiet([BETTERDISPLAY_CLI, "set", "-tagID=" + TV_TAG_ID, "-resolution=1920x1080"], timeout=8)

def set_macbook_mode():
    wake_mac()
    if os.path.exists(BETTERDISPLAY_CLI):
        ensure_betterdisplay()
        # Repasse en 1680x1050 (16:10) pour le partage d'écran MacBook Air
        subprocess.run([BETTERDISPLAY_CLI, "set", "-tagID=10", "-displayModeNumber=31"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def standby_tv_cec():
    """Met la TV Samsung en veille via HDMI-CEC (Standby 0x36) et vérifie l'extinction."""
    if not os.path.exists(DPCD_CEC):
        if os.path.exists(BETTERDISPLAY_CLI):
            run_quiet([BETTERDISPLAY_CLI, "perform", "-tagID=" + TV_TAG_ID, "-sendCEC=standby"], timeout=8)
        return
    with _cec_lock:
        run_quiet([DPCD_CEC, "standby", "--pa", TV_PHYS_ADDR], timeout=8)
    time.sleep(2.5)
    state = tv_power_state()
    if state == "on":
        # Certaines TV Samsung n'acceptent Standby que de la source active : ré-affirme Active Source puis Standby
        with _cec_lock:
            run_quiet([DPCD_CEC, "input", "--pa", TV_PHYS_ADDR], timeout=8)
            time.sleep(0.4)
            run_quiet([DPCD_CEC, "standby", "--pa", TV_PHYS_ADDR], timeout=8)
        time.sleep(2.0)
        state = tv_power_state()
    print(f"[tv] standby terminé (state={state})", flush=True)

def get_current_audio():
    """Sortie réelle (CoreAudio). AirPlay actif => "HomePod Salon (AirPlay)"."""
    if os.path.exists(AUDIO_SWITCHER):
        res = run_quiet([AUDIO_SWITCHER, "current"], timeout=5)
        out = res.stdout.strip() if res is not None else ""
        if out:
            return out
    return "Mac mini"

def run_audio_switcher(*args, timeout=40):
    """Exécute audio_switcher (d'abord directement pour utiliser le processus responsable parent,
    puis via run_disclaimed si besoin)."""
    with _cc_ui_lock:
        res = run_quiet([AUDIO_SWITCHER] + list(args), timeout=timeout)
        if res is not None and res.returncode == 3 and os.path.exists(TV_MIRROR_LAUNCHER):
            res = run_quiet([TV_MIRROR_LAUNCHER, AUDIO_SWITCHER] + list(args), timeout=timeout)
    if res is None:
        return -1, "ERR:timeout"
    lines = res.stdout.strip().splitlines()
    return res.returncode, (lines[-1] if lines else "")

_audio_lock = threading.Lock()

# Préférence de sortie choisie sur l'iPhone. "tv" = HDMI SAMSUNG (repli Mac mini) sans délai :
# les lancements Mode TV / Steam ne rebasculent alors plus sur le HomePod (AirPlay ≈ 2 s de latence).
AUDIO_PREF_FILE = os.path.expanduser("~/ES-DE/scripts/.audio_output_pref")

def get_audio_pref():
    try:
        with open(AUDIO_PREF_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "homepod"

def set_audio_pref(value):
    try:
        with open(AUDIO_PREF_FILE, "w", encoding="utf-8") as f:
            f.write(value)
    except OSError as e:
        print(f"[audio] préférence non enregistrée: {e}", flush=True)

def switch_audio_tv(reason=""):
    """Sortie sans délai : TV SAMSUNG en HDMI, sinon haut-parleurs du Mac mini (jamais le dummy 4k60)."""
    if not os.path.exists(AUDIO_SWITCHER):
        return -1, "ERR:audio_switcher absent"
    with _audio_lock:
        rc, out = run_audio_switcher("samsung", timeout=20)
        if not out.startswith("OK:"):
            rc, out = run_audio_switcher("mac", timeout=20)
        print(f"[audio] {reason}: tv -> rc={rc} {out}", flush=True)
        return rc, out

def switch_audio_homepod(reason="", respect_airpods=True):
    """Bascule le son système sur le HomePod « Salon » (AirPlay). Repli SAMSUNG / Mac mini, jamais le
    dummy plug 4k60. Si respect_airpods et que des AirPods sont la sortie active, on n'y touche pas."""
    if not os.path.exists(AUDIO_SWITCHER):
        return -1, "ERR:audio_switcher absent"
    if respect_airpods and get_audio_pref() == "tv":
        cur = get_current_audio()
        if "airpods" in cur.lower() or "samsung" in cur.lower():
            print(f"[audio] {reason}: préférence TV sans délai, sortie conservée ({cur})", flush=True)
            return 0, f"OK:{cur} (conservé)"
        return switch_audio_tv(reason=f"{reason} (préférence TV)")
    with _audio_lock:
        if respect_airpods and "airpods" in get_current_audio().lower():
            print(f"[audio] {reason}: AirPods actifs, sortie conservée", flush=True)
            return 0, "OK:AirPods (conservés)"
        rc, out = run_audio_switcher("homepod")
        print(f"[audio] {reason}: homepod -> rc={rc} {out}", flush=True)
        if rc == 3:
            print("[audio] audio_switcher: Accessibilité refusée (Réglages > Confidentialité > Accessibilité "
                  "> audio_switcher). Pour redemander : scripts/tv_mirror/run_disclaimed scripts/audio_switcher request-access",
                  flush=True)
        return rc, out

def switch_audio_homepod_async(reason):
    threading.Thread(target=switch_audio_homepod, kwargs={"reason": reason}, daemon=True).start()

HUD_FLAG_PATH = "/Users/thomaslefevre/ES-DE/scripts/.hud_enabled"
SHADER_HUD_BIN = "/Users/thomaslefevre/ES-DE/scripts/ryujinx_shader_hud"

def is_hud_enabled():
    return os.path.exists(HUD_FLAG_PATH)

def set_hud_enabled(enable: bool):
    if enable:
        with open(HUD_FLAG_PATH, "w") as f:
            f.write("1\n")
        subprocess.run(["/bin/launchctl", "setenv", "MTL_HUD_ENABLED", "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # If Ryujinx is already running, launch ryujinx_shader_hud if not running
        if subprocess.run(["/usr/bin/pgrep", "-f", "Ryujinx.app/Contents/MacOS/Ryujinx"], stdout=subprocess.DEVNULL).returncode == 0:
            if subprocess.run(["/usr/bin/pgrep", "-f", SHADER_HUD_BIN], stdout=subprocess.DEVNULL).returncode != 0:
                subprocess.Popen([SHADER_HUD_BIN], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if subprocess.run(["/usr/bin/pgrep", "-f", r"steamapps\\common\\"], stdout=subprocess.DEVNULL).returncode == 0:
            if subprocess.run(["/usr/bin/pgrep", "-x", "wine_fps_hud"], stdout=subprocess.DEVNULL).returncode != 0:
                subprocess.Popen(["/Users/thomaslefevre/ES-DE/scripts/wine_fps_hud"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        if os.path.exists(HUD_FLAG_PATH):
            try:
                os.remove(HUD_FLAG_PATH)
            except OSError:
                pass
        subprocess.run(["/bin/launchctl", "unsetenv", "MTL_HUD_ENABLED"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["/usr/bin/pkill", "-f", SHADER_HUD_BIN], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["/usr/bin/killall", "-9", "wine_fps_hud"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _process_snapshot():
    """Un seul appel ps (au lieu de ~13 pgrep) : (noms d'exécutables, lignes de commande)."""
    try:
        res = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,args="], capture_output=True, text=True, timeout=3)
        names_res = subprocess.run(["/bin/ps", "-axo", "comm="], capture_output=True, text=True, timeout=3)
    except (subprocess.TimeoutExpired, OSError):
        return None
    me = str(os.getpid())
    args = []
    for line in res.stdout.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if pid != me:
            args.append(cmd.strip())
    names = {os.path.basename(n.strip()) for n in names_res.stdout.splitlines()}
    return names, args

def get_active_status():
    snap = _process_snapshot()
    for proc, label in [
        (r"Breath of the Wild\.app/Contents/MacOS/", "🌿 Breath of the Wild (Recomp)"),
        ("wwhd", "⛵ Wind Waker HD (Recomp)"),
        ("Ryujinx", "Jeu Switch"),
        ("Dolphin", "Jeu GC/Wii"),
        ("PCSX2-v2.8.2", "Jeu PS2"),
        ("RPCS3", "Jeu PS3"),
        ("Cemu", "Jeu Wii U"),
        ("Azahar", "Jeu 3DS"),
        ("DuckStation", "Jeu PS1"),
        ("PPSSPPSDL", "Jeu PSP"),
        ("RetroArch", "RetroArch Actif"),
        ("CoJGunslinger", "Call of Juarez (CrossOver)"),
        (r"steamapps\\common\\", "Jeu PC (CrossOver)"),
        ("Steam.exe", "Steam CrossOver Actif"),
        (WINE_PROCESS_PATTERN, "Steam CrossOver Actif"),
        ("steam_osx", "Steam Actif"),
        ("pegasus-fe", "Pegasus Actif"),
        ("ES-DE", "ES-DE Actif"),
    ]:
        # Nom exact pour pegasus-fe / ES-DE : en plein texte, le chemin ~/ES-DE/scripts/ matcherait toujours.
        if snap is None:
            match_flag = "-x" if proc in ("pegasus-fe", "ES-DE") else "-f"
            res = subprocess.run(["/usr/bin/pgrep", match_flag, proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                return label
            continue
        names, args = snap
        if proc in ("pegasus-fe", "ES-DE"):
            if proc in names:
                return label
        elif any(re.search(proc, a) for a in args):
            return label
    return "Prêt • M4"

def close_processes(proc_list):
    for proc in proc_list:
        subprocess.run(["/usr/bin/killall", "-9", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if "ipcserver" in proc_list:
        # launchd relance ipcserver après chaque kill tant que le job Steam Mac reste chargé.
        subprocess.run(["/bin/launchctl", "remove", "com.valvesoftware.steam.ipctool"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if "wineserver" in proc_list:
        close_crossover()

def close_crossover():
    """Arrêt propre de la bouteille (laisse Steam écrire son état), puis kill des survivants."""
    try:
        subprocess.run(
            [CROSSOVER_BIN + "/wineserver", "-k"],
            env=dict(os.environ, WINEPREFIX=CROSSOVER_BOTTLE),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass
    time.sleep(0.5)
    subprocess.run(["/usr/bin/pkill", "-9", "-f", WINE_PROCESS_PATTERN], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["/usr/bin/pkill", "-9", "-f", "CrossOver-Hosted Application/wine"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ------------------------------------------------------------------ Volume
# La TV en HDMI n'a pas de volume logiciel macOS (« output volume: missing value ») : osascript ne
# fait rien. On envoie donc les touches volume de la télécommande à la TV en HDMI-CEC
# (User Control Pressed 0x44 + 0x41/0x42/0x43, puis Released 0x45). Autres sorties : volume système.
CEC_VOL_KEYS = {"up": "41", "down": "42", "mute": "43"}
SYSTEM_VOL_STEP = 6
_cec_lock = threading.Lock()
_vol_queue = queue.Queue()
_audio_cache = {"t": 0.0, "value": ""}

def current_audio_cached(max_age=2.0):
    now = time.time()
    if now - _audio_cache["t"] > max_age:
        _audio_cache["value"] = get_current_audio()
        _audio_cache["t"] = now
    return _audio_cache["value"]

def invalidate_audio_cache():
    _audio_cache["t"] = 0.0

def is_hdmi_tv_output(name):
    n = (name or "").lower()
    return "samsung" in n or "hdmi" in n

def cec_volume_key(direction):
    key = CEC_VOL_KEYS[direction]
    with _cec_lock:
        r = run_quiet([DPCD_CEC, "send", f"40:44:{key}"], timeout=3)
        run_quiet([DPCD_CEC, "send", "40:45"], timeout=3)
    return r is not None and r.returncode == 0

def _vol_worker():
    while True:
        direction = _vol_queue.get()
        try:
            if not cec_volume_key(direction):
                print(f"[vol] CEC {direction} non acquitté par la TV", flush=True)
        except Exception as e:
            print(f"[vol] erreur CEC: {e}", flush=True)

threading.Thread(target=_vol_worker, daemon=True).start()

def queue_tv_volume(direction):
    if _vol_queue.qsize() < 6:  # au-delà, on jette : évite que le volume continue après relâchement
        _vol_queue.put(direction)

# La Samsung ignore les touches volume HDMI-CEC : le volume TV est donc logiciel, géré par
# tv_volume/tv_volume (process tap Core Audio, LaunchAgent com.thomas.tvvolume, UDP 127.0.0.1:8766).
TV_VOLUME_ADDR = ("127.0.0.1", 8766)

def tv_soft_volume(direction):
    """Renvoie {"level", "muted", "active", "device"} ou None si le helper ne répond pas."""
    import socket
    cmd = {"up": "up", "down": "down", "mute": "mute"}.get(direction, "get")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.8)
            sock.sendto(cmd.encode(), TV_VOLUME_ADDR)
            data = sock.recv(256).decode("utf-8", "replace")
    except OSError:
        return None
    info = dict(kv.split("=", 1) for kv in data.split() if "=" in kv)
    try:
        return {"level": int(info.get("level", "0")), "muted": info.get("muted") == "1",
                "active": info.get("active") == "1", "device": info.get("device", "")}
    except ValueError:
        return None

def system_volume(direction):
    """Volume macOS de la sortie courante. Renvoie "NA" si la sortie n'a pas de volume logiciel."""
    if direction == "mute":
        script = (
            'set m to output muted of (get volume settings)\n'
            'if m is missing value then return "NA"\n'
            'set volume output muted (not m)\n'
            'if m then return "unmuted"\n'
            'return "muted"'
        )
    else:
        step = SYSTEM_VOL_STEP if direction == "up" else -SYSTEM_VOL_STEP
        script = (
            'set v to output volume of (get volume settings)\n'
            'if v is missing value then return "NA"\n'
            f'set v to v + ({step})\n'
            'if v > 100 then set v to 100\n'
            'if v < 0 then set v to 0\n'
            'set volume output volume v\n'
            'if v > 0 then set volume output muted false\n'
            'return v as text'
        )
    res = run_quiet(["/usr/bin/osascript", "-e", script], timeout=4)
    if res is None or res.returncode != 0:
        return "NA"
    return res.stdout.strip() or "NA"

# ------------------------------------------------------------------ Actions longues en arrière-plan
# BetterDisplay, CEC, kill/lancement d'apps : plusieurs secondes. L'iPhone reçoit la réponse tout de
# suite ; les actions s'exécutent dans l'ordre des appuis (verrou) pour ne pas se marcher dessus.
_action_lock = threading.Lock()

def run_action_bg(fn, *args, **kwargs):
    def _run():
        with _action_lock:
            try:
                fn(*args, **kwargs)
            except Exception as e:
                print(f"[action] {getattr(fn, '__name__', fn)}: {e}", flush=True)
    threading.Thread(target=_run, daemon=True).start()

def action_tv_gaming(launch_esde):
    set_tv_mode(wake_tv=True)
    if launch_esde:
        close_processes(["ES-DE"])
        subprocess.Popen(["/usr/bin/open", "-a", "/Applications/Pegasus.app"])
        subprocess.Popen(["/usr/bin/osascript", "-e", 'tell application "Pegasus" to activate'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def action_tv_off():
    if os.path.exists(DPCD_CEC):
        with _cec_lock:
            run_quiet([DPCD_CEC, "standby", "--pa", TV_PHYS_ADDR], timeout=8)
    elif os.path.exists(BETTERDISPLAY_CLI):
        run_quiet([BETTERDISPLAY_CLI, "perform", "-tagID=" + TV_TAG_ID, "-sendCEC=standby"], timeout=8)
    set_macbook_mode()
    if is_hdmi_tv_output(get_current_audio()) and os.path.exists(AUDIO_SWITCHER):
        with _audio_lock:
            run_audio_switcher("mac", timeout=15)
        invalidate_audio_cache()
    threading.Thread(target=standby_tv_cec, daemon=True).start()

def action_launch_esde():
    set_tv_mode(wake_tv=True)
    close_processes(["pegasus-fe", "ES-DE"] + STEAM_PROCESSES + EMULATOR_PROCESSES)
    subprocess.Popen(["/usr/bin/open", "-a", "/Applications/Pegasus.app"])
    subprocess.Popen(["/usr/bin/osascript", "-e", 'tell application "Pegasus" to activate'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def action_launch(close_list, cmd):
    set_tv_mode(wake_tv=True)
    close_processes(close_list)
    subprocess.Popen(cmd)

def action_quit():
    close_processes(GAMING_PROCESSES)
    set_macbook_mode()


import hashlib
import xml.etree.ElementTree as ET

ROMS_ROOT = "/Users/thomaslefevre/Games/ROMs"
GAMELISTS_ROOT = "/Users/thomaslefevre/ES-DE/gamelists"
MEDIA_ROOT = "/Users/thomaslefevre/ES-DE/downloaded_media"
SCRIPTS_DIR = "/Users/thomaslefevre/ES-DE/scripts"

SYSTEM_DEFS = [
    ("switch", "Nintendo Switch", "SWITCH", "#ef4444", "Switch", [".nsp", ".xci"], lambda rom: [f"{SCRIPTS_DIR}/ryujinx_launch.sh", rom]),
    ("wiiu", "Nintendo Wii U", "WII U", "#0ea5e9", "WiiU", [".wua", ".wud", ".wux", ".rpx"], lambda rom: [f"{SCRIPTS_DIR}/cemu_launch.sh", rom]),
    ("wii", "Nintendo Wii", "WII", "#38bdf8", "Wii", [".rvz", ".iso", ".wbfs"], lambda rom: [f"{SCRIPTS_DIR}/dolphin_launch.sh", rom]),
    ("gc", "Nintendo GameCube", "GAMECUBE", "#8b5cf6", "GameCube", [".rvz", ".iso", ".gcm"], lambda rom: [f"{SCRIPTS_DIR}/dolphin_launch.sh", rom]),
    ("nds", "Nintendo DS", "NDS", "#ec4899", "NDS", [".nds"], lambda rom: [f"{SCRIPTS_DIR}/retroarch_launch.sh", "melondsds_libretro.dylib", rom]),
    ("n64", "Nintendo 64", "N64", "#10b981", "N64", [".z64", ".n64", ".v64"], lambda rom: [f"{SCRIPTS_DIR}/retroarch_launch.sh", "mupen64plus_next_libretro.dylib", rom]),
    ("gba", "Game Boy Advance", "GBA", "#6366f1", "GBA", [".gba"], lambda rom: [f"{SCRIPTS_DIR}/retroarch_launch.sh", "mgba_libretro.dylib", rom]),
    ("snes", "Super Nintendo", "SNES", "#a855f7", "SNES", [".sfc", ".smc"], lambda rom: [f"{SCRIPTS_DIR}/retroarch_launch.sh", "snes9x_libretro.dylib", rom]),
    ("gbc", "Game Boy Color", "GBC", "#f59e0b", "GBC", [".gbc"], lambda rom: [f"{SCRIPTS_DIR}/retroarch_launch.sh", "gambatte_libretro.dylib", rom]),
    ("gb", "Game Boy", "GB", "#84cc16", "GB", [".gb"], lambda rom: [f"{SCRIPTS_DIR}/retroarch_launch.sh", "gambatte_libretro.dylib", rom]),
    ("nes", "Nintendo NES", "NES", "#f43f5e", "NES", [".nes"], lambda rom: [f"{SCRIPTS_DIR}/retroarch_launch.sh", "mesen_libretro.dylib", rom]),
    ("psx", "PlayStation 1", "PS1", "#3b82f6", "PS1", [".cue", ".chd"], lambda rom: [f"{SCRIPTS_DIR}/duckstation_launch.sh", rom]),
    ("psp", "PlayStation Portable", "PSP", "#06b6d4", "PSP", [".iso", ".cso"], lambda rom: [f"{SCRIPTS_DIR}/ppsspp_launch.sh", rom]),
]

_CATALOG_CACHE = {"t": 0.0, "games": [], "by_id": {}}
LAST_LAUNCHED_GAME = {"id": "", "name": "", "t": 0.0}

def get_games_catalog(force=False):
    now = time.time()
    if not force and _CATALOG_CACHE["games"] and (now - _CATALOG_CACHE["t"] < 30.0):
        return _CATALOG_CACHE["games"], _CATALOG_CACHE["by_id"]

    games = [
        {
            "id": "botw_recomp",
            "name": "Zelda: Breath of the Wild (Recomp Natif M4 4K)",
            "system": "recomp",
            "systemLabel": "Recomp Natif M4",
            "badge": "RECOMP M4",
            "color": "#10b981",
            "coverPath": f"{MEDIA_ROOT}/switch/covers/The Legend of Zelda Breath of the Wild [01007EF00011E000][v0](eShop).jpg",
            "launchCmd": [f"{SCRIPTS_DIR}/botw_recomp_launch.sh"],
            "featured": True,
        },
        {
            "id": "wwhd_recomp",
            "name": "Zelda: The Wind Waker HD (Recomp Natif M4)",
            "system": "recomp",
            "systemLabel": "Recomp Natif M4",
            "badge": "RECOMP M4",
            "color": "#10b981",
            "coverPath": f"{MEDIA_ROOT}/wiiu/covers/The Wind Waker HD (EU).jpg",
            "launchCmd": [f"{SCRIPTS_DIR}/wwhd_recomp_launch.sh"],
            "featured": True,
        },
        {
            "id": "coj_gunslinger",
            "name": "Call of Juarez: Gunslinger",
            "system": "pc",
            "systemLabel": "Jeu PC (Steam / CrossOver)",
            "badge": "JEUX PC",
            "color": "#f97316",
            "coverPath": f"{MEDIA_ROOT}/steam/covers/Call of Juarez Gunslinger (Windows).jpg",
            "launchCmd": ["/Users/thomaslefevre/Games/ROMs/steam/Call of Juarez Gunslinger (Windows).sh"],
            "featured": True,
        },
        {
            "id": "forestia_1998",
            "name": "Forestia (1998 — Édition CD-ROM)",
            "system": "pc",
            "systemLabel": "Jeu PC (DOS CD-ROM)",
            "badge": "JEUX PC",
            "color": "#22c55e",
            "coverPath": f"{MEDIA_ROOT}/desktop/covers/Forestia.png",
            "launchCmd": ["/Users/thomaslefevre/.t3/projects/forestia-mobile/moonlight_forestia.sh"],
            "featured": True,
        },
    ]

    for sys_id, sys_label, badge, color, folder, exts, cmd_fn in SYSTEM_DEFS:
        gl_map = {}
        gl_file = os.path.join(GAMELISTS_ROOT, sys_id, "gamelist.xml")
        if os.path.isfile(gl_file):
            try:
                for g in ET.parse(gl_file).findall("game"):
                    p = os.path.basename(g.findtext("path", ""))
                    n = g.findtext("name", "").strip()
                    if p and n:
                        gl_map[p] = n
            except Exception:
                pass
        rom_dir = os.path.join(ROMS_ROOT, folder)
        for fname, title in sorted(gl_map.items(), key=lambda kv: kv[1].lower()):
            stem, ext = os.path.splitext(fname)
            if ext.lower() not in exts:
                continue
            full_rom = os.path.join(rom_dir, fname)
            cov = os.path.join(MEDIA_ROOT, sys_id, "covers", stem + ".jpg")
            if not os.path.isfile(cov):
                cov_png = os.path.join(MEDIA_ROOT, sys_id, "covers", stem + ".png")
                cov = cov_png if os.path.isfile(cov_png) else ICON_PATH
            gid = sys_id + "_" + hashlib.md5(fname.encode("utf-8")).hexdigest()[:10]
            is_feat = sys_id in ("switch", "wiiu", "wii") or any(
                k in title.lower() for k in ("zelda", "mario", "luigi", "metroid", "pokemon", "pokémon", "colosseum", "ssx")
            )
            games.append({
                "id": gid,
                "name": title,
                "system": sys_id,
                "systemLabel": sys_label,
                "badge": badge,
                "color": color,
                "coverPath": cov,
                "launchCmd": cmd_fn(full_rom),
                "featured": is_feat,
            })

    by_id = {g["id"]: g for g in games}
    _CATALOG_CACHE["t"] = now
    _CATALOG_CACHE["games"] = games
    _CATALOG_CACHE["by_id"] = by_id
    return games, by_id

def action_launch_game(game):
    LAST_LAUNCHED_GAME["id"] = game["id"]
    LAST_LAUNCHED_GAME["name"] = game["name"]
    LAST_LAUNCHED_GAME["t"] = time.time()
    set_tv_mode(wake_tv=True)
    close_processes(["pegasus-fe", "ES-DE"] + STEAM_PROCESSES + EMULATOR_PROCESSES)
    cmd = ([TV_MIRROR_LAUNCHER] if os.path.exists(TV_MIRROR_LAUNCHER) else []) + game["launchCmd"]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

class GamingHandler(http.server.BaseHTTPRequestHandler):
    # HTTP/1.1 keep-alive : l'iPhone réutilise la connexion (pas de nouvelle poignée TCP à chaque tap).
    protocol_version = "HTTP/1.1"
    timeout = 30  # ferme les connexions inactives

    def log_message(self, format, *args):
        pass

    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors()
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(HTML_PAGE.encode("utf-8"))))
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
            act = get_active_status()
            return self.send_json({
                "status": "ok",
                "active": act,
                "lastGame": LAST_LAUNCHED_GAME if act != "Prêt • M4" else {"id": "", "name": ""},
                "audio": get_current_audio(),
                "display": get_current_display(),
                "hud": is_hud_enabled(),
            })

        if path == "/api/games":
            games, _ = get_games_catalog()
            pub = [
                {
                    "id": g["id"],
                    "name": g["name"],
                    "system": g["system"],
                    "systemLabel": g["systemLabel"],
                    "badge": g["badge"],
                    "color": g["color"],
                    "coverUrl": f"/cover/{g['id']}",
                    "featured": g["featured"],
                }
                for g in games
            ]
            return self.send_json({"status": "ok", "count": len(pub), "games": pub})

        if path.startswith("/cover/"):
            gid = urllib.parse.unquote(path[len("/cover/"):].strip("/"))
            _, by_id = get_games_catalog()
            g = by_id.get(gid)
            cov_path = g["coverPath"] if g and os.path.isfile(g["coverPath"]) else ICON_PATH
            if os.path.isfile(cov_path):
                with open(cov_path, "rb") as f:
                    data = f.read()
                ctype = "image/png" if cov_path.lower().endswith(".png") else "image/jpeg"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(data)))
                self._send_cors()
                self.end_headers()
                self.wfile.write(data)
                return

        if path == "/launch-game":
            gid = qs.get("id", [""])[0]
            _, by_id = get_games_catalog()
            game = by_id.get(gid)
            if not game:
                return self.send_json({"status": "error", "message": f"⚠️ Jeu introuvable ({gid})"})
            switch_audio_homepod_async("launch-game")
            run_action_bg(action_launch_game, game)
            return self.send_json({
                "status": "ok",
                "game": game["name"],
                "id": game["id"],
                "message": f"📺 Télé allumée • Lancement de {game['name']} !"
            })

        if path == "/hud":
            mode = qs.get("mode", ["toggle"])[0]
            new_state = (not is_hud_enabled()) if mode == "toggle" else (mode == "on")
            set_hud_enabled(new_state)
            if new_state:
                return self.send_json({"status": "ok", "hud": True, "message": "📊 HUD FPS + Alerte Shaders activés !"})
            else:
                return self.send_json({"status": "ok", "hud": False, "message": "🙈 HUD FPS & Shaders masqués"})

        if path == "/tv-gaming":
            switch_audio_homepod_async("tv-gaming")
            # Bascule aussi le son sur le salon / TV si disponible, et lance ES-DE si rien ne tourne
            launch_esde = get_active_status() == "Prêt • M4"
            run_action_bg(action_tv_gaming, launch_esde)
            if launch_esde:
                return self.send_json({"status": "ok", "message": "📺 Télé allumée • Résolution TV 1080p (4K) • Pegasus (Flixnet) prêt !"})
            return self.send_json({"status": "ok", "message": "📺 Télé allumée & Résolution TV 1080p (4K) activée !"})

        if path == "/tv-off":
            run_action_bg(action_tv_off)
            return self.send_json({"status": "ok", "message": "🌙 Télé éteinte & Mode MacBook (1680×1050) activé !"})

        if path == "/display":
            mode = qs.get("mode", ["tv"])[0]
            if mode == "tv":
                run_action_bg(set_tv_mode, wake_tv=True)
                return self.send_json({"status": "ok", "message": "📺 Télé allumée & Résolution TV (1920×1080 HiDPI) activée !"})
            elif mode == "mac":
                run_action_bg(set_macbook_mode)
                return self.send_json({"status": "ok", "message": "💻 Résolution MacBook (1680×1050) restaurée !"})

        if path in ("/launch", "/gaming"):
            switch_audio_homepod_async(path.strip("/"))
            # Ferme Steam Mac & Steam Windows avant de lancer ES-DE (en arrière-plan)
            run_action_bg(action_launch_esde)
            return self.send_json({"status": "ok", "message": "🎮 TV en 1080p + Pegasus (Flixnet) lancé !"})

        if path == "/steam":
            switch_audio_homepod_async("steam")
            # Ferme ES-DE et les émulateurs avant de lancer Steam Big Picture (en arrière-plan)
            run_action_bg(action_launch, ["pegasus-fe", "ES-DE"] + EMULATOR_PROCESSES,
                          ["/Applications/Steam Big Picture.app/Contents/MacOS/SteamBigPicture"])
            return self.send_json({"status": "ok", "message": "🚀 TV en 1080p + Steam Big Picture lancé !"})

        if path == "/steam-win":
            switch_audio_homepod_async("steam-win")
            run_action_bg(action_launch, ["pegasus-fe", "ES-DE", "steam_osx", "Steam Helper", "ipcserver"] + EMULATOR_PROCESSES,
                          ["/Applications/Steam Windows (Big Picture).app/Contents/MacOS/SteamWindowsBigPicture"])
            return self.send_json({"status": "ok", "message": "🪟 Steam Windows (CrossOver 26) lancé !"})

        if path == "/audio":
            invalidate_audio_cache()
            target = qs.get("out", [""])[0]
            if target in ("tv", "samsung", "mac"):
                set_audio_pref("tv")
                rc, res = switch_audio_tv(reason="bouton TV sans délai")
                if res.startswith("OK:"):
                    dev = res.split(":", 1)[1]
                    return self.send_json({"status": "ok", "message": f"📺 Son sans délai sur {dev}"})
                return self.send_json({"status": "ok", "message": "⚠️ Sortie TV / Mac introuvable"})
            if target == "airpods":
                with _audio_lock:
                    rc, res = run_audio_switcher("airpods")
                if res.startswith("OK:"):
                    dev = res.split(":", 1)[1]
                    return self.send_json({"status": "ok", "message": f"🎧 Son basculé sur {dev}"})
                return self.send_json({"status": "ok", "message": "🎧 AirPods non détectés à proximité"})
            elif target == "homepod":
                set_audio_pref("homepod")
                rc, res = switch_audio_homepod(reason="bouton HomePod", respect_airpods=False)
                if res.startswith("OK:"):
                    dev = res.split(":", 1)[1]
                    return self.send_json({"status": "ok", "message": f"🔊 Son basculé sur {dev}"})
                if rc == 3:
                    return self.send_json({"status": "ok", "message": "⚠️ Autoriser audio_switcher dans Réglages > Accessibilité (son sur la TV en attendant)"})
                if res.startswith("FALLBACK:"):
                    dev = res.split(":", 1)[1].split(" (")[0]
                    return self.send_json({"status": "ok", "message": f"⚠️ HomePod Salon injoignable • son sur {dev}"})
                return self.send_json({"status": "ok", "message": "⚠️ HomePod Salon injoignable"})

        if path == "/vol":
            direction = qs.get("dir", [""])[0]
            if direction not in CEC_VOL_KEYS:
                return self.send_json({"status": "error", "message": "Commande volume inconnue"})
            tv_msgs = {"up": "🔊 Volume TV +", "down": "🔉 Volume TV −", "mute": "🔇 Mute TV"}
            out = current_audio_cached()
            if is_hdmi_tv_output(out):
                tv = tv_soft_volume(direction)
                if tv and tv["active"]:
                    if tv["muted"]:
                        msg = "🔇 TV coupée"
                    else:
                        msg = f"{'🔉' if direction == 'down' else '🔊'} Volume TV {tv['level']}%"
                    return self.send_json({"status": "ok", "target": "tv", "level": tv["level"], "message": msg})
                if os.path.exists(DPCD_CEC):
                    queue_tv_volume(direction)  # dernier recours (la Samsung l'ignore en général)
                why = "helper tv_volume arrêté" if tv is None else "autorisation Enregistrement audio manquante ?"
                return self.send_json({"status": "error", "target": "tv", "message": f"⚠️ Volume TV indisponible ({why})"})
            res = system_volume(direction)
            if res == "NA":
                # Sortie sans volume logiciel (HDMI inconnu…) : repli sur la télécommande CEC de la TV
                if os.path.exists(DPCD_CEC):
                    queue_tv_volume(direction)
                    return self.send_json({"status": "ok", "target": "tv", "message": tv_msgs[direction]})
                return self.send_json({"status": "error", "message": f"⚠️ Volume non réglable sur {out}"})
            if direction == "mute":
                msg = "🔇 Son coupé" if res == "muted" else "🔊 Son rétabli"
            else:
                msg = f"{'🔊' if direction == 'up' else '🔉'} Volume {res}%"
            return self.send_json({"status": "ok", "target": "system", "level": res, "message": msg})

        if path == "/quit":
            run_action_bg(action_quit)
            return self.send_json({"status": "ok", "message": "⏹️ Jeux fermés & Résolution MacBook restaurée"})

        body = HTML_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def quit_active_emulator_to_esde():
    """Ferme proprement l'émulateur ou le jeu Steam/Whisky en cours et redonne le focus à ES-DE."""
    active_procs = []
    for proc in EMULATOR_PROCESSES:
        res = subprocess.run(["/usr/bin/pgrep", "-x", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0:
            res = subprocess.run(["/usr/bin/pgrep", "-f", f"/{proc}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            active_procs.append(proc)
    # Vérifie aussi si un jeu Windows (steamapps\common\) ou Steam tourne
    win_game = subprocess.run(["/usr/bin/pgrep", "-f", r"steamapps\\common\\"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    steam_running = any(
        subprocess.run(["/usr/bin/pgrep", "-f", sp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        for sp in ("Steam.exe", "steam.exe", "steam_osx", WINE_PROCESS_PATTERN)
    )
    if not active_procs and not win_game and not steam_running:
        return False
    print(f"[gamepad] Select+Start détecté -> fermeture de {active_procs or ['Steam/Whisky']} et retour à Pegasus", flush=True)
    if win_game:
        subprocess.run(["/usr/bin/pkill", "-15", "-f", r"steamapps\\common\\"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for proc in active_procs:
        subprocess.run(["/usr/bin/killall", "-15", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.45)
    if win_game:
        subprocess.run(["/usr/bin/pkill", "-9", "-f", r"steamapps\\common\\"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for proc in active_procs:
        subprocess.run(["/usr/bin/killall", "-9", proc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if steam_running:
        close_processes(STEAM_PROCESSES)
    # 3. Relance ou remet Pegasus (Flixnet) au premier plan
    close_processes(["ES-DE"])
    pegasus_running = subprocess.run(["/usr/bin/pgrep", "-x", "pegasus-fe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not pegasus_running:
        subprocess.Popen(["/usr/bin/open", "-a", "/Applications/Pegasus.app"])
    subprocess.Popen(
        ["/usr/bin/osascript", "-e", 'tell application "Pegasus" to activate'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.Popen(
        ["/usr/bin/osascript", "-e", 'tell application "System Events" to set frontmost of first process whose name contains "pegasus" to true'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True

def start_gamepad_hotkey_watcher():
    """Surveille en arrière-plan la combinaison Select + Start sur toutes les manettes SDL2."""
    def _worker():
        import ctypes
        import glob
        sdl_path = "/Users/thomaslefevre/ES-DE/scripts/libSDL2-2.0.0.dylib" if os.path.exists("/Users/thomaslefevre/ES-DE/scripts/libSDL2-2.0.0.dylib") else "/Applications/ES-DE.app/Contents/MacOS/libSDL2-2.0.0.dylib"
        if not os.path.exists(sdl_path):
            print("[gamepad] libSDL2 introuvable, surveillance Select+Start désactivée", flush=True)
            return
        try:
            sdl = ctypes.CDLL(sdl_path)
            sdl.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
            SDL_INIT_JOYSTICK = 0x00000200
            SDL_INIT_GAMECONTROLLER = 0x00002000
            if sdl.SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER) < 0:
                print("[gamepad] Échec SDL_Init", flush=True)
                return

            sdl.SDL_GameControllerAddMapping.argtypes = [ctypes.c_char_p]
            sdl.SDL_GameControllerAddMapping.restype = ctypes.c_int
            sdl.SDL_NumJoysticks.argtypes = []
            sdl.SDL_NumJoysticks.restype = ctypes.c_int
            sdl.SDL_IsGameController.argtypes = [ctypes.c_int]
            sdl.SDL_IsGameController.restype = ctypes.c_int
            sdl.SDL_GameControllerOpen.argtypes = [ctypes.c_int]
            sdl.SDL_GameControllerOpen.restype = ctypes.c_void_p
            sdl.SDL_GameControllerClose.argtypes = [ctypes.c_void_p]
            sdl.SDL_GameControllerClose.restype = None
            sdl.SDL_GameControllerGetAttached.argtypes = [ctypes.c_void_p]
            sdl.SDL_GameControllerGetAttached.restype = ctypes.c_int
            sdl.SDL_GameControllerUpdate.argtypes = []
            sdl.SDL_GameControllerUpdate.restype = None
            sdl.SDL_GameControllerGetButton.argtypes = [ctypes.c_void_p, ctypes.c_int]
            sdl.SDL_GameControllerGetButton.restype = ctypes.c_uint8
            sdl.SDL_JoystickOpen.argtypes = [ctypes.c_int]
            sdl.SDL_JoystickOpen.restype = ctypes.c_void_p
            sdl.SDL_JoystickClose.argtypes = [ctypes.c_void_p]
            sdl.SDL_JoystickClose.restype = None
            sdl.SDL_JoystickGetAttached.argtypes = [ctypes.c_void_p]
            sdl.SDL_JoystickGetAttached.restype = ctypes.c_int
            sdl.SDL_JoystickGetButton.argtypes = [ctypes.c_void_p, ctypes.c_int]
            sdl.SDL_JoystickGetButton.restype = ctypes.c_uint8

            for cfg in glob.glob("/Users/thomaslefevre/ES-DE/controllers/*.cfg"):
                try:
                    with open(cfg, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                sdl.SDL_GameControllerAddMapping(line.encode("utf-8"))
                except OSError:
                    pass

            SDL_CONTROLLER_BUTTON_BACK = 4
            SDL_CONTROLLER_BUTTON_START = 6

            controllers = {}  # index -> (is_gc, handle)
            last_scan = 0.0
            last_trigger = 0.0

            print("[gamepad] Surveillance globale Select + Start activée (retour Pegasus)", flush=True)
            while True:
                now = time.monotonic()
                sdl.SDL_GameControllerUpdate()

                if now - last_scan > 2.0:
                    last_scan = now
                    # Nettoie les manettes débranchées
                    for idx, (is_gc, h) in list(controllers.items()):
                        attached = sdl.SDL_GameControllerGetAttached(h) if is_gc else sdl.SDL_JoystickGetAttached(h)
                        if not attached:
                            if is_gc:
                                sdl.SDL_GameControllerClose(h)
                            else:
                                sdl.SDL_JoystickClose(h)
                            del controllers[idx]
                    # Ouvre les nouvelles manettes détectées
                    num = sdl.SDL_NumJoysticks()
                    for idx in range(num):
                        if idx not in controllers:
                            if sdl.SDL_IsGameController(idx):
                                h = sdl.SDL_GameControllerOpen(idx)
                                if h:
                                    controllers[idx] = (True, h)
                            else:
                                h = sdl.SDL_JoystickOpen(idx)
                                if h:
                                    controllers[idx] = (False, h)

                combo_pressed = False
                for idx, (is_gc, h) in list(controllers.items()):
                    if is_gc:
                        back = sdl.SDL_GameControllerGetButton(h, SDL_CONTROLLER_BUTTON_BACK)
                        start = sdl.SDL_GameControllerGetButton(h, SDL_CONTROLLER_BUTTON_START)
                        if back and start:
                            combo_pressed = True
                            break
                    else:
                        # Fallback boutons bruts 8BitDo (10+11 ou 6+7)
                        b10 = sdl.SDL_JoystickGetButton(h, 10)
                        b11 = sdl.SDL_JoystickGetButton(h, 11)
                        b6 = sdl.SDL_JoystickGetButton(h, 6)
                        b7 = sdl.SDL_JoystickGetButton(h, 7)
                        if (b10 and b11) or (b6 and b7):
                            combo_pressed = True
                            break

                if combo_pressed and (now - last_trigger > 2.0):
                    last_trigger = now
                    threading.Thread(target=quit_active_emulator_to_esde, daemon=True).start()

                time.sleep(0.04)
        except Exception as e:
            print(f"[gamepad] Erreur watcher Select+Start: {e}", flush=True)

    threading.Thread(target=_worker, daemon=True).start()


M4_REPO_DIR = "/Users/thomaslefevre/.t3/projects/m4-gaming"

def get_local_lan_ip():
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.1.152"

def save_and_push_m4_endpoint(tunnel_url):
    if not os.path.isdir(M4_REPO_DIR):
        return
    lan_ip = get_local_lan_ip()
    ep_path = os.path.join(M4_REPO_DIR, "endpoint.json")
    payload = {
        "tunnelUrl": tunnel_url,
        "lanUrl": f"http://{lan_ip}:8765",
        "altLanUrl": f"http://{lan_ip}:8768",
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        with open(ep_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        subprocess.run(["/usr/bin/git", "add", "endpoint.json"], cwd=M4_REPO_DIR, check=True)
        diff = subprocess.run(["/usr/bin/git", "diff", "--cached", "--quiet", "--", "endpoint.json"], cwd=M4_REPO_DIR)
        if diff.returncode != 0:
            subprocess.run(["/usr/bin/git", "commit", "-m", "chore(tunnel): update live M4 Gaming cloudflare tunnel endpoint"], cwd=M4_REPO_DIR, check=True)
            subprocess.run(["/usr/bin/git", "pull", "--rebase", "--autostash", "origin", "main"], cwd=M4_REPO_DIR)
            subprocess.run(["/usr/bin/git", "push", "origin", "main"], cwd=M4_REPO_DIR, check=True)
    except Exception as e:
        print(f"[tunnel] Git sync error: {e}", flush=True)

def start_cloudflare_tunnel():
    import glob, re
    cf_candidates = glob.glob(os.path.expanduser("~/.t3/tools/cloudflared/*/*/cloudflared"))
    if not cf_candidates:
        return
    cf_bin = cf_candidates[0]
    def _runner():
        while True:
            try:
                proc = subprocess.Popen(
                    [cf_bin, "tunnel", "--url", "http://127.0.0.1:8768", "--no-autoupdate"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                for line in proc.stdout:
                    m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                    if m:
                        url = m.group(0)
                        print(f"[tunnel] Active M4 Gaming Tunnel URL: {url}", flush=True)
                        save_and_push_m4_endpoint(url)
                proc.wait()
            except Exception as e:
                print(f"[tunnel] error: {e}", flush=True)
            time.sleep(5)
    threading.Thread(target=_runner, daemon=True).start()

if __name__ == "__main__":
    start_gamepad_hotkey_watcher()
    start_cloudflare_tunnel()
    def _serve_alt():
        try:
            alt = http.server.ThreadingHTTPServer(("0.0.0.0", 8768), GamingHandler)
            alt.serve_forever()
        except Exception:
            pass
    threading.Thread(target=_serve_alt, daemon=True).start()
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), GamingHandler)
    server.serve_forever()
