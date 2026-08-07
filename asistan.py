#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kripto Asistan — Telegram'dan Soru Al, Claude ile Cevapla, Zamanlı Mail Gönder
================================================================================

report.py'nin günlük 08:00 raporundan AYRI, admin'in Telegram'da bota özelden
yazdığı soruları (haber, "neden düştü/battı", genel piyasa soruları)
cevaplayan, "şu gün şu saatte bana ... mail at" görevlerini zamanında yerine
getiren VE fiyat alarmlarını ("BTC 65000'i geçerse haber ver") izleyen ek
katman. GitHub Actions'ta ayrı bir workflow (asistan.yml) her birkaç
dakikada bir çalışır; yeni mesaj/vadesi gelmiş görev yoksa Claude'a hiç
dokunmadan çıkar — fiyat alarmı kontrolü de Claude gerektirmez, her
çalıştırmada ucuz tarafta (CoinGecko + Telegram) yapılır.

Her cevapta, kullanıcı hakkında öğrenilen kalıcı bilgiler (ilgilendiği
coin'ler, risk toleransı, tercih ettiği üslup vb.) state/hafiza.json'a
biriktirilir ve bir sonraki soruda tekrar Claude'a bağlam olarak verilir —
böylece asistan zamanla kullanıcıyı "tanır".

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
HAFIZA_YOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "hafiza.json")
ALARMLAR_YOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "alarmlar.json")
HAFIZA_UST_SINIR = 200  # notlar bunu aşarsa en eskiler düşürülür

# SORU PROMPTU — admin'in tek bir mesajına verilecek cevabı üretmek için
# headless Claude Code'a verilir. {soru}, {simdi} ve {hafiza} çalışma anında doldurulur.
SORU_PROMPTU = """Sen Telegram'da çalışan bir kripto/piyasa asistanısın. Kullanıcı (botun sahibi) sana özel olarak aşağıdaki mesajı yazdı.

BUGÜNÜN TARİHİ VE SAATİ (TSİ): {simdi}

KULLANICI HAKKINDA BİLDİKLERİN (varsa, cevabını buna göre kişiselleştir):
{hafiza}

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

DURUM C — Kullanıcı senden bir FİYAT ALARMI kurmanı istiyor (ör. "BTC 65000'i geçerse haber ver", "ETH 3000'in altına inerse söyle"):
  1. Kullanıcıya TEK CÜMLELİK kısa bir onay yaz (ör. "Tamam, BTC $65,000 üzerine çıkınca haber vereceğim.").
  2. Onay cümlesinin hemen altına, TAM bu formatta bir alarm bloğu ekle (Telegram'a GİTMEYECEK, sistem tarafından okunacak):
===ALARM===
{{"coingecko_id": "coingecko.com'daki DOĞRU api id'si, örn. bitcoin/ethereum/solana/binancecoin/ripple/aave/bittensor", "sembol": "gösterim sembolü, örn. BTC", "yon": "uzerinde" veya "altinda", "hedef_fiyat": sayı (USD, sadece rakam)}}
===ALARM-SON===
  - coingecko_id'yi mümkün olduğunca doğru ver; emin değilsen en olası CoinGecko id'sini kullan.
  - Bu durumda NORMAL cevap yazma, SADECE onay cümlesi + alarm bloğunu yaz.

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

GENEL KURAL — HAFIZA GÜNCELLEME (DURUM A/B/C fark etmez):
Bu mesajdan kullanıcı hakkında YENİ ve KALICI bir bilgi/tercih öğrendiysen
(ör. hangi coin'lerle ilgilendiği, risk toleransı, hangi tür raporu/üslubu
sevdiği, tekrar eden istekleri), cevabının/görev bloğunun ALTINA ayrı bir
blok olarak ekle (Telegram'a GİTMEYECEK, sistem tarafından okunacak):
===HAFIZA===
["yeni kalıcı not 1", "yeni kalıcı not 2"]
===HAFIZA-SON===
- Sadece GERÇEKTEN yeni bilgi varsa ekle; yukarıdaki BİLDİKLERİN listesinde
  zaten varsa veya önemsiz/geçiciyse bu bloğu HİÇ yazma.
- Notlar kısa, üçüncü tekil şahısla, tekrar kullanılabilir olsun
  (ör. "Uzun vadeli yatırımcı, kısa vadeli işlem önerisi istemiyor").

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
    temiz = re.sub(r"===GOREV===.*?===GOREV-SON===", "", cevap, flags=re.S).strip()
    return temiz, gorev


def _hafiza_notlarini_ayikla(cevap):
    """Claude'un ham cevabından ===HAFIZA===...===HAFIZA-SON=== bloğunu ayıklar.
    (temiz_cevap, yeni_notlar_listesi) döndürür."""
    m = re.search(r"===HAFIZA===\s*(.*?)\s*===HAFIZA-SON===", cevap, re.S)
    notlar = []
    if m:
        try:
            v = json.loads(m.group(1).strip())
            if isinstance(v, list):
                notlar = [str(x).strip() for x in v if str(x).strip()]
        except ValueError:
            notlar = []
    temiz = re.sub(r"===HAFIZA===.*?===HAFIZA-SON===", "", cevap, flags=re.S).strip()
    return temiz, notlar


def _alarm_ayikla(cevap):
    """Claude'un ham cevabından ===ALARM===...===ALARM-SON=== bloğunu ayıklar.
    (temiz_cevap, alarm_dict_or_None) döndürür."""
    m = re.search(r"===ALARM===\s*(.*?)\s*===ALARM-SON===", cevap, re.S)
    alarm = None
    if m:
        try:
            v = json.loads(m.group(1).strip())
            if (isinstance(v, dict) and v.get("coingecko_id") and v.get("yon") in ("uzerinde", "altinda")
                    and isinstance(v.get("hedef_fiyat"), (int, float)) and v["hedef_fiyat"] > 0):
                alarm = v
        except ValueError:
            alarm = None
    temiz = re.sub(r"===ALARM===.*?===ALARM-SON===", "", cevap, flags=re.S).strip()
    return temiz, alarm


# --------------------------------------------------------------------------- #
# Hafıza (kullanıcı hakkında kalıcı notlar) yönetimi
# --------------------------------------------------------------------------- #

def _hafizayi_oku():
    try:
        with open(HAFIZA_YOL, encoding="utf-8") as f:
            v = json.load(f).get("notlar", [])
        return v if isinstance(v, list) else []
    except (FileNotFoundError, ValueError, OSError):
        return []


def _hafizayi_yaz(notlar):
    os.makedirs(os.path.dirname(HAFIZA_YOL), exist_ok=True)
    with open(HAFIZA_YOL, "w", encoding="utf-8") as f:
        json.dump({"notlar": notlar}, f, ensure_ascii=False, indent=2)


def _hafizaya_ekle(yeni_notlar):
    """Yeni notları mevcut hafızaya ekler (tekrarları atlar, listeyi
    HAFIZA_UST_SINIR ile sınırlar — en eski notlar düşürülür)."""
    if not yeni_notlar:
        return
    notlar = _hafizayi_oku()
    for n in yeni_notlar:
        if n not in notlar:
            notlar.append(n)
    if len(notlar) > HAFIZA_UST_SINIR:
        notlar = notlar[-HAFIZA_UST_SINIR:]
    _hafizayi_yaz(notlar)


# --------------------------------------------------------------------------- #
# Fiyat alarmları yönetimi
# --------------------------------------------------------------------------- #

def _alarmlari_oku():
    try:
        with open(ALARMLAR_YOL, encoding="utf-8") as f:
            v = json.load(f).get("alarmlar", [])
        return v if isinstance(v, list) else []
    except (FileNotFoundError, ValueError, OSError):
        return []


def _alarmlari_yaz(alarmlar):
    os.makedirs(os.path.dirname(ALARMLAR_YOL), exist_ok=True)
    with open(ALARMLAR_YOL, "w", encoding="utf-8") as f:
        json.dump({"alarmlar": alarmlar}, f, ensure_ascii=False, indent=2)


def _fiyat_bicimle(v):
    return f"${v:,.2f}" if v < 100 else f"${v:,.0f}"


def _fiyatlari_cek(coingecko_idler):
    """Verilen CoinGecko id'leri için USD fiyatlarını tek istekte çeker.
    {coingecko_id: fiyat} döndürür; bulunamayan id'ler sözlükte yer almaz."""
    if not coingecko_idler:
        return {}
    veri = _get_json(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": ",".join(sorted(set(coingecko_idler))), "vs_currencies": "usd"},
    )
    return {cid: d["usd"] for cid, d in veri.items() if isinstance(d, dict) and "usd" in d}


def _alarmlari_kontrol_et_ve_bildir(bot_token, admin_id):
    """Aktif fiyat alarmlarını günceli fiyatlarla karşılaştırır; koşulu
    sağlayanları admin'e Telegram'dan bildirip 'tetiklendi' işaretler.
    Claude'a hiç dokunmaz — sadece CoinGecko + Telegram kullanır."""
    alarmlar = _alarmlari_oku()
    aktifler = [a for a in alarmlar if a.get("durum") == "aktif"]
    if not aktifler:
        return

    try:
        fiyatlar = _fiyatlari_cek([a.get("coingecko_id") for a in aktifler])
    except Exception as e:                               # noqa: BLE001
        print(f"[uyarı] Alarm fiyatları çekilemedi: {_gizle(e)}", file=sys.stderr)
        return

    degisti = False
    for a in aktifler:
        fiyat = fiyatlar.get(a.get("coingecko_id"))
        if fiyat is None:
            continue
        hedef = a.get("hedef_fiyat")
        tetiklendi = (a.get("yon") == "uzerinde" and fiyat >= hedef) or \
                     (a.get("yon") == "altinda" and fiyat <= hedef)
        if not tetiklendi:
            continue

        sembol = a.get("sembol") or a.get("coingecko_id", "")
        yon_metni = "üzerine çıktı" if a["yon"] == "uzerinde" else "altına indi"
        telegram_gonder(
            bot_token, admin_id,
            f"🔔 <b>Fiyat Alarmı!</b>\n{html.escape(sembol)} hedefin olan "
            f"{_fiyat_bicimle(hedef)} {yon_metni} — şu an: {_fiyat_bicimle(fiyat)}"
        )
        a["durum"] = "tetiklendi"
        a["tetiklenme_zamani"] = datetime.now(IST).isoformat()
        a["tetiklenme_fiyati"] = fiyat
        degisti = True
        print(f"[bilgi] Alarm tetiklendi: {sembol} {a['yon']} {hedef} (şu an {fiyat}).",
              file=sys.stderr)

    if degisti:
        _alarmlari_yaz(alarmlar)


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
    """Yeni admin mesajı YA DA vadesi gelmiş mail görevi var mı bakar (Claude'a
    dokunmadan) VE aktif fiyat alarmlarını kontrol edip tetiklenenleri
    Telegram'dan bildirir (bu da Claude gerektirmez — sadece CoinGecko)."""
    durum = _durum_oku()
    ud = durum.get("son_update_id")
    guncellemeler = _guncellemeleri_al(bot_token, ud + 1 if ud else None)
    mesajlar, _ = _admin_mesajlarini_ayikla(guncellemeler, admin_id)
    gorev_vadesi_geldi = _vadesi_gelmis_gorev_var_mi()
    islenecek_var = bool(mesajlar) or gorev_vadesi_geldi
    _github_output_yaz("mesaj_var", "true" if islenecek_var else "false")
    print(f"[bilgi] {len(guncellemeler)} güncelleme, {len(mesajlar)} admin mesajı, "
          f"vadesi gelmiş görev: {gorev_vadesi_geldi}.", file=sys.stderr)

    _alarmlari_kontrol_et_ve_bildir(bot_token, admin_id)


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
            notlar = _hafizayi_oku()
            hafiza_str = "\n".join(f"- {n}" for n in notlar) if notlar else "Henüz bir şey kaydedilmedi."
            try:
                ham = _claude_calistir(
                    SORU_PROMPTU.format(soru=soru, simdi=simdi_str, hafiza=hafiza_str),
                    min_uzunluk=10)
                cevap, gorev = _gorev_ayikla(ham)
                cevap, alarm = _alarm_ayikla(cevap)
                cevap, yeni_notlar = _hafiza_notlarini_ayikla(cevap)
                if yeni_notlar:
                    print(f"[bilgi] Hafızaya {len(yeni_notlar)} yeni not eklendi.", file=sys.stderr)
                    _hafizaya_ekle(yeni_notlar)
            except Exception as e:                   # noqa: BLE001
                cevap = f"⚠️ Bu soruyu cevaplarken bir hata oluştu: {html.escape(str(e)[:300])}"
                gorev = None
                alarm = None

            if alarm:
                alarmlar = _alarmlari_oku()
                alarmlar.append({
                    "id": uuid.uuid4().hex[:8],
                    "coingecko_id": str(alarm["coingecko_id"]).strip(),
                    "sembol": str(alarm.get("sembol") or alarm["coingecko_id"]).strip(),
                    "yon": alarm["yon"],
                    "hedef_fiyat": float(alarm["hedef_fiyat"]),
                    "olusturulma_zamani": datetime.now(IST).isoformat(),
                    "durum": "aktif",
                })
                _alarmlari_yaz(alarmlar)
                print(f"[bilgi] Yeni fiyat alarmı kaydedildi: {alarmlar[-1]}", file=sys.stderr)

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
