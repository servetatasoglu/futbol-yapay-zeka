# analysis/pipeline_helpers.py
"""Main pipeline: maç listesi ile value bet birleştirme, market/edge motoru zenginleştirme."""

from __future__ import annotations


def _mac_id(ev: str, dep: str, mac_tarihi) -> str:
    return f"{ev}|{dep}|{str(mac_tarihi or '')[:10]}"


def _secilen_kitap(ko: dict, tahmin: str) -> str:
    """kitap_oranlari: book -> (ev_o, ber_o, dep_o)"""
    if not ko:
        return "aggregate"
    if tahmin == "Ev Sahibi Kazanır":
        return max(ko, key=lambda k: ko[k][0])
    if tahmin == "Beraberlik":
        return max(ko, key=lambda k: ko[k][1])
    if tahmin == "Deplasman Kazanır":
        return max(ko, key=lambda k: ko[k][2])
    return "aggregate"


def mac_listesinden_indeks(mac_listesi: list) -> dict:
    d = {}
    for m in mac_listesi:
        d[_mac_id(m.get("ev", ""), m.get("dep", ""), m.get("mac_tarihi"))] = m
    return d


def zenginlestir_market_ve_edge(
    value_betler: list,
    mac_listesi: list,
    edge_guvenilik_skoru_fn,
    piyasa_verimlilik_skoru_fn,
) -> None:
    """Her bahise piyasa sözlüğü, edge güvenilirlik ve verimlilik ekler (yerinde)."""
    idx = mac_listesinden_indeks(mac_listesi)
    for bet in value_betler:
        mid = bet.get("mac_id") or _mac_id(
            bet.get("ev", ""), bet.get("dep", ""), bet.get("mac_tarihi", "")
        )
        mac = idx.get(mid)
        if not mac:
            for _k, m in idx.items():
                if m.get("ev") == bet.get("ev") and m.get("dep") == bet.get("dep"):
                    mac = m
                    break
        or_def = (mac or {}).get("over_round", 1.08)
        ks_def = (mac or {}).get("kitap_sayisi", 1)
        pin_def = (mac or {}).get("pinnacle_var", False)
        bf_def = (mac or {}).get("betfair_var", False)
        mac_mini = {
            "over_round":   float(bet.get("over_round", or_def) or or_def),
            "kitap_sayisi": int(bet.get("kitap_sayisi", ks_def) or ks_def),
            "pinnacle_var": bool(bet.get("pinnacle_var", pin_def)),
            "betfair_var":  bool(bf_def),
        }
        if mac:
            bet.setdefault("ev_oran", mac.get("ev_oran"))
            bet.setdefault("ber_oran", mac.get("ber_oran"))
            bet.setdefault("dep_oran", mac.get("dep_oran"))
            ko = mac.get("kitap_oranlari") or {}
            bet["kitap"] = _secilen_kitap(ko, bet.get("tahmin", ""))
        else:
            bet.setdefault("ev_oran", bet.get("oran"))
            bet.setdefault("ber_oran", 0)
            bet.setdefault("dep_oran", 0)
            bet.setdefault("kitap", "aggregate")

        edge = float(bet.get("edge", 0) or 0)
        bet["edge_guvenilik"] = edge_guvenilik_skoru_fn(edge, mac_mini)
        bet["piyasa_verimlilik"] = piyasa_verimlilik_skoru_fn(mac_mini)


def uygula_fl1_beraberlik_limiti(value_betler: list, fl1_aktif: bool, fl1_max: int, ber_max: int) -> list:
    if not fl1_aktif:
        return value_betler
    fl1_sayac = ber_sayac = 0
    out = []
    for vb in value_betler:
        lig = vb.get("lig_kodu", "")
        tah = vb.get("tahmin", "")
        if lig == "FL1":
            if fl1_sayac >= fl1_max:
                continue
            fl1_sayac += 1
        if tah == "Beraberlik":
            if ber_sayac >= ber_max:
                continue
            ber_sayac += 1
        out.append(vb)
    return out
