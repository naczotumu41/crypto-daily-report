#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coin Haber İzleme — Derin, Birincil-Kaynaklı Gelişme Takibi
==============================================================

Kullanıcının izlemeye aldığı coin'ler için periyodik olarak (6 saatte bir)
GERÇEKTEN önemli ve DOĞRULANMIŞ gelişmeleri araştırır, sadece yenilerini
Telegram'dan bildirir.

Kaynak kısıtlaması (ÖNEMLİ SINIR): Claude'un WebSearch aracı domain bazlı
kesin bir engelleme desteklemiyor — bu yüzden "sadece şu kaynaklara güven"
kuralı PROMPT ile UYGULANIYOR, teknik bir garanti değil. HABER_ARASTIRMA_
PROMPTU, birincil kaynaklara (projenin resmi kanalları, DefiLlama, Token
Terminal, Glassnode, CryptoQuant, Messari, Dune Analytics, CoinMarketCap/
CoinGecko, ilgili zincirin blok gezgini) öncelik vermesini, X/Twitter gibi
platformlardaki genel/doğrulanmamış yorumu KAYNAK OLARAK KULLANMAMASINI ve
hiçbir önemli/doğrulanmış gelişme yoksa HİÇBİR ŞEY yazmamasını (uydurmadan
kaçınmak için) açıkça istiyor.

Bildirilen her başlık, aynı coin için sonraki çalıştırmalarda tekrar
raporlanmasın diye state/haber_izleme.json'a kaydediliyor ve bir sonraki
promptta "bunları TEKRAR raporlama" bağlamı olarak veriliyor.

izleme kaydı oluşturma/iptal etme asistan.py'den (DURUM G / DURUM D) yapılır;
bu dosya sadece PERİYODİK KONTROLÜ çalıştırır.

Kullanım:
  python haber_izleme.py

Ortam değişkenleri (mevcut secret'lar; YENİ secret gerekmez):
  CLAUDE_CODE_OAUTH_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID
"""

import html
import json
import os
import re
import sys

from report import (
    _claude_calistir,
    _env_yukle,
    _gizle,
    admin_hata_bildir,
    telegram_gonder,
)

_env_yukle()

IZLEME_YOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "haber_izleme.json")
BILINEN_BASLIK_UST_SINIR = 30  # coin başına; bunu aşarsa en eskiler düşürülür

HABER_ARASTIRMA_PROMPTU = """Sen titiz bir kripto proje/piyasa araştırmacısısın. Aşağıdaki coin(ler) için SON birkaç saatteki GERÇEKTEN ÖNEMLİ ve DOĞRULANMIŞ gelişmeleri derinlemesine araştır.

İZLENEN COIN'LER:
{coin_listesi}

DAHA ÖNCE BİLDİRİLMİŞ BAŞLIKLAR (bunları TEKRAR raporlama; sadece GERÇEKTEN yeni bir şey varsa yaz):
{bilinen_basliklar}

KAYNAK KURALLARI (ÇOK ÖNEMLİ — kesinlikle uy):
- SADECE birincil/güvenilir kaynaklara dayan: projenin kendi resmi kanalları (blog, docs, GitHub, resmi duyuru), DefiLlama, Token Terminal, Glassnode, CryptoQuant, Messari, Dune Analytics, CoinMarketCap, CoinGecko, ilgili zincirin blok gezgini (Etherscan, Solscan, vb.), ve resmi kurumsal sosyal medya hesaplarının KENDİ paylaşımı (üçüncü şahıs yorumu/spekülasyonu DEĞİL).
- X/Twitter ve benzeri platformlardaki GENEL kullanıcı yorumunu, spekülasyonu, doğrulanmamış söylentiyi KAYNAK OLARAK KULLANMA. Bir bilgi sadece sosyal medyada konuşuluyorsa ve yukarıdaki birincil kaynaklardan biriyle DOĞRULANAMIYORSA, YAZMA.
- Her bulguya MUTLAKA birincil kaynağın linkini ekle.
- Rutin fiyat hareketi, günlük teknik yorum ya da genel piyasa havasını YAZMA — sadece somut ve önemli bir gelişme yaz (büyük ortaklık, güvenlik olayı/hack, protokol güncellemesi, düzenleyici karar, önemli on-chain hareket, token ekonomisi değişikliği, önemli listeleme/delisting vb.).
- Doğrulayamadığın ya da emin olmadığın hiçbir şeyi yazma.
- Bir coin için gerçekten önemli/doğrulanmış yeni bir gelişme YOKSA o coin hakkında HİÇBİR ŞEY yazma — uydurma.

ÇIKTI — SADECE bu blok, başka HİÇBİR ŞEY yazma:
===HABER===
[{{"coingecko_id": "...", "sembol": "...", "baslik": "kısa başlık (bir daha aynısını tespit etmek için kullanılacak)", "ozet": "1-2 cümlelik Türkçe özet", "kaynak_url": "..."}}]
===HABER-SON===
Yeni/önemli hiçbir şey yoksa boş liste yaz: ===HABER===[]===HABER-SON==="""


def _izlenenleri_oku():
    try:
        with open(IZLEME_YOL, encoding="utf-8") as f:
            v = json.load(f).get("izlenenler", [])
        return v if isinstance(v, list) else []
    except (FileNotFoundError, ValueError, OSError):
        return []


def _izlenenleri_yaz(izlenenler):
    os.makedirs(os.path.dirname(IZLEME_YOL), exist_ok=True)
    with open(IZLEME_YOL, "w", encoding="utf-8") as f:
        json.dump({"izlenenler": izlenenler}, f, ensure_ascii=False, indent=2)


def _haber_ayikla(cevap):
    """Claude'un ham cevabından ===HABER===[...]===HABER-SON=== bloğunu
    ayıklar. Geçerli öğelerin listesini döndürür (boş liste = bulunamadı)."""
    m = re.search(r"===HABER===\s*(.*?)\s*===HABER-SON===", cevap, re.S)
    if not m:
        return []
    try:
        v = json.loads(m.group(1).strip())
    except ValueError:
        return []
    if not isinstance(v, list):
        return []
    return [h for h in v if isinstance(h, dict) and h.get("coingecko_id") and h.get("baslik")]


def haberleri_kontrol_et_ve_bildir(bot_token, admin_id):
    """Aktif izlenen coin'ler için tek bir Claude çağrısıyla derin araştırma
    yapar, sadece GERÇEKTEN yeni/önemli bulguları izlemeyi KURAN sohbete
    bildirir ve bilinen başlıklar listesini günceller."""
    tum_izlenenler = _izlenenleri_oku()
    aktifler = [i for i in tum_izlenenler if i.get("durum") == "aktif"]
    if not aktifler:
        print("[bilgi] İzlenen coin yok.", file=sys.stderr)
        return

    coin_listesi = "\n".join(
        f"- {i.get('sembol')} (coingecko_id: {i.get('coingecko_id')})" for i in aktifler
    )
    tum_bilinen = [b for i in aktifler for b in i.get("bilinen_basliklar", [])]
    bilinen_basliklar = "\n".join(f"- {b}" for b in tum_bilinen) if tum_bilinen else "Yok"

    print(f"[bilgi] {len(aktifler)} coin için haber araştırılıyor (WebSearch)...", file=sys.stderr)
    try:
        ham = _claude_calistir(
            HABER_ARASTIRMA_PROMPTU.format(coin_listesi=coin_listesi, bilinen_basliklar=bilinen_basliklar),
            min_uzunluk=5,
        )
    except Exception as e:                               # noqa: BLE001
        print(f"[uyarı] Haber araştırması başarısız: {_gizle(e)}", file=sys.stderr)
        return

    haberler = _haber_ayikla(ham)
    if not haberler:
        print("[bilgi] Yeni/önemli haber bulunamadı.", file=sys.stderr)
        return

    degisti = False
    for h in haberler:
        eslesen = next((i for i in aktifler if i.get("coingecko_id") == h.get("coingecko_id")), None)
        if not eslesen:
            print(f"[uyarı] Habere eşleşen izlenen coin bulunamadı: {h}", file=sys.stderr)
            continue

        baslik = str(h.get("baslik", "")).strip()
        if baslik in eslesen.get("bilinen_basliklar", []):
            continue  # Claude yine de tekrar yazmış olabilir — sessizce atla

        sembol = eslesen.get("sembol") or eslesen.get("coingecko_id", "")
        ozet = str(h.get("ozet", "")).strip()
        kaynak = str(h.get("kaynak_url", "")).strip()
        mesaj = f"📰 <b>{html.escape(sembol)} Haberi</b>\n{html.escape(baslik)}"
        if ozet:
            mesaj += f"\n{html.escape(ozet)}"
        if kaynak:
            mesaj += f"\n<a href=\"{html.escape(kaynak)}\">Kaynak</a>"
        telegram_gonder(bot_token, eslesen.get("chat_id") or admin_id, mesaj)

        eslesen.setdefault("bilinen_basliklar", []).append(baslik)
        eslesen["bilinen_basliklar"] = eslesen["bilinen_basliklar"][-BILINEN_BASLIK_UST_SINIR:]
        degisti = True
        print(f"[bilgi] Yeni haber bildirildi: {sembol} — {baslik}", file=sys.stderr)

    if degisti:
        _izlenenleri_yaz(tum_izlenenler)


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    admin_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
    if not bot_token or not admin_id:
        print("HATA: TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_CHAT_ID tanımlı değil.", file=sys.stderr)
        sys.exit(1)

    try:
        haberleri_kontrol_et_ve_bildir(bot_token, admin_id)
    except Exception as e:                               # noqa: BLE001
        print(f"[HATA] {_gizle(e)}", file=sys.stderr)
        admin_hata_bildir(_gizle(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
