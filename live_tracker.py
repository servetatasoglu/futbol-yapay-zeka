#!/usr/bin/env python3
# live_tracker.py
"""
Canlı Paper Trading Takip Sistemi
══════════════════════════════════════════════════════════════
Kullanım:
  python3 live_tracker.py           → Durumu göster
  python3 live_tracker.py --refresh → Sonuçları güncelle + göster
  python3 live_tracker.py --panel   → Tarayıcı panelini güncelle + aç

Çalışma mantığı:
  1. data/paper_trades.json'daki açık bahisleri kontrol eder
  2. result_updater üzerinden API'den maç sonuçlarını çeker
  3. P&L, ROI, CLV, Sharpe'ı hesaplar
  4. live_tracking_panel.html'yi günceller
"""

import os
import json
import sys
import math
import subprocess
from datetime import datetime, timezone

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
TRADES_PATH  = os.path.join(BASE_DIR, "data", "paper_trades.json")
SUMMARY_PATH = os.path.join(BASE_DIR, "data", "paper_summary.json")
PANEL_PATH   = os.path.join(BASE_DIR, "live_tracking_panel.html")

PAPER_BASLANGIC = 10_000.0   # sanal TL


# ═══════════════════════════════════════════════════════
#  Veri Yükleme
# ═══════════════════════════════════════════════════════

def trades_yukle() -> list:
    if not os.path.exists(TRADES_PATH):
        return []
    try:
        with open(TRADES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def summary_yukle() -> dict:
    if not os.path.exists(SUMMARY_PATH):
        return {"baslangic_banka": PAPER_BASLANGIC, "mevcut_banka": PAPER_BASLANGIC}
    try:
        with open(SUMMARY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"baslangic_banka": PAPER_BASLANGIC, "mevcut_banka": PAPER_BASLANGIC}


# ═══════════════════════════════════════════════════════
#  Metrikleri Hesapla
# ═══════════════════════════════════════════════════════

def metrikleri_hesapla(trades: list) -> dict:
    sonuclananlar = [t for t in trades if t.get("durum") in ("kazandi", "kaybetti")]
    bekleyenler   = [t for t in trades if t.get("durum") == "bekliyor"]
    toplam        = len(trades)

    if not sonuclananlar:
        return {
            "toplam": toplam,
            "sonuclanan": 0,
            "bekleyen": len(bekleyenler),
            "kazanan": 0,
            "kaybeden": 0,
            "win_rate": 0.0,
            "toplam_staked": 0.0,
            "toplam_pnl": 0.0,
            "yield_pct": 0.0,
            "bankroll_return": 0.0,
            "sharpe": 0.0,
            "ort_clv": 0.0,
            "ort_edge": 0.0,
            "max_drawdown": 0.0,
            "trades": trades,
            "bekleyenler": bekleyenler,
        }

    kazananlar    = [t for t in sonuclananlar if t.get("durum") == "kazandi"]
    kaybettenler  = [t for t in sonuclananlar if t.get("durum") == "kaybetti"]

    toplam_staked = sum(t.get("bahis_miktar", 0) for t in sonuclananlar)
    toplam_pnl    = sum(t.get("kar_zarar", 0)    for t in sonuclananlar)
    yield_pct     = (toplam_pnl / toplam_staked * 100) if toplam_staked > 0 else 0.0
    bankroll_ret  = (toplam_pnl / PAPER_BASLANGIC * 100)

    # Sharpe (günlük P&L üzerinden)
    pnllar = [t.get("kar_zarar", 0) for t in sonuclananlar]
    ort    = sum(pnllar) / len(pnllar)
    std    = math.sqrt(sum((x - ort)**2 for x in pnllar) / len(pnllar)) if len(pnllar) > 1 else 1e-9
    sharpe = (ort / std) * math.sqrt(252) if std > 0 else 0.0

    # CLV (kapanış oranı girilen bahisler)
    clv_trades = [t for t in sonuclananlar if t.get("kapanisoran", 0) > 1.0]
    ort_clv = 0.0
    if clv_trades:
        clvler = [(t["oran"] / t["kapanisoran"] - 1) * 100 for t in clv_trades]
        ort_clv = sum(clvler) / len(clvler)

    ort_edge = sum(t.get("edge", 0) for t in sonuclananlar) / len(sonuclananlar) * 100

    # Max drawdown
    banka = PAPER_BASLANGIC
    peak  = banka
    max_dd = 0.0
    for t in sorted(sonuclananlar, key=lambda x: x.get("kayit_tarihi", "")):
        banka += t.get("kar_zarar", 0)
        if banka > peak:
            peak = banka
        dd = (peak - banka) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return {
        "toplam":          toplam,
        "sonuclanan":      len(sonuclananlar),
        "bekleyen":        len(bekleyenler),
        "kazanan":         len(kazananlar),
        "kaybeden":        len(kaybettenler),
        "win_rate":        len(kazananlar) / len(sonuclananlar) * 100,
        "toplam_staked":   toplam_staked,
        "toplam_pnl":      toplam_pnl,
        "yield_pct":       yield_pct,
        "bankroll_return": bankroll_ret,
        "sharpe":          sharpe,
        "ort_clv":         ort_clv,
        "ort_edge":        ort_edge,
        "max_drawdown":    max_dd,
        "trades":          trades,
        "bekleyenler":     bekleyenler,
    }


# ═══════════════════════════════════════════════════════
#  Terminal Çıktısı
# ═══════════════════════════════════════════════════════

def terminal_yazdir(m: dict):
    print("\n" + "═" * 62)
    print("  ⚽ CANLI PAPER TRADING TAKİP")
    print("  Tarih:", datetime.now().strftime("%d.%m.%Y %H:%M"))
    print("═" * 62)

    def sign(v): return "+" if v >= 0 else ""
    def color(v, good_positive=True):
        if v > 0:   return "✅" if good_positive else "⚠️"
        elif v < 0: return "❌" if good_positive else "✅"
        return "➖"

    print(f"\n  📊 ÖZET")
    print(f"  Toplam Bahis     : {m['toplam']}")
    print(f"  Sonuçlanan       : {m['sonuclanan']}  (Kazanan: {m['kazanan']}  Kaybeden: {m['kaybeden']})")
    print(f"  Bekleyen         : {m['bekleyen']}")

    if m['sonuclanan'] > 0:
        print(f"\n  💰 FİNANSAL")
        print(f"  Win Rate         : %{m['win_rate']:.1f}")
        print(f"  Toplam Staked    : {m['toplam_staked']:.0f} TL (sanal)")
        pnl_str = f"{sign(m['toplam_pnl'])}{m['toplam_pnl']:.1f} TL"
        print(f"  Toplam P&L       : {pnl_str}  {color(m['toplam_pnl'])}")
        y = m['yield_pct']
        print(f"  Yield (ROI)      : {sign(y)}{y:.2f}%  {color(y)}")
        br = m['bankroll_return']
        print(f"  Bankroll Return  : {sign(br)}{br:.2f}%  {color(br)}")
        sh = m['sharpe']
        print(f"  Sharpe Ratio     : {sign(sh)}{sh:.2f}  {color(sh)}")
        clv = m['ort_clv']
        print(f"  Ort. CLV         : {sign(clv)}{clv:.2f}%  {color(clv)}")
        print(f"  Max Drawdown     : -%{m['max_drawdown']:.1f}")

        # Gate değerlendirmesi
        print(f"\n  🚪 EXECUTION GATE DEĞERLENDİRMESİ")
        if m['yield_pct'] > 0 and m['ort_clv'] > 0 and m['sharpe'] > 0:
            print("  ✅ TÜM GATE'LER POZİTİF — Sistem alpha üretiyor!")
            print("     Daha fazla veri biriktikten sonra gerçek para")
            print("     ile geçiş değerlendirilebilir (min 200 bahis).")
        elif m['sonuclanan'] < 30:
            print(f"  ⏳ Henüz {m['sonuclanan']}/200 bahis tamamlandı — İstatistiksel")
            print("     anlamlılık için en az 200 bahis gereklidir.")
        else:
            print("  ❌ Gate(ler) hâlâ negatif — Gerçek para kullanmayın.")

    if m['bekleyen'] > 0:
        print(f"\n  ⏳ BEKLEYEN BAHİSLER ({m['bekleyen']} adet)")
        print(f"  {'ID':>4}  {'Maç':<32}  {'Tahmin':<18}  {'Oran':>5}  {'Tarih':<12}")
        print("  " + "-" * 75)
        for t in m['bekleyenler'][:10]:
            mac  = f"{t.get('ev','?')} - {t.get('dep','?')}"[:32]
            tah  = t.get('tahmin', '?')[:18]
            print(f"  {t.get('id','-'):>4}  {mac:<32}  {tah:<18}  "
                  f"{t.get('oran',0):>5.2f}  {t.get('mac_tarihi','?')[:10]:<12}")

    print("\n" + "═" * 62)


# ═══════════════════════════════════════════════════════
#  HTML Panel Üret
# ═══════════════════════════════════════════════════════

def html_panel_uret(m: dict):
    """Canlı takip panelini HTML olarak üretir."""

    def sign(v): return "+" if v >= 0 else ""
    def cls(v):  return "positive" if v > 0 else ("negative" if v < 0 else "neutral")

    # Bahis satırları
    def satir_html(trade_list, tip="sonuclu"):
        rows = ""
        for t in reversed(trade_list[-50:]):
            durum = t.get("durum", "bekliyor")
            if durum == "kazandi":
                durum_html = '<span class="pill pill-green">✅ Kazandı</span>'
            elif durum == "kaybetti":
                durum_html = '<span class="pill pill-red">❌ Kaybetti</span>'
            else:
                durum_html = '<span class="pill pill-yellow">⏳ Bekliyor</span>'

            pnl = t.get("kar_zarar", 0)
            pnl_html = f'<span class="{cls(pnl)}">{sign(pnl)}{pnl:.1f} TL</span>' if pnl != 0 else "<span class='muted'>—</span>"
            clv_val  = ((t.get("oran",1) / t.get("kapanisoran",1)) - 1)*100 if t.get("kapanisoran",0)>1 else 0
            clv_html = f'<span class="{cls(clv_val)}">{sign(clv_val)}{clv_val:.1f}%</span>' if clv_val != 0 else "<span class='muted'>—</span>"

            rows += f"""
            <tr>
              <td class="mono muted">#{t.get('id','?')}</td>
              <td>{t.get('ev','?')} <span class="muted">vs</span> {t.get('dep','?')}</td>
              <td><span class="lig-badge">{t.get('lig','?')}</span></td>
              <td class="mono">{t.get('tahmin','?')}</td>
              <td class="mono">{t.get('oran',0):.2f}</td>
              <td class="mono">{t.get('edge',0)*100:.1f}%</td>
              <td>{pnl_html}</td>
              <td>{clv_html}</td>
              <td class="mono muted">{t.get('mac_tarihi','?')[:10]}</td>
              <td>{durum_html}</td>
            </tr>"""
        return rows or '<tr><td colspan="10" class="empty">Henüz bahis yok</td></tr>'

    # Gate durumu
    if m['sonuclanan'] < 30:
        gate_color = "#f59e0b"
        gate_icon  = "⏳"
        gate_text  = f"İstatistiksel anlam için {m['sonuclanan']}/200 bahis tamamlandı"
    elif m['yield_pct'] > 0 and m['ort_clv'] > 0 and m['sharpe'] > 0:
        gate_color = "#10b981"
        gate_icon  = "✅"
        gate_text  = "Tüm gate'ler pozitif — sistem alpha üretiyor!"
    else:
        gate_color = "#ef4444"
        gate_icon  = "❌"
        gate_text  = "Gate(ler) hâlâ negatif — gerçek para kullanmayın"

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    n   = m['sonuclanan']

    all_trades = m.get("trades", [])
    son_satirlar = satir_html(all_trades)

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <meta http-equiv="refresh" content="300"/>
  <title>Canlı Paper Trading — Futbol Yapay Zeka</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/>
  <style>
    :root{{
      --bg:#0a0d14;--surface:#111827;--card:#161d2e;--border:#1e2d45;
      --accent:#3b82f6;--green:#10b981;--red:#ef4444;--yellow:#f59e0b;
      --text:#e2e8f0;--muted:#64748b;--mono:'JetBrains Mono',monospace;
    }}
    *{{margin:0;padding:0;box-sizing:border-box;}}
    body{{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;min-height:100vh;}}
    header{{
      background:linear-gradient(135deg,#0f172a 0%,#1e1b4b 50%,#0f172a 100%);
      border-bottom:1px solid var(--border);padding:22px 44px;
      display:flex;align-items:center;justify-content:space-between;
      position:sticky;top:0;z-index:100;
    }}
    .logo{{display:flex;align-items:center;gap:14px;}}
    .logo-icon{{width:40px;height:40px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);
      border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px;}}
    .logo h1{{font-size:17px;font-weight:700;color:#e2e8f0;}}
    .logo p{{font-size:11px;color:var(--muted);}}
    .badge{{padding:5px 13px;border-radius:20px;font-size:11px;font-weight:600;
      display:flex;align-items:center;gap:6px;}}
    .badge-live{{background:rgba(16,185,129,.12);color:#10b981;border:1px solid rgba(16,185,129,.25);}}
    .dot{{width:7px;height:7px;border-radius:50%;background:#10b981;
      box-shadow:0 0 6px #10b981;animation:pulse 2s infinite;}}
    @keyframes pulse{{0%,100%{{opacity:1;}}50%{{opacity:.35;}}}}
    main{{padding:36px 44px;max-width:1440px;margin:0 auto;}}

    /* Gate Banner */
    .gate-banner{{
      background:rgba(0,0,0,.2);
      border:1px solid {gate_color}44;
      border-left:4px solid {gate_color};
      border-radius:12px;padding:18px 24px;margin-bottom:32px;
      display:flex;align-items:center;gap:14px;
    }}
    .gate-icon{{font-size:26px;}}
    .gate-text h3{{font-size:14px;font-weight:700;color:{gate_color};margin-bottom:3px;}}
    .gate-text p{{font-size:12px;color:#94a3b8;}}

    /* KPI */
    .kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px;}}
    @media(max-width:1000px){{.kpi-grid{{grid-template-columns:repeat(2,1fr);}}}}
    .kpi{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px;
      transition:transform .2s,border-color .2s;}}
    .kpi:hover{{transform:translateY(-2px);border-color:rgba(59,130,246,.35);}}
    .kpi-label{{font-size:10px;font-weight:600;letter-spacing:.08em;
      text-transform:uppercase;color:var(--muted);margin-bottom:8px;}}
    .kpi-val{{font-size:30px;font-weight:800;font-family:var(--mono);line-height:1;margin-bottom:6px;}}
    .kpi-sub{{font-size:11px;color:var(--muted);}}
    .positive{{color:#10b981;}} .negative{{color:#ef4444;}} .neutral{{color:#60a5fa;}} .muted{{color:#64748b;}}

    /* Progress bar */
    .progress-bar-bg{{height:4px;background:rgba(255,255,255,.05);border-radius:2px;margin-top:10px;overflow:hidden;}}
    .progress-bar{{height:100%;background:linear-gradient(90deg,#3b82f6,#8b5cf6);border-radius:2px;transition:width .8s ease;}}

    /* Trades table */
    .card{{background:var(--card);border:1px solid var(--border);border-radius:14px;
      padding:22px;margin-bottom:24px;}}
    .card-title{{font-size:13px;font-weight:700;color:#cbd5e1;margin-bottom:18px;
      display:flex;align-items:center;gap:8px;}}
    table{{width:100%;border-collapse:collapse;font-size:12px;}}
    th{{text-align:left;padding:8px 10px;font-size:10px;font-weight:600;
      letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
      border-bottom:1px solid var(--border);}}
    td{{padding:10px 10px;border-bottom:1px solid rgba(255,255,255,.03);}}
    tr:last-child td{{border-bottom:none;}}
    tr:hover td{{background:rgba(255,255,255,.02);}}
    .mono{{font-family:var(--mono);}}
    .pill{{font-size:11px;font-weight:600;padding:3px 9px;border-radius:12px;white-space:nowrap;}}
    .pill-green{{background:rgba(16,185,129,.1);color:#10b981;border:1px solid rgba(16,185,129,.2);}}
    .pill-red{{background:rgba(239,68,68,.1);color:#ef4444;border:1px solid rgba(239,68,68,.2);}}
    .pill-yellow{{background:rgba(245,158,11,.1);color:#f59e0b;border:1px solid rgba(245,158,11,.2);}}
    .lig-badge{{font-size:10px;font-weight:600;padding:2px 7px;border-radius:5px;
      background:rgba(59,130,246,.1);color:#60a5fa;border:1px solid rgba(59,130,246,.15);font-family:var(--mono);}}
    .empty{{text-align:center;padding:32px;color:var(--muted);}}

    /* 2-col */
    .two-col{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px;}}
    @media(max-width:800px){{.two-col{{grid-template-columns:1fr;}}}}

    /* Stats list */
    .stat-row{{display:flex;justify-content:space-between;align-items:center;
      padding:10px 0;border-bottom:1px solid rgba(255,255,255,.04);}}
    .stat-row:last-child{{border-bottom:none;}}
    .stat-label{{font-size:12px;color:#94a3b8;}}
    .stat-val{{font-family:var(--mono);font-size:13px;font-weight:600;}}

    footer{{border-top:1px solid var(--border);padding:20px 44px;
      display:flex;justify-content:space-between;font-size:11px;color:var(--muted);}}
  </style>
</head>
<body>
<header>
  <div class="logo">
    <div class="logo-icon">⚽</div>
    <div>
      <h1>Canlı Paper Trading Takibi</h1>
      <p>Futbol Yapay Zeka · Son güncelleme: {now}</p>
    </div>
  </div>
  <div style="display:flex;gap:10px">
    <div class="badge badge-live"><div class="dot"></div>Paper Mode</div>
    <div class="badge" style="background:rgba(59,130,246,.1);color:#60a5fa;border:1px solid rgba(59,130,246,.25);">
      Sanal Bankroll: {10000 + m.get('toplam_pnl',0):,.0f} TL
    </div>
  </div>
</header>

<main>

  <!-- Gate Banner -->
  <div class="gate-banner">
    <div class="gate-icon">{gate_icon}</div>
    <div class="gate-text">
      <h3>Execution Gate Durumu</h3>
      <p>{gate_text}</p>
    </div>
  </div>

  <!-- KPI -->
  <div class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">Yield / ROI</div>
      <div class="kpi-val {cls(m['yield_pct'])}">{sign(m['yield_pct'])}{m['yield_pct']:.2f}%</div>
      <div class="kpi-sub">total_pnl / total_staked</div>
      <div class="progress-bar-bg"><div class="progress-bar" style="width:{min(100, max(0, m['win_rate']))}%"></div></div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Ort. CLV</div>
      <div class="kpi-val {cls(m['ort_clv'])}">{sign(m['ort_clv'])}{m['ort_clv']:.2f}%</div>
      <div class="kpi-sub">Closing Line Value</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Sharpe Ratio</div>
      <div class="kpi-val {cls(m['sharpe'])}">{sign(m['sharpe'])}{m['sharpe']:.2f}</div>
      <div class="kpi-sub">Risk-adjusted return</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Toplam P&amp;L</div>
      <div class="kpi-val {cls(m['toplam_pnl'])}">{sign(m['toplam_pnl'])}{m['toplam_pnl']:.0f} TL</div>
      <div class="kpi-sub">Sanal para (kâğıt)</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Win Rate</div>
      <div class="kpi-val neutral">{m['win_rate']:.1f}%</div>
      <div class="kpi-sub">{m['kazanan']} / {m['sonuclanan']} maç</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Sonuçlanan</div>
      <div class="kpi-val neutral">{m['sonuclanan']}</div>
      <div class="kpi-sub">Min 200 gerekli</div>
      <div class="progress-bar-bg"><div class="progress-bar" style="width:{min(100, m['sonuclanan']/200*100):.0f}%"></div></div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Bekleyen</div>
      <div class="kpi-val" style="color:#f59e0b">{m['bekleyen']}</div>
      <div class="kpi-sub">Sonuç bekleniyor</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Max Drawdown</div>
      <div class="kpi-val negative">-{m['max_drawdown']:.1f}%</div>
      <div class="kpi-sub">Peak-to-trough</div>
    </div>
  </div>

  <!-- Detay istatistikler -->
  <div class="two-col">
    <div class="card">
      <div class="card-title">📊 Detay İstatistikler</div>
      <div class="stat-row">
        <span class="stat-label">Toplam Staked</span>
        <span class="stat-val neutral">{m['toplam_staked']:.0f} TL</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Bankroll Return</span>
        <span class="stat-val {cls(m['bankroll_return'])}">{sign(m['bankroll_return'])}{m['bankroll_return']:.2f}%</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Ort. Edge</span>
        <span class="stat-val {cls(m['ort_edge'])}">{sign(m['ort_edge'])}{m['ort_edge']:.2f}%</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">İstatistiksel Yeterlilik</span>
        <span class="stat-val {'positive' if m['sonuclanan']>=200 else 'negative'}">{m['sonuclanan']}/200 bahis</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title">🚪 Execution Gate Kriterleri</div>
      <div class="stat-row">
        <span class="stat-label">Yield ≥ 0% (hedef: +2%)</span>
        <span class="stat-val {cls(m['yield_pct'])}">{sign(m['yield_pct'])}{m['yield_pct']:.2f}%</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">CLV ≥ 0%</span>
        <span class="stat-val {cls(m['ort_clv'])}">{sign(m['ort_clv'])}{m['ort_clv']:.2f}%</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Sharpe ≥ 0</span>
        <span class="stat-val {cls(m['sharpe'])}">{sign(m['sharpe'])}{m['sharpe']:.2f}</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Min Bahis Sayısı</span>
        <span class="stat-val {'positive' if m['sonuclanan']>=200 else 'negative'}">{m['sonuclanan']} / 200</span>
      </div>
    </div>
  </div>

  <!-- Tüm Bahisler -->
  <div class="card">
    <div class="card-title">📋 Tüm Bahisler (Son 50)</div>
    <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th>#</th><th>Maç</th><th>Lig</th><th>Tahmin</th>
            <th>Oran</th><th>Edge</th><th>P&amp;L</th><th>CLV</th><th>Tarih</th><th>Durum</th>
          </tr>
        </thead>
        <tbody>
          {son_satirlar}
        </tbody>
      </table>
    </div>
  </div>

</main>

<footer>
  <div>⚽ Paper Trading Panel · Sanal Para · Gerçek Para DEĞİL</div>
  <div>Son güncelleme: {now} · 5 dakikada bir otomatik yenilenir</div>
  <div>📄 <a href="audit_panel.html" style="color:#60a5fa">Audit Paneli</a></div>
</footer>
</body>
</html>"""

    with open(PANEL_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ Panel güncellendi → {PANEL_PATH}")


# ═══════════════════════════════════════════════════════
#  Ana Giriş
# ═══════════════════════════════════════════════════════

def main():
    args = set(sys.argv[1:])

    # Sonuçları güncelle
    if "--refresh" in args or "--panel" in args:
        print("🔄 API'den maç sonuçları çekiliyor...")
        try:
            from execution.result_updater import sonuclari_guncelle
            guncellenen = sonuclari_guncelle()
            print(f"  ✅ {guncellenen} maç sonucu güncellendi")
        except Exception as e:
            print(f"  ⚠️  Otomatik güncelleme başarısız: {e}")
            print("     Sonuçları manuel girmek için: execution/paper_trading.py")

    trades = trades_yukle()
    m      = metrikleri_hesapla(trades)

    terminal_yazdir(m)
    html_panel_uret(m)

    if "--panel" in args or "--open" in args:
        print(f"\n🌐 Panel açılıyor: {PANEL_PATH}")
        subprocess.Popen(["open", PANEL_PATH])

    if not trades:
        print("\n  ℹ️  Henüz kayıtlı paper trade yok.")
        print("     Sistem ana döngüsünü çalıştırdıktan sonra")
        print("     bahisler otomatik olarak data/paper_trades.json'a kaydedilir.")
        print("\n  Örnek manuel bahis eklemek için:")
        print("     from execution.paper_trading import paper_bahis_kaydet")
        print("     paper_bahis_kaydet('Arsenal', 'Chelsea', 'PL', 'Ev Sahibi Kazanır',")
        print("                        oran=2.10, edge=0.04, olasilik=0.52, mac_tarihi='2026-10-12')")


if __name__ == "__main__":
    main()
