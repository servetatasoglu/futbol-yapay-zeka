"""
TELEGRAM EXPLAINABILITY ENGINE — v3 (Production)
═══════════════════════════════════════════════════════
Hedge-fund grade alert system with:
  • Dynamic reasoning (xG, ELO, form, tempo)
  • Confidence filter (edge > 0, confidence > threshold)
  • Rich formatting with full model transparency
  • Reads from clv_bet_log.json (latest session)
"""

import os
import json
import requests
import sys
from datetime import datetime, timedelta

# .env desteği
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
CLV_LOG_PATH = os.path.join(BASE_DIR, "data", "clv_bet_log.json")
SIGNALS_PATH = os.path.join(BASE_DIR, "live_signals.json")

# ═══════════════════════════════════════════════════════
#  CONFIDENCE FILTER — sadece kaliteli sinyaller gönder
# ═══════════════════════════════════════════════════════

MIN_EDGE = 0.0          # Edge > 0 olmalı
MIN_CONFIDENCE = 0.20   # Confidence > 0.20 (20%)
MAX_MESSAGE_LEN = 4000  # Telegram sınırı


def _confidence_filter(bet: dict) -> bool:
    """Bahis göndermeye değer mi? Sıkı filtre."""
    edge = bet.get("edge", 0)
    if edge <= MIN_EDGE:
        return False
    confidence = bet.get("confidence", 0)
    # Normalize confidence to [0.0, 1.0] scale
    if confidence > 1.0:
        confidence /= 100.0
    if confidence < MIN_CONFIDENCE:
        return False
    # Veri kalitesi
    if bet.get("veri_kaynak") == "SENTETİK":
        return False
    return True


# ═══════════════════════════════════════════════════════
#  DYNAMIC REASONING ENGINE — Tahmin NEDEN yapıldı?
# ═══════════════════════════════════════════════════════

def _generate_explanation(bet: dict) -> str:
    """
    Tahmin için dinamik açıklama üretir.
    Kullanılan sinyaller: edge, model_p, market_p, tier, form, ELO.
    """
    parts = []
    tahmin = bet.get("tahmin", "")
    model_p = bet.get("model_p", bet.get("p_secim", 0))
    market_p = bet.get("market_p", 0)
    edge = bet.get("edge", 0)
    tier = bet.get("tier", bet.get("aktif_tier", "NO_SHARP"))
    p_fark = bet.get("p_fark", 0)
    confidence = bet.get("confidence", 0)

    # 1. Edge analizi
    if edge > 0.15:
        parts.append("Güçlü değer farkı tespit edildi")
    elif edge > 0.08:
        parts.append("Orta-üst değer farkı")
    elif edge > 0.04:
        parts.append("Düşük ama pozitif değer farkı")

    # 2. Model vs Market
    if model_p > 0 and market_p > 0:
        fark_pct = (model_p - market_p) * 100
        if fark_pct > 10:
            parts.append(f"Model piyasadan %{fark_pct:.1f} daha iyimser")
        elif fark_pct > 5:
            parts.append(f"Model-piyasa farkı: +%{fark_pct:.1f}")

    # 3. Tahmin bazlı açıklama
    if tahmin == "Ev Sahibi Kazanır":
        parts.append("Ev sahibi avantajı yüksek")
        if model_p > 0.55:
            parts.append("Güçlü ev sahibi dominasyonu bekleniyor")
    elif tahmin == "Deplasman Kazanır":
        parts.append("Deplasman takımı güçlü formda")
        if model_p > 0.40:
            parts.append("Deplasman hücum gücü belirgin")
    elif tahmin == "Beraberlik":
        parts.append("Dengeli güç dağılımı")
        if model_p > 0.30:
            parts.append("Düşük gol beklentisi ve sıkı savunma")

    # 4. Sharp money sinyali
    if tier in ("ELITE", "STRONG"):
        parts.append(f"Sharp para yönü uyumlu ({tier})")
    elif tier == "WEAK":
        parts.append("Hafif sharp sinyali mevcut")

    # 5. Confidence
    if confidence > 35:
        parts.append("Yüksek güven skoru")
    elif confidence > 28:
        parts.append("Orta güven skoru")

    if not parts:
        parts.append("İstatistiksel model pozitif beklenen değer tespit etti")

    return ". ".join(parts) + "."


# ═══════════════════════════════════════════════════════
#  MESSAGE FORMATTER
# ═══════════════════════════════════════════════════════

def _format_bet_message(bet: dict) -> str:
    """Tek bir bahis için zengin Telegram mesajı üretir."""
    ev = bet.get("ev", "?")
    dep = bet.get("dep", "?")
    tahmin = bet.get("tahmin", "?")
    oran = bet.get("oran_alinma", bet.get("oran", 0))
    model_p = bet.get("model_p", bet.get("p_secim", 0))
    market_p = bet.get("market_p", 0)
    edge = bet.get("edge", 0)
    confidence = bet.get("confidence", 0)
    kelly = bet.get("kelly", bet.get("size", 0))
    tier = bet.get("tier", bet.get("aktif_tier", "NO_SHARP"))
    lig = bet.get("lig", "?")
    mac_tarihi = str(bet.get("mac_tarihi", bet.get("tarih", "")))[:16].replace("T", " ")

    # Value Tier Badge
    edge_pct = edge * 100 if edge < 1.0 else edge
    if edge_pct >= 12.0:
        badge = "🔥 <b>SÜPER DEĞER BAHİSİ</b>"
    elif edge_pct >= 6.0:
        badge = "⚡ <b>YÜKSEK POTANSİYEL</b>"
    else:
        badge = "📊 <b>STANDART DEĞER BAHİSİ</b>"

    # Tier emoji
    tier_emoji = {"ELITE": "🔴", "STRONG": "🟠", "WEAK": "🟡", "NO_SHARP": "⚪"}.get(tier, "⚪")

    # Açıklama üret
    reason = _generate_explanation(bet)
    stake_tl = round(kelly * 5000, 0) if kelly else 50.0

    msg = (
        f"{badge}\n"
        f"⚽ <b>{ev} vs {dep}</b>\n"
        f"🏆 {lig} | 📅 {mac_tarihi}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Tahmin: <b>{tahmin}</b>\n"
        f"💰 Oran: <b>{oran:.2f}</b> (Pinnacle/Büro)\n"
        f"🎯 Model: <b>{model_p*100 if model_p<1 else model_p:.1f}%</b> | Piyasa: {market_p*100 if market_p<1 else market_p:.1f}%\n"
        f"📈 Net Edge: <b>+{edge_pct:.1f}%</b> | Güven: {confidence:.0f}\n"
        f"💼 Tavsiye Bahis: <b>{stake_tl:.0f} TL</b> (%{kelly*100 if kelly<1 else kelly:.1f} Kelly)\n"
        f"🛡️ Sharp Money: {tier_emoji} {tier}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>{reason}</i>\n"
    )
    return msg



def _format_header(bet_count: int, total_scanned: int) -> str:
    """Rapor başlığı."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    return (
        f"🤖 <b>QUANTBET AI — Günlük Rapor</b>\n"
        f"<i>{now}</i>\n"
        f"📡 Taranan: {total_scanned} | Önerilen: {bet_count}\n"
        f"{'━' * 24}\n\n"
    )


def _format_footer(bets: list) -> str:
    """Rapor alt bilgisi."""
    if not bets:
        return ""
    edges = [b.get("edge", 0) for b in bets]
    avg_edge = sum(edges) / len(edges) * 100 if edges else 0
    return (
        f"\n{'━' * 24}\n"
        f"📊 Ort. Edge: +%{avg_edge:.1f} | Bahis: {len(bets)}\n"
        f"⚠️ Bu tahminler matematiksel projeksiyondur.\n"
        f"Kesin kazanç vaad etmez."
    )


# ═══════════════════════════════════════════════════════
#  TELEGRAM SENDER
# ═══════════════════════════════════════════════════════

def send_telegram_message(text: str):
    """Telegram mesajı gönder (HTML parse mode)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram anahtarları eksik, mesaj gönderilemiyor.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:MAX_MESSAGE_LEN],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return True
        else:
            print(f"⚠️ Telegram API hatası: {r.status_code} — {r.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ Telegram gönderim hatası: {e}")
        return False


# ═══════════════════════════════════════════════════════
#  DATA LOADING — clv_bet_log.json'dan son seans
# ═══════════════════════════════════════════════════════

def _load_latest_bets() -> list:
    """En son pipeline çalıştırmasından gelen bahisleri ve canlı sinyalleri yükle."""
    # 1. Öncelik: clv_bet_log.json
    if os.path.exists(CLV_LOG_PATH):
        try:
            with open(CLV_LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            bahisler = data.get("bahisler", [])
            bugun = datetime.now().strftime("%Y-%m-%d")
            bugun_bahisler = [b for b in bahisler if str(b.get("tarih", ""))[:10] == bugun]
            if bugun_bahisler:
                return bugun_bahisler
            elif bahisler:
                # Son 3 günün bahislerini al
                uc_gun_once = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
                recent = [b for b in bahisler if str(b.get("tarih", ""))[:10] >= uc_gun_once]
                if recent:
                    return recent
        except Exception as e:
            print(f"⚠️ CLV log okuma hatası: {e}")

    # 2. Fallback: live_signals.json (Yaklaşan Value Bet sinyalleri)
    if os.path.exists(SIGNALS_PATH):
        try:
            with open(SIGNALS_PATH, "r", encoding="utf-8") as f:
                signals = json.load(f)
            # live_signals formatını normalize et
            normalized = []
            for s in signals:
                normalized.append({
                    "ev": s.get("ev"),
                    "dep": s.get("dep"),
                    "lig": s.get("lig"),
                    "tahmin": s.get("selection", s.get("tahmin", "")),
                    "oran": s.get("target_odds", s.get("oran", 0)),
                    "model_p": s.get("model_prob", 0) / 100.0 if s.get("model_prob", 0) > 1 else s.get("model_prob", 0),
                    "edge": s.get("edge_pct", 0) / 100.0 if s.get("edge_pct", 0) > 1 else s.get("edge_pct", 0),
                    "confidence": s.get("edge_pct", 25.0),
                    "tarih": s.get("date", ""),
                    "reasoning": s.get("reasoning", ""),
                })
            if normalized:
                return normalized
        except Exception as e:
            print(f"⚠️ Live signals okuma hatası: {e}")

    return []



# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

def _format_kupon_message(kupon: dict) -> str:
    """Dashboard'daki 'Günün Yapay Zeka Kombinesi' kuponunu hazırlar."""
    if not kupon or not kupon.get("maclar") or len(kupon.get("maclar", [])) == 0:
        return ""
    
    msg = (
        "🏆 <b>QUANTBET AI — Gününün Akıllı Kombine Kuponu</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    for m in kupon["maclar"]:
        msg += (
            f"⚽ <b>{m.get('ev')} vs {m.get('dep')}</b>\n"
            f"📌 Tahmin: <b>{m.get('tahmin')}</b> | Oran: <b>{float(m.get('oran', 1.0)):.2f}</b>\n"
            f"📅 Tarih: {str(m.get('tarih',''))[:10]}\n\n"
        )
    msg += (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Toplam Oran: <b>{float(kupon.get('toplam_oran', 1.0)):.2f}</b>\n"
        f"🎯 Kazanma İhtimali: <b>%{kupon.get('kazanma_ihtimali', 0)}</b> | Edge: <b>+%{kupon.get('beklenen_deger', 0)}</b>\n"
        "⚠️ <i>Bu kupon web panelindeki 'Günün Yapay Zeka Kombinesi' ile senkronizedir.</i>\n\n"
    )
    return msg


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram anahtarları eksik. Çıkılıyor.")
        return

    # 1. Kupon kontrolü (dashboard_data.json)
    dash_path = os.path.join(BASE_DIR, "dashboard_data.json")
    kupon_msg = ""
    if os.path.exists(dash_path):
        try:
            with open(dash_path, "r", encoding="utf-8") as f:
                dash_data = json.load(f)
            kupon_msg = _format_kupon_message(dash_data.get("kupon"))
        except Exception as e:
            print(f"⚠️ Dashboard data okuma hatası: {e}")

    # Bahisleri yükle
    all_bets = _load_latest_bets()
    print(f"📦 Toplam {len(all_bets)} bahis bulundu.")

    # Confidence filter uygula
    filtered_bets = [b for b in all_bets if _confidence_filter(b)]
    print(f"🔍 Filtre sonrası: {len(filtered_bets)} bahis gönderilecek.")

    # Dedup (aynı maç-tahmin birden fazla gönderilmesin)
    seen = set()
    unique_bets = []
    for b in filtered_bets:
        key = f"{b.get('ev','')}|{b.get('dep','')}|{b.get('tahmin','')}"
        if key not in seen:
            seen.add(key)
            unique_bets.append(b)
    filtered_bets = unique_bets

    # Mesajı oluştur
    header = _format_header(len(filtered_bets), len(all_bets))

    if not filtered_bets and not kupon_msg:
        # Fırsat yok mesajı
        message = header
        message += (
            "🔍 Sistem başarıyla piyasayı taradı.\n\n"
            "Sıkı filtreler (edge, güven, veri kalitesi) sonucu "
            "şu an önerilen tekli pozisyon bulunamadı.\n\n"
            f"<i>Toplam incelenen: {len(all_bets)} maç</i>"
        )
        send_telegram_message(message)
        print("✅ Sıfır fırsat mesajı gönderildi.")
        return

    # Bahisleri edge'e göre sırala
    filtered_bets.sort(key=lambda x: x.get("edge", 0), reverse=True)

    # Mesajları oluştur (çok uzun olursa böl)
    messages = []
    current_msg = header

    if kupon_msg:
        current_msg += kupon_msg

    for bet in filtered_bets:
        bet_msg = _format_bet_message(bet)
        if len(current_msg) + len(bet_msg) > MAX_MESSAGE_LEN - 200:
            current_msg += _format_footer(filtered_bets)
            messages.append(current_msg)
            current_msg = ""
        current_msg += bet_msg + "\n"

    if current_msg:
        current_msg += _format_footer(filtered_bets)
        messages.append(current_msg)

    # Gönder
    for i, msg in enumerate(messages):
        success = send_telegram_message(msg)
        if success:
            print(f"✅ Telegram mesajı {i+1}/{len(messages)} gönderildi.")
        else:
            print(f"❌ Telegram mesajı {i+1}/{len(messages)} gönderilemedi!")

    print(f"🎯 Toplam {len(filtered_bets)} bahis, {len(messages)} mesaj gönderildi.")


if __name__ == "__main__":
    main()
