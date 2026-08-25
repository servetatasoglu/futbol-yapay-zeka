# analysis/db_logger.py
"""
SQLite Veritabanı Entegrasyonu (ACID Compliance)
══════════════════════════════════════════════════════
Gerçek para bahislerinde dosya kilitlenmelerini (lock) 
ve çökme durumunda veri kayıplarını engellemek için tasarlandı.
Mevcut CSV sistemiyle beraber Dual-Write (çift yazma) yapar.
"""

import sqlite3
import os
import threading

# SQLite erişimi için Singleton & Lock mekanizması
_DB_LOCK = threading.Lock()
DB_FILE = os.path.join("logs", "claod_futbol.sqlite")

def _veritabanini_baslat():
    """Tablolar yoksa oluşturur."""
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with _DB_LOCK:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Tahminler Tablosu
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tahminler_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                Tarih TEXT, Ev TEXT, Dep TEXT, Lig TEXT, Tahmin TEXT, 
                Oran REAL, Olasilik REAL, Edge REAL, EfektifEdge REAL, 
                FairP REAL, PiyasaSapma REAL, PiyasaUyum REAL, 
                OverRound REAL, SharpPiyasa INTEGER, EvELO REAL, DepELO REAL,
                Konsensus REAL, MC_Analitik REAL, LamEv REAL, LamDep REAL,
                Over15_P REAL, Over25_P REAL, Over35_P REAL, BTS_P REAL,
                EvForm REAL, DepForm REAL, EvMomentum REAL, DepMomentum REAL,
                EvSeri TEXT, DepSeri TEXT, H2HGuven REAL, H2HMac INTEGER,
                AgirlikELO REAL, AgirlikPoisson REAL, AgirlikForm REAL,
                MacTarihi TEXT, SharpSinyal TEXT, HareketGucu REAL, 
                EvHareket REAL, DepHareket REAL, IlkEvOran REAL, 
                IlkDepOran REAL, KitapSayisi INTEGER, PinnacleVar INTEGER,
                FiltreAciklamasi TEXT, GercekSonuc TEXT,
                UNIQUE(Ev, Dep, MacTarihi, Tahmin)
            )
        ''')
        
        # Kuponlar Tablosu
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kupon_log (
                KuponID TEXT PRIMARY KEY,
                Tarih TEXT, Tur TEXT, ToplamOran REAL, BirlesikP REAL, Edge REAL,
                Mac1Ev TEXT, Mac1Dep TEXT, Mac1Tahmin TEXT, Mac1Oran REAL, Mac1Sonuc TEXT,
                Mac2Ev TEXT, Mac2Dep TEXT, Mac2Tahmin TEXT, Mac2Oran REAL, Mac2Sonuc TEXT,
                Mac3Ev TEXT, Mac3Dep TEXT, Mac3Tahmin TEXT, Mac3Oran REAL, Mac3Sonuc TEXT,
                KuponSonuc TEXT, KazanilanKat REAL
            )
        ''')
        
        conn.commit()
        conn.close()

# Modül yüklendiğinde tabloları otomatik kontrol et
_veritabanini_baslat()

def sqlite_tahmin_kaydet(bet_dict: dict, simdi: str):
    """Tek bir tahmin satırını SQLite veritabanına kaydeder/günceller."""
    with _DB_LOCK:
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            mac_tar_k = str(bet_dict.get("mac_tarihi", ""))[:10]
            
            cursor.execute('''
                INSERT OR IGNORE INTO tahminler_log (
                    Tarih, Ev, Dep, Lig, Tahmin, Oran, Olasilik, Edge, EfektifEdge,
                    FairP, PiyasaSapma, PiyasaUyum, OverRound, SharpPiyasa, 
                    EvELO, DepELO, Konsensus, MC_Analitik, LamEv, LamDep,
                    Over15_P, Over25_P, Over35_P, BTS_P, EvForm, DepForm, 
                    EvMomentum, DepMomentum, EvSeri, DepSeri, H2HGuven, H2HMac,
                    AgirlikELO, AgirlikPoisson, AgirlikForm, MacTarihi,
                    SharpSinyal, HareketGucu, EvHareket, DepHareket,
                    IlkEvOran, IlkDepOran, KitapSayisi, PinnacleVar, FiltreAciklamasi
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                simdi,
                bet_dict.get("ev"), bet_dict.get("dep"), bet_dict.get("lig"), bet_dict.get("tahmin"),
                bet_dict.get("oran"), bet_dict.get("olasilik"), bet_dict.get("edge"), bet_dict.get("efektif_edge"),
                bet_dict.get("fair_p", 0), bet_dict.get("piyasa_sapma", 0), bet_dict.get("piyasa_uyum", 0),
                bet_dict.get("over_round", 0), 1 if bet_dict.get("sharp_piyasa") else 0,
                bet_dict.get("ev_elo", 0), bet_dict.get("dep_elo", 0),
                bet_dict.get("konsensus", 0), bet_dict.get("mc_analitik_uyum", 0),
                bet_dict.get("lam_ev", 0), bet_dict.get("lam_dep", 0),
                bet_dict.get("over15_p", 0), bet_dict.get("over25_p", 0), bet_dict.get("over35_p", 0), bet_dict.get("bts_p", 0),
                bet_dict.get("ev_form_skor", 0.5), bet_dict.get("dep_form_skor", 0.5),
                bet_dict.get("ev_momentum", 0.0), bet_dict.get("dep_momentum", 0.0),
                bet_dict.get("ev_seri", "?"), bet_dict.get("dep_seri", "?"),
                bet_dict.get("h2h_guven", 0), bet_dict.get("h2h_mac", 0),
                bet_dict.get("agirlik_elo", 0), bet_dict.get("agirlik_poisson", 0), bet_dict.get("agirlik_form", 0),
                mac_tar_k,
                bet_dict.get("sharp_sinyal", "YOK"), bet_dict.get("hareket_gucu", 0.0),
                bet_dict.get("ev_hareket", 0.0), bet_dict.get("dep_hareket", 0.0),
                bet_dict.get("ilk_ev_oran", 0.0), bet_dict.get("ilk_dep_oran", 0.0),
                bet_dict.get("kitap_sayisi", 1), 1 if bet_dict.get("pinnacle_var", False) else 0,
                bet_dict.get("filtre_sebep", bet_dict.get("filtre_acik", ""))
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"  ⚠️  SQLite tahmin kayıt hatası: {e}")

def sqlite_kupon_kaydet(satir_listesi: list):
    """Kupon_log.csv'ye yazılan veriyi SQLite'a yazar."""
    with _DB_LOCK:
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            for s in satir_listesi:
                # HEADER sirasi varsayilir: Tarih, KuponID, Tur, ToplamOran...
                cursor.execute('''
                    INSERT OR IGNORE INTO kupon_log (
                        Tarih, KuponID, Tur, ToplamOran, BirlesikP, Edge,
                        Mac1Ev, Mac1Dep, Mac1Tahmin, Mac1Oran, Mac1Sonuc,
                        Mac2Ev, Mac2Dep, Mac2Tahmin, Mac2Oran, Mac2Sonuc,
                        Mac3Ev, Mac3Dep, Mac3Tahmin, Mac3Oran, Mac3Sonuc,
                        KuponSonuc, KazanilanKat
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    s[0], s[1], s[2], s[3], s[4], s[5],
                    s[6], s[7], s[8], s[9], s[10],
                    s[11], s[12], s[13], s[14], s[15],
                    s[16], s[17], s[18], s[19], s[20],
                    s[21], s[22]
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"  ⚠️  SQLite kupon kayıt hatası: {e}")
