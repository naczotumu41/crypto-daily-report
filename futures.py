#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Futures Sinyalleri — Saatlik Teknik Analiz
=============================================

Her saat, BTC/ETH/XRP/BNB için Binance Futures'tan gerçek OHLC mum verisi
çekip ATR ve EMA20/EMA50 trendini SAF PYTHON ile hesaplar (LLM'e sayı
uydurtulmaz — proje genelindeki ilke burada da geçerli). Giriş, stop-loss ve
hedef seviyeleri bu hesaplardan üretilir. Claude'a sadece kısa bir "neden"
gerekçesi yazdırılır (WebSearch ile güncel haber/gelişme kontrolü); Claude
sayısal seviyeleri DEĞİŞTİREMEZ.

Risk yönetimi: stop-loss, iki mesafeden KÜÇÜK OLANI kullanır:
  1) ATR_CARPANI * ATR(14) — teknik olarak makul bir stop mesafesi
  2) (MAX_SERMAYE_RISKI / KALDIRAC) * giriş fiyatı — sermayenin en fazla
     MAX_SERMAYE_RISKI kadarını riske atacak mesafe (varsayılan KALDIRAC'a göre)
Yani sermaye riski ASLA MAX_SERMAYE_RISKI'ni aşmaz; ATR daha dar bir stop
öneriyorsa o kullanılır (daha az risk). Hedef, stop mesafesinin RR_ORANI katı
uzaklıkta, ama en yakın destek/direnç varsa ondan öteye geçmez.

Sadece admin'e (TELEGRAM_ADMIN_CHAT_ID) özelden gönderilir — kanala gitmez.

Kullanım:
  python futures.py

Ortam değişkenleri (mevcut secret'lar; YENİ secret gerekmez):
  CLAUDE_CODE_OAUTH_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID

⚠️ Yatırım tavsiyesi değildir. Kaldıraçlı işlemler yüksek risk taşır.
"""

import os
import sys
from datetime import datetime

from report import (
    IST,
    _claude_calistir,
    _env_yukle,
    _get_json,
    _gizle,
    admin_hata_bildir,
    mesaji_bol,
    telegram_gonder,
)

_env_yukle()

# Binance Futures sembolü -> gösterim sembolü
SEMBOLLER = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "XRPUSDT": "XRP", "BNBUSDT": "BNB"}

MUM_ARALIGI = "1h"
MUM_SAYISI = 100          # EMA50 + ATR(14) için yeterli geçmiş
DESTEK_DIRENC_PENCERESI = 30  # son N mumda swing high/low

MAX_SERMAYE_RISKI = 0.10  # sermayenin en fazla %10'u riske atılır
KALDIRAC = 3               # varsayılan kaldıraç (kullanıcı onayladı)
ATR_CARPANI = 1.5          # stop için ATR çarpanı
RR_ORANI = 2.0             # hedef mesafesi = stop mesafesi * RR_ORANI

ANALIZ_PROMPTU = """Sen bir kripto futures piyasa analistisin. Aşağıda TEKNİK VERİLERDEN (ATR ve EMA trend hesabıyla üretilmiş, senin uydurmadığın ve DEĞİŞTİREMEYECEĞİN) sinyaller var:

{seviyeler_metni}

Her coin için WebSearch ile SON birkaç saatteki gelişmeleri/haberleri kontrol et; teknik yön ile güncel haber akışı uyumlu mu değil mi kısaca belirt. Yalnızca doğruladığın bilgiyi kullan, uydurma.

ÇIKTI KURALLARI:
- Her coin için TEK SATIR gerekçe yaz, satır coin sembolüyle başlasın (ör. "<b>BTC:</b> ...").
- Telegram HTML kullan (<b>, <i>, <a href="">); markdown KULLANMA.
- Sayısal seviyeleri (giriş/stop/hedef) ASLA yazma/değiştirme — onlar zaten mesajda var, sadece kısa gerekçe ver.
- Giriş cümlesi kurma, doğrudan ilk coin'in satırıyla başla."""


# --------------------------------------------------------------------------- #
# Saf hesaplama fonksiyonları — ağ GEREKTİRMEZ, test edilebilir
# --------------------------------------------------------------------------- #

def _atr_hesapla(mumlar, periyot=14):
    """mumlar: kronolojik sıralı [{"open","high","low","close"}, ...] listesi.
    True Range ortalamasını (ATR) döndürür."""
    if len(mumlar) < periyot + 1:
        raise ValueError("ATR için yetersiz mum sayısı")
    trs = []
    for i in range(1, len(mumlar)):
        h, l = mumlar[i]["high"], mumlar[i]["low"]
        c_onceki = mumlar[i - 1]["close"]
        trs.append(max(h - l, abs(h - c_onceki), abs(l - c_onceki)))
    return sum(trs[-periyot:]) / periyot


def _ema_hesapla(kapanislar, periyot):
    """Basit ortalamayla başlayıp üstel ağırlıklandıran klasik EMA."""
    if len(kapanislar) < periyot:
        raise ValueError("EMA için yetersiz mum sayısı")
    k = 2 / (periyot + 1)
    ema = sum(kapanislar[:periyot]) / periyot
    for fiyat in kapanislar[periyot:]:
        ema = fiyat * k + ema * (1 - k)
    return ema


def _yon_belirle(kapanislar):
    """Fiyat ve EMA20/EMA50 hizasına göre 'long', 'short' ya da net trend
    yoksa None döndürür."""
    ema20 = _ema_hesapla(kapanislar, 20)
    ema50 = _ema_hesapla(kapanislar, 50)
    fiyat = kapanislar[-1]
    if fiyat > ema20 > ema50:
        return "long"
    if fiyat < ema20 < ema50:
        return "short"
    return None


def _destek_direnc(mumlar, pencere=DESTEK_DIRENC_PENCERESI):
    """Son `pencere` mumdaki en düşük low / en yüksek high (basit swing seviyeleri)."""
    alt = mumlar[-pencere:]
    return min(m["low"] for m in alt), max(m["high"] for m in alt)


def _seviyeleri_hesapla(mumlar):
    """Kronolojik mum listesinden giriş/stop/hedef seviyelerini hesaplar.
    Dönen dict: yon (None ise net trend yok, diğer alanlar hesaplanmaz),
    giris, stop, hedef, atr, sermaye_riski_yuzde, stop_sinirlandi (bool:
    ATR yerine sermaye risk sınırının bağlayıcı olup olmadığı)."""
    kapanislar = [m["close"] for m in mumlar]
    yon = _yon_belirle(kapanislar)
    if yon is None:
        return {"yon": None}

    giris = kapanislar[-1]
    atr = _atr_hesapla(mumlar)
    atr_mesafe = atr * ATR_CARPANI
    risk_mesafe = giris * (MAX_SERMAYE_RISKI / KALDIRAC)
    stop_mesafe = min(atr_mesafe, risk_mesafe)
    stop_sinirlandi = risk_mesafe < atr_mesafe

    destek, direnc = _destek_direnc(mumlar)
    hedef_mesafe = stop_mesafe * RR_ORANI

    if yon == "long":
        stop = giris - stop_mesafe
        hedef = giris + hedef_mesafe
        if direnc > giris:
            hedef = min(hedef, direnc)
    else:
        stop = giris + stop_mesafe
        hedef = giris - hedef_mesafe
        if destek < giris:
            hedef = max(hedef, destek)

    sermaye_riski_yuzde = (stop_mesafe / giris) * KALDIRAC * 100

    return {
        "yon": yon, "giris": giris, "stop": stop, "hedef": hedef, "atr": atr,
        "sermaye_riski_yuzde": sermaye_riski_yuzde, "stop_sinirlandi": stop_sinirlandi,
    }


# --------------------------------------------------------------------------- #
# Ağ — Binance Futures'tan gerçek mum verisi
# --------------------------------------------------------------------------- #

def _mumlari_cek(sembol, aralik=MUM_ARALIGI, sayi=MUM_SAYISI):
    """Binance Futures public API'sinden OHLC mum verisi çeker (API key gerekmez)."""
    veri = _get_json(
        "https://fapi.binance.com/fapi/v1/klines",
        params={"symbol": sembol, "interval": aralik, "limit": sayi},
    )
    return [
        {"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])}
        for k in veri
    ]


# --------------------------------------------------------------------------- #
# Mesaj biçimlendirme + gönderim
# --------------------------------------------------------------------------- #

def _fiyat_bicimle(v):
    return f"${v:,.2f}" if v < 100 else f"${v:,.0f}"


def _sinyal_blogu(sembol, s):
    if s["yon"] is None:
        return f"<b>{sembol}</b> — net trend yok, sinyal atlandı."

    yon_metni = "LONG 🟢" if s["yon"] == "long" else "SHORT 🔴"
    risk_notu = (f"~%{s['sermaye_riski_yuzde']:.1f} sermaye riski @ {KALDIRAC}x kaldıraç"
                 + (" (sermaye limiti bağlayıcı — ATR daha geniş bir stop öneriyordu)"
                    if s["stop_sinirlandi"] else ""))
    return (
        f"<b>{sembol}</b> — {yon_metni}\n"
        f"Giriş: {_fiyat_bicimle(s['giris'])}\n"
        f"Stop: {_fiyat_bicimle(s['stop'])} ({risk_notu})\n"
        f"Hedef: {_fiyat_bicimle(s['hedef'])} (R:R 1:{RR_ORANI:g})"
    )


def _analiz_uret(coin_seviyeleri):
    """Sadece sinyali olan (yon != None) coin'ler için Claude'dan kısa
    WebSearch destekli gerekçe ister. Hiç sinyal yoksa Claude'a hiç dokunmaz."""
    aktifler = {sembol: s for sembol, s in coin_seviyeleri.items() if s["yon"] is not None}
    if not aktifler:
        return ""

    satirlar = []
    for sembol, s in aktifler.items():
        yon_tr = "yükseliş (LONG)" if s["yon"] == "long" else "düşüş (SHORT)"
        satirlar.append(
            f"{sembol}: yön={yon_tr}, giriş={_fiyat_bicimle(s['giris'])}, "
            f"stop={_fiyat_bicimle(s['stop'])}, hedef={_fiyat_bicimle(s['hedef'])}"
        )
    prompt = ANALIZ_PROMPTU.format(seviyeler_metni="\n".join(satirlar))

    try:
        return "\n" + _claude_calistir(prompt, min_uzunluk=10)
    except Exception as e:                               # noqa: BLE001
        print(f"[uyarı] Analiz gerekçesi üretilemedi: {_gizle(e)}", file=sys.stderr)
        return ""


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    admin_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
    if not bot_token or not admin_id:
        print("HATA: TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_CHAT_ID tanımlı değil.", file=sys.stderr)
        sys.exit(1)

    try:
        coin_seviyeleri = {}
        for binance_sembol, gosterim in SEMBOLLER.items():
            print(f"[bilgi] {gosterim} mum verisi çekiliyor...", file=sys.stderr)
            mumlar = _mumlari_cek(binance_sembol)
            coin_seviyeleri[gosterim] = _seviyeleri_hesapla(mumlar)

        print("[bilgi] Analiz gerekçesi üretiliyor (WebSearch)...", file=sys.stderr)
        analiz = _analiz_uret(coin_seviyeleri)

        simdi = datetime.now(IST).strftime("%H:%M TSİ")
        bloklar = [_sinyal_blogu(sembol, s) for sembol, s in coin_seviyeleri.items()]
        mesaj = (
            f"⏰ <b>Futures Sinyalleri — {simdi}</b>\n\n"
            + "\n\n".join(bloklar)
        )
        if analiz:
            mesaj += f"\n\n📰 <b>Kısa gerekçeler</b>{analiz}"
        mesaj += (
            "\n\n⚠️ <i>Gerçek zamanlı hesaplanmış teknik seviyelerdir, YATIRIM TAVSİYESİ "
            "DEĞİLDİR. Kaldıraçlı işlemler yüksek risk taşır, sermayenizin tamamını "
            "kaybedebilirsiniz. Kendi araştırmanızı yapın.</i>"
        )

        for parca in mesaji_bol(mesaj):
            telegram_gonder(bot_token, admin_id, parca)
        print("[başarılı] Futures sinyalleri admin'e gönderildi.", file=sys.stderr)

    except Exception as e:                               # noqa: BLE001
        print(f"[HATA] {_gizle(e)}", file=sys.stderr)
        admin_hata_bildir(_gizle(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
