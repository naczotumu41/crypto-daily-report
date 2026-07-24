#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kripto Asistan — Telegram'dan Soru Al, Claude ile Cevapla
===========================================================

report.py'nin günlük 08:00 raporundan AYRI, admin'in Telegram'da bota özelden
yazdığı soruları (haber, "neden düştü/battı", genel piyasa soruları)
cevaplayan ek katman. GitHub Actions'ta ayrı bir workflow (asistan.yml) her
birkaç dakikada bir çalışır; yeni mesaj yoksa Claude'a hiç dokunmadan çıkar.

Kullanım:
  python asistan.py --kontrol   Yanıt bekleyen admin mesajı var mı bakar
                                 (Claude'a DOKUNMAZ, state'i DEĞİŞTİRMEZ).
                                 Sonucu GITHUB_OUTPUT'a "mesaj_var=true/false"
                                 olarak yazar (workflow bir sonraki, pahalı
                                 adımı — Claude Code CLI kurulumu — buna göre
                                 atlar ya da çalıştırır).
  python asistan.py             Bekleyen admin mesaj(lar)ını Claude ile
                                 cevaplayıp Telegram'a gönderir, state'i ilerletir.

Yalnızca TELEGRAM_ADMIN_CHAT_ID'den gelen mesajlar cevaplanır — kanaldaki ya
da botla konuşan başka biri Claude aboneliğini tüketmesin diye.

Ortam değişkenleri (report.py ile aynı secret'lar; YENİ secret gerekmez):
  CLAUDE_CODE_OAUTH_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID
"""

import html
import json
import os
import sys

from report import (
    _claude_calistir,
    _env_yukle,
    _get_json,
    _gizle,
    admin_hata_bildir,
    mesaji_bol,
    telegram_gonder,
)

_env_yukle()

STATE_YOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "asistan.json")

# SORU PROMPTU — admin'in tek bir mesajına verilecek cevabı üretmek için
# headless Claude Code'a verilir. {soru} çalışma anında doldurulur.
SORU_PROMPTU = """Sen Telegram'da çalışan bir kripto/piyasa asistanısın. Kullanıcı (botun sahibi) sana özel olarak aşağıdaki soruyu sordu; ona doğrudan cevap ver.

KULLANICININ SORUSU:
{soru}

Soru güncel bir olayla ilgiliyse (haber, "neden düştü/yükseldi/battı" gibi) WebSearch ile son gelişmeleri araştır; yalnızca doğruladığın bilgiyi yaz, uydurma, önemli iddialarda kaynak belirt.

ÇIKTI KURALLARI:
- Telegram HTML kullan (<b>, <i>, <a href="">); markdown/tablo KULLANMA.
- Kısa ve öz cevap ver, gereksiz giriş cümlesi kurma; doğrudan konuya gir.
- Doğrulayamadığın sayısal iddiayı yazma; gerekirse "doğrulanamadı" de.
- Kullanıcı net bir alım/satım ya da giriş/çıkış fiyat seviyesi isterse: bunu
  ŞU AN hesaplayamadığını söyle (canlı grafik/teknik veriye erişimin yok),
  genel piyasa yorumu yapabilirsin ama UYDURMA SAYI VERME; bu özelliğin ayrıca
  geliştirilmekte olduğunu belirt.
- Finansal görüş/yorum içeren cevapların sonuna kısaca "Yatırım tavsiyesi
  değildir." ekle.
- Cevap SADECE yanıtın kendisi olsun; "işte cevabım" gibi ek ifade yazma."""


def _durum_oku():
    try:
        with open(STATE_YOL, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _durum_yaz(son_update_id):
    os.makedirs(os.path.dirname(STATE_YOL), exist_ok=True)
    with open(STATE_YOL, "w", encoding="utf-8") as f:
        json.dump({"son_update_id": son_update_id}, f, ensure_ascii=False, indent=2)


def _guncellemeleri_al(bot_token, offset):
    """Telegram getUpdates ile offset'ten sonraki güncellemeleri çeker."""
    params = {"timeout": 0, "allowed_updates": json.dumps(["message"])}
    if offset is not None:
        params["offset"] = offset
    veri = _get_json(f"https://api.telegram.org/bot{bot_token}/getUpdates", params=params)
    return veri.get("result", [])


def _admin_mesajlarini_ayikla(guncellemeler, admin_id):
    """Güncellemeler arasından admin'in metin mesajlarını çıkarır.
    (admin_mesajlari, en_buyuk_update_id) döndürür — ikincisi None ise hiç
    güncelleme yok demektir."""
    admin_id = str(admin_id)
    mesajlar = []
    son_id = None
    for g in guncellemeler:
        son_id = g["update_id"] if son_id is None else max(son_id, g["update_id"])
        msg = g.get("message") or {}
        metin = msg.get("text")
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        if metin and chat_id == admin_id:
            mesajlar.append(metin)
    return mesajlar, son_id


def _github_output_yaz(anahtar, deger):
    yol = os.environ.get("GITHUB_OUTPUT")
    if not yol:
        return
    with open(yol, "a", encoding="utf-8") as f:
        f.write(f"{anahtar}={deger}\n")


def kontrol_et(bot_token, admin_id):
    """Claude'a hiç dokunmadan: yanıt bekleyen admin mesajı var mı bakar."""
    durum = _durum_oku()
    ud = durum.get("son_update_id")
    guncellemeler = _guncellemeleri_al(bot_token, ud + 1 if ud else None)
    mesajlar, _ = _admin_mesajlarini_ayikla(guncellemeler, admin_id)
    _github_output_yaz("mesaj_var", "true" if mesajlar else "false")
    print(f"[bilgi] {len(guncellemeler)} güncelleme, {len(mesajlar)} admin mesajı bekliyor.",
          file=sys.stderr)


def cevapla(bot_token, admin_id):
    """Bekleyen admin mesaj(lar)ını Claude ile cevaplar ve state'i ilerletir."""
    durum = _durum_oku()
    ud = durum.get("son_update_id")
    guncellemeler = _guncellemeleri_al(bot_token, ud + 1 if ud else None)
    mesajlar, son_id = _admin_mesajlarini_ayikla(guncellemeler, admin_id)

    if not mesajlar:
        print("[bilgi] Cevaplanacak yeni admin mesajı yok.", file=sys.stderr)
        if son_id is not None:
            _durum_yaz(son_id)
        return

    for soru in mesajlar:
        print(f"[bilgi] Soru cevaplanıyor: {soru[:80]!r}", file=sys.stderr)
        try:
            cevap = _claude_calistir(SORU_PROMPTU.format(soru=soru), min_uzunluk=10)
        except Exception as e:                       # noqa: BLE001
            cevap = f"⚠️ Bu soruyu cevaplarken bir hata oluştu: {html.escape(str(e)[:300])}"
        for parca in mesaji_bol(cevap):
            telegram_gonder(bot_token, admin_id, parca)

    # Mesajları başarıyla cevapladıktan sonra state'i ilerlet — yarı yolda
    # hata olursa (ör. 3. soruda) offset ilerlemez, bir sonraki çalıştırma
    # aynı soruları (cevaplananlar dahil) tekrar dener; kabul edilebilir çünkü
    # tekrar cevap almak, hiç cevap almamaktan iyidir.
    if son_id is not None:
        _durum_yaz(son_id)


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    admin_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
    if not bot_token or not admin_id:
        print("HATA: TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_CHAT_ID tanımlı değil.", file=sys.stderr)
        sys.exit(1)

    try:
        if "--kontrol" in sys.argv:
            kontrol_et(bot_token, admin_id)
        else:
            cevapla(bot_token, admin_id)
    except Exception as e:                           # noqa: BLE001
        print(f"[HATA] {_gizle(e)}", file=sys.stderr)
        admin_hata_bildir(_gizle(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
