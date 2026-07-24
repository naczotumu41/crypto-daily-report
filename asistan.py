#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kripto Asistan — Telegram'dan Soru Al, Claude ile Cevapla, Zamanlı Mail Gönder
================================================================================

report.py'nin günlük 08:00 raporundan AYRI, admin'in Telegram'da bota özelden
yazdığı soruları (haber, "neden düştü/battı", genel piyasa soruları)
cevaplayan VE "şu gün şu saatte bana ... mail at" görevlerini zamanında
yerine getiren ek katman. GitHub Actions'ta ayrı bir workflow (asistan.yml)
her birkaç dakikada bir çalışır; yeni mesaj/vadesi gelmiş görev yoksa
Claude'a hiç dokunmadan çıkar.

Kullanım:
  python asistan.py --kontrol   Yanıt bekleyen admin mesajı YA DA vadesi gelmiş
                                 mail görevi var mı bakar (Claude'a DOKUNMAZ,
                                 state'i DEĞİŞTİRMEZ). Sonucu GITHUB_OUTPUT'a
                                 "mesaj_var=true/false" olarak yazar (workflow
                                 bir sonraki, pahalı adımı — Claude Code CLI
                                 kurulumu — buna göre atlar ya da çalıştırır).
  python asistan.py             Bekleyen admin mesaj(lar)ını Claude ile
                                 cevaplar (bir mesaj mail görevi zamanlıyorsa
                                 state/gorevler.json'a kaydeder), state'i
                                 ilerletir, ARDINDAN vadesi gelmiş mail
                                 görevlerini üretip gönderir.

Yalnızca TELEGRAM_ADMIN_CHAT_ID'den gelen mesajlar cevaplanır — kanaldaki ya
da botla konuşan başka biri Claude aboneliğini/mail kotasını tüketmesin diye.

Ortam değişkenleri:
  Mevcut (report.py ile paylaşılır): CLAUDE_CODE_OAUTH_TOKEN,
    TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID
  Mail özelliği için YENİ (Gmail SMTP, uygulama şifresi ile — ücretsiz):
    SMTP_GMAIL_ADRES, SMTP_UYGULAMA_SIFRESI, ALICI_EMAIL
"""

import html
import json
import os
import re
import smtplib
import sys
import time
import uuid
from datetime import datetime
from email.message import EmailMessage

from report import (
    HTTP_TIMEOUT,
    IST,
    MAX_RETRY,
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
GOREVLER_YOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "gorevler.json")

# SORU PROMPTU — admin'in tek bir mesajına verilecek cevabı üretmek için
# headless Claude Code'a verilir. {soru} ve {simdi} çalışma anında doldurulur.
SORU_PROMPTU = """Sen Telegram'da çalışan bir kripto/piyasa asistanısın. Kullanıcı (botun sahibi) sana özel olarak aşağıdaki mesajı yazdı.

BUGÜNÜN TARİHİ VE SAATİ (TSİ): {simdi}

KULLANICININ MESAJI:
{soru}

Önce şunu ayırt et:

DURUM A — Kullanıcı senden GELECEKTE belirli bir gün/saatte MAİL göndermeni istiyor (ör. "yarın sabah 9'da bana BTC durumunu mail at", "25 Temmuz 14:00'te şunu mail olarak yolla", "cuma günü bana ... gönder"):
  1. Kullanıcıya TEK CÜMLELİK kısa bir onay yaz (ör. "Tamam, 25 Temmuz 2026 14:00 TSİ'de mail göndereceğim.").
  2. Onay cümlesinin hemen altına, TAM bu formatta bir görev bloğu ekle (Telegram'a GİTMEYECEK, sistem tarafından okunacak):
===GOREV===
{{"hedef_zaman": "YYYY-MM-DDTHH:MM:SS+03:00", "icerik_talebi": "mail gönderileceği anda ne yapılması gerektiğinin net, bağımsız bir açıklaması"}}
===GOREV-SON===
  - hedef_zaman'ı BUGÜNÜN TARİHİNE göre MUTLAKA gelecekte bir an olacak şekilde, ISO 8601 + Europe/Istanbul (+03:00) ofsetiyle hesapla. "yarın", "cuma", "3 gün sonra" gibi göreli ifadeleri yukarıdaki bugünün tarihinden yola çıkarak kesin tarihe çevir. Kullanıcı saat belirtmediyse 09:00 varsay.
  - icerik_talebi alanı, o an ayrı bir Claude çağrısına doğrudan talimat olarak verilecek; bağımsız, net ve kendi başına anlaşılır olsun (ör. "Güncel BTC ve ETH fiyatlarını, 24 saatlik değişimi ve varsa önemli gelişmeleri özetle").
  - Bu durumda NORMAL cevap yazma, SADECE onay cümlesi + görev bloğunu yaz.

DURUM B — Diğer her şey (soru, haber talebi, "neden düştü/battı" gibi açıklama istekleri, genel sohbet):
  Doğrudan cevap ver. Soru güncel bir olayla ilgiliyse WebSearch ile son gelişmeleri araştır; yalnızca doğruladığın bilgiyi yaz, uydurma, önemli iddialarda kaynak belirt.

  ÇIKTI KURALLARI (DURUM B için):
  - Telegram HTML kullan (<b>, <i>, <a href="">); markdown/tablo KULLANMA.
  - Kısa ve öz cevap ver, gereksiz giriş cümlesi kurma; doğrudan konuya gir.
  - Doğrulayamadığın sayısal iddiayı yazma; gerekirse "doğrulanamadı" de.
  - Kullanıcı net bir alım/satım ya da giriş/çıkış fiyat seviyesi isterse: bunu
    ŞU AN hesaplayamadığını söyle (canlı grafik/teknik veriye erişimin yok),
    genel piyasa yorumu yapabilirsin ama UYDURMA SAYI VERME; bu özelliğin ayrıca
    geliştirilmekte olduğunu belirt.
  - Finansal görüş/yorum içeren cevapların sonuna kısaca "Yatırım tavsiyesi
    değildir." ekle.

Cevap SADECE ilgili durumun çıktısı olsun; "işte cevabım" gibi ek ifade yazma."""

# MAIL İÇERİK PROMPTU — bir görevin vadesi geldiğinde e-posta gövdesini
# üretmek için headless Claude Code'a verilir. {icerik_talebi} doldurulur.
MAIL_ICERIK_PROMPTU = """Aşağıdaki görev talebine göre, e-posta ile gönderilecek Türkçe bir içerik yaz.

GÖREV TALEBİ:
{icerik_talebi}

Gerekiyorsa (güncel fiyat, haber, gelişme vb.) WebSearch ile araştır; doğrulayamadığın hiçbir sayıyı uydurma, gerekirse "doğrulanamadı" de.

ÇIKTI KURALLARI:
- Düz metin yaz (e-posta gövdesi); HTML/markdown KULLANMA.
- Kısa ve öz ol, doğrudan konuya gir.
- Finansal görüş/yorum içeriyorsa sona "Yatırım tavsiyesi değildir." ekle.
- Sonuna ayrı bir satırda "— Kripto Asistanı" imzasını ekle.
- Çıktı SADECE e-posta gövdesinin kendisi olsun; "işte içerik" gibi ek ifade yazma."""


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


# --------------------------------------------------------------------------- #
# Görev (zamanlı mail) yönetimi
# --------------------------------------------------------------------------- #

def _gorevleri_oku():
    try:
        with open(GOREVLER_YOL, encoding="utf-8") as f:
            v = json.load(f).get("gorevler", [])
        return v if isinstance(v, list) else []
    except (FileNotFoundError, ValueError, OSError):
        return []


def _gorevleri_yaz(gorevler):
    os.makedirs(os.path.dirname(GOREVLER_YOL), exist_ok=True)
    with open(GOREVLER_YOL, "w", encoding="utf-8") as f:
        json.dump({"gorevler": gorevler}, f, ensure_ascii=False, indent=2)


def _gorev_ayikla(cevap):
    """Claude'un ham cevabından ===GOREV===...===GOREV-SON=== bloğunu ayıklar.
    (temiz_cevap, gorev_dict_or_None) döndürür."""
    m = re.search(r"===GOREV===\s*(.*?)\s*===GOREV-SON===", cevap, re.S)
    gorev = None
    if m:
        try:
            v = json.loads(m.group(1).strip())
            if isinstance(v, dict) and v.get("hedef_zaman") and v.get("icerik_talebi"):
                gorev = v
        except ValueError:
            gorev = None
    temiz = re.split(r"===GOREV===", cevap, maxsplit=1)[0].strip()
    return temiz, gorev


def _hedef_zamani_ayristir(deger):
    """ISO 8601 zaman damgasını ayrıştırır; saat dilimi yoksa TSİ varsayar."""
    hz = datetime.fromisoformat(str(deger))
    if hz.tzinfo is None:
        hz = hz.replace(tzinfo=IST)
    return hz


def _vadesi_gelmis_gorev_var_mi():
    simdi = datetime.now(IST)
    for g in _gorevleri_oku():
        if g.get("durum") != "bekliyor":
            continue
        try:
            if _hedef_zamani_ayristir(g["hedef_zaman"]) <= simdi:
                return True
        except (ValueError, KeyError):
            continue
    return False


def _mail_gonder(konu, govde):
    """Gmail SMTP (uygulama şifresi) ile tek bir e-posta gönderir. Ağ
    hatalarında MAX_RETRY kez dener."""
    gonderen = os.environ.get("SMTP_GMAIL_ADRES")
    sifre = os.environ.get("SMTP_UYGULAMA_SIFRESI")
    alici = os.environ.get("ALICI_EMAIL")
    if not (gonderen and sifre and alici):
        raise RuntimeError(
            "SMTP_GMAIL_ADRES / SMTP_UYGULAMA_SIFRESI / ALICI_EMAIL tanımlı değil."
        )

    msg = EmailMessage()
    msg["Subject"] = konu
    msg["From"] = gonderen
    msg["To"] = alici
    msg.set_content(govde)

    son_hata = None
    for deneme in range(1, MAX_RETRY + 1):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=HTTP_TIMEOUT) as s:
                s.login(gonderen, sifre)
                s.send_message(msg)
            return
        except Exception as e:                       # noqa: BLE001
            son_hata = e
            print(f"[uyarı] Mail gönderimi başarısız ({deneme}/{MAX_RETRY}): {e}", file=sys.stderr)
            if deneme < MAX_RETRY:
                time.sleep(2 * deneme)
    raise RuntimeError(f"Mail gönderimi {MAX_RETRY} denemede başarısız: {son_hata}")


def _vadesi_gelmis_gorevleri_gonder(bot_token, admin_id):
    """Vadesi gelmiş 'bekliyor' görevler için mail içeriği üretip gönderir,
    her görevin durumunu günceller ve admin'i Telegram'dan bilgilendirir."""
    gorevler = _gorevleri_oku()
    simdi = datetime.now(IST)
    degisti = False

    for g in gorevler:
        if g.get("durum") != "bekliyor":
            continue
        try:
            hz = _hedef_zamani_ayristir(g["hedef_zaman"])
        except (ValueError, KeyError) as e:
            g["durum"] = "hata"
            g["hata"] = f"geçersiz hedef_zaman: {e}"
            degisti = True
            continue
        if hz > simdi:
            continue

        icerik_talebi = str(g.get("icerik_talebi", "")).strip()
        print(f"[bilgi] Görev vadesi geldi, mail hazırlanıyor: {icerik_talebi[:80]!r}",
              file=sys.stderr)
        try:
            govde = _claude_calistir(MAIL_ICERIK_PROMPTU.format(icerik_talebi=icerik_talebi),
                                     min_uzunluk=10)
            konu = f"Kripto Asistanı: {icerik_talebi[:60].strip()}"
            _mail_gonder(konu, govde)
            g["durum"] = "gonderildi"
            g["gonderim_zamani"] = simdi.isoformat()
            telegram_gonder(bot_token, admin_id,
                            f"✅ Mail gönderildi: <i>{html.escape(icerik_talebi[:150])}</i>")
        except Exception as e:                       # noqa: BLE001
            g["durum"] = "hata"
            g["hata"] = str(e)[:300]
            print(f"[uyarı] Görev maili gönderilemedi: {_gizle(e)}", file=sys.stderr)
            telegram_gonder(bot_token, admin_id,
                            f"⚠️ Zamanlanmış mail gönderilemedi: {html.escape(str(e)[:300])}")
        degisti = True

    if degisti:
        _gorevleri_yaz(gorevler)


def kontrol_et(bot_token, admin_id):
    """Claude'a hiç dokunmadan: yanıt bekleyen admin mesajı YA DA vadesi
    gelmiş mail görevi var mı bakar."""
    durum = _durum_oku()
    ud = durum.get("son_update_id")
    guncellemeler = _guncellemeleri_al(bot_token, ud + 1 if ud else None)
    mesajlar, _ = _admin_mesajlarini_ayikla(guncellemeler, admin_id)
    gorev_vadesi_geldi = _vadesi_gelmis_gorev_var_mi()
    islenecek_var = bool(mesajlar) or gorev_vadesi_geldi
    _github_output_yaz("mesaj_var", "true" if islenecek_var else "false")
    print(f"[bilgi] {len(guncellemeler)} güncelleme, {len(mesajlar)} admin mesajı, "
          f"vadesi gelmiş görev: {gorev_vadesi_geldi}.", file=sys.stderr)


def cevapla(bot_token, admin_id):
    """Bekleyen admin mesaj(lar)ını Claude ile cevaplar (mail görevlerini
    state/gorevler.json'a kaydeder), state'i ilerletir, ardından vadesi
    gelmiş mail görevlerini üretip gönderir."""
    durum = _durum_oku()
    ud = durum.get("son_update_id")
    guncellemeler = _guncellemeleri_al(bot_token, ud + 1 if ud else None)
    mesajlar, son_id = _admin_mesajlarini_ayikla(guncellemeler, admin_id)

    if not mesajlar:
        print("[bilgi] Cevaplanacak yeni admin mesajı yok.", file=sys.stderr)
        if son_id is not None:
            _durum_yaz(son_id)
    else:
        simdi_str = datetime.now(IST).strftime("%d.%m.%Y %H:%M, %A")
        for soru in mesajlar:
            print(f"[bilgi] Soru cevaplanıyor: {soru[:80]!r}", file=sys.stderr)
            try:
                ham = _claude_calistir(SORU_PROMPTU.format(soru=soru, simdi=simdi_str),
                                       min_uzunluk=10)
                cevap, gorev = _gorev_ayikla(ham)
            except Exception as e:                   # noqa: BLE001
                cevap = f"⚠️ Bu soruyu cevaplarken bir hata oluştu: {html.escape(str(e)[:300])}"
                gorev = None

            if gorev:
                try:
                    hz = _hedef_zamani_ayristir(gorev["hedef_zaman"])
                    if hz <= datetime.now(IST):
                        raise ValueError("hedef zaman geçmişte")
                    gorevler = _gorevleri_oku()
                    gorevler.append({
                        "id": uuid.uuid4().hex[:8],
                        "hedef_zaman": hz.isoformat(),
                        "icerik_talebi": str(gorev["icerik_talebi"]).strip(),
                        "olusturulma_zamani": datetime.now(IST).isoformat(),
                        "durum": "bekliyor",
                    })
                    _gorevleri_yaz(gorevler)
                except (ValueError, KeyError) as e:
                    print(f"[uyarı] Görev zamanı geçersiz, kaydedilmedi: {e}", file=sys.stderr)
                    cevap += ("\n\n⚠️ Görevi zamanlarken bir sorun oldu, tarihi daha net "
                              "belirtir misin? (ör. \"25 Temmuz 09:00\")")

            for parca in mesaji_bol(cevap):
                telegram_gonder(bot_token, admin_id, parca)

        # Mesajları başarıyla cevapladıktan sonra state'i ilerlet — yarı yolda
        # hata olursa (ör. 3. soruda) offset ilerlemez, bir sonraki çalıştırma
        # aynı soruları (cevaplananlar dahil) tekrar dener; kabul edilebilir
        # çünkü tekrar cevap almak, hiç cevap almamaktan iyidir.
        if son_id is not None:
            _durum_yaz(son_id)

    _vadesi_gelmis_gorevleri_gonder(bot_token, admin_id)


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
