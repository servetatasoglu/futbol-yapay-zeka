# scrapers/proxy_manager.py
"""
Ücretsiz Proxy Rotatörü
══════════════════════════════════════════════════════════════
VPN kullanılmadığında, engellenmiş domainlere (Transfermarkt, vs.)
erişmek için Github repo ve free-proxy-list sitelerindeki güncel
proxyleri çekip kullanılabilir olanı bulur ve ona üzerinden 
HTTP Session döndürür.

Kullanım:
  from data.proxy import get_working_session
  
  session = get_working_session(test_url="https://www.transfermarkt.com")
  if session:
      r = session.get("https://www.transfermarkt.com", timeout=10)
"""

import os
import json
import time
import requests
import concurrent.futures
from typing import List, Optional

# Ayarlar
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "data")
PROXY_CACHE_FILE = os.path.join(CACHE_DIR, "working_proxies.json")
PROXY_CACHE_TIME_SEC = 3600 * 2  # 2 saat cache

# Güncel public proxy kaynakları
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]

def load_cached_proxies() -> List[str]:
    """Önceden test edilmiş çalışan proxy'leri yükler."""
    if not os.path.exists(PROXY_CACHE_FILE):
        return []
    try:
        with open(PROXY_CACHE_FILE, "r") as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) > PROXY_CACHE_TIME_SEC:
            return []
        return data.get("proxies", [])
    except:
        return []

def save_working_proxies(proxies: List[str]):
    """Çalıştığı tespit edilen proxyleri kaydeder."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        data = {
            "timestamp": time.time(),
            "proxies": list(set(proxies))[:50]  # maks 50 proxy tut
        }
        with open(PROXY_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Proxy cache yazılamadı: {e}")

def fetch_raw_proxies() -> List[str]:
    """Dış kaynaklardan ham proxy listesi çeker."""
    print("  🌐 Ücretsiz proxy listeleri indiriliyor...")
    proxies = set()
    for url in PROXY_SOURCES:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                lines = r.text.splitlines()
                for line in lines:
                    line = line.strip()
                    if ":" in line and len(line) > 10:
                        proxies.add(line)
        except:
            pass
    print(f"  🔍 Alınan toplam proxy: {len(proxies)}")
    return list(proxies)

def test_single_proxy(proxy: str, test_url: str, timeout: int = 5) -> Optional[str]:
    """Bir proxy'yi verilen URL üzerinde test eder."""
    proxies_dict = {
        "http": f"http://{proxy}",
        "https": f"http://{proxy}"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        # Hızlı test
        r = requests.get(test_url, proxies=proxies_dict, headers=headers, timeout=timeout)
        if r.status_code in [200, 301, 302, 403, 404]: 
            # 403 ve 404 de bağlantının başarılı olduğunu ama sayfanın/iznin olmadığını gösterir
            # Bize timeout olmayan proxy lazım.
            return proxy
    except:
        pass
    return None

def find_working_proxies(raw_proxies: List[str], test_url: str, required_count: int = 5) -> List[str]:
    """Çoklu iş parçacığı (threading) ile paralelde proxyleri test eder."""
    print(f"  ⚙️  Proxy'ler test ediliyor (hedef: {test_url})...")
    working = []
    
    # FIX: 200→50 subset, daha hızlı tamamlanır
    test_subset = raw_proxies[:50]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(test_single_proxy, p, test_url, 3): p for p in test_subset}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                working.append(res)
                if len(working) >= required_count:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

    return working

def get_working_session(test_url: str = "https://www.google.com") -> requests.Session:
    """
    VPN/Bağlantı sorunu olmaması için çalışan bir proxy içeren session döndürür.
    Öncelikle yerel ağı (kendi IP'mizi) test eder. Çalışıyorsa doğrudan onu verir.
    Eğer ana ağ engelliyse, proxy kullanır.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
    })
    
    # 1. Önce VPN/kendi internetimiz engelli mi kontrol et
    try:
        r = session.get(test_url, timeout=4, verify=False)  # FIX: SSL verify=False + kısa timeout
        if r.status_code in (200, 301, 302, 403, 404):
            print(f"  ✅ Yerel ağ / VPN aktif ({test_url}). Proxy gerekmedi.")
            return session
    except requests.exceptions.SSLError:
        # SSL hatası = bağlantı var ama sertifika sorunlu — direkt session döndür
        print(f"  ⚠️  SSL hatası ({test_url}), verify=False ile devam ediliyor.")
        session.verify = False
        return session
    except Exception:
        pass
    
    print(f"  ⚠️  Yerel ağ ({test_url}) engelli/timeout! Proxy moduna geçiliyor...")
    
    # 2. Cache'den proxy dene
    cached = load_cached_proxies()
    if cached:
        for p in cached[:5]:
            p_dict = {"http": f"http://{p}", "https": f"http://{p}"}
            try:
                session.proxies.update(p_dict)
                r = session.get(test_url, timeout=5)
                if r.status_code == 200:
                    print(f"  ✅ Çalışan proxy (cache): {p}")
                    return session
            except:
                pass
    
    # 3. Yeni proxy çek ve test et
    raw_p = fetch_raw_proxies()
    if not raw_p:
        print("  ❌ Ücretsiz proxy listesi çekilemedi!")
        session.proxies.clear()
        return session
        
    working_p = find_working_proxies(raw_p, test_url=test_url, required_count=3)
    if working_p:
        save_working_proxies(working_p + cached) # cache'e yeni çalışanları ekle
        p = working_p[0]
        session.proxies.update({"http": f"http://{p}", "https": f"http://{p}"})
        print(f"  ✅ Bulunan yeni proxy aktif: {p}")
        return session
    else:
        print("  ❌ Çalışan proxy bulunamadı. Bağlantı sorun yaşayabilir!")
        session.proxies.clear()
        return session

if __name__ == "__main__":
    s = get_working_session("https://api.football-data.org/v4/")
    try:
        print("Test Sonucu:", s.get("https://api.football-data.org/v4/", timeout=5).status_code)
    except Exception as e:
        print("Test başarısız:", e)
