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

Aktif alarm/görevlerini "listele" diye sorabilir ya da birini "iptal et"
diyebilirsin — her iki durumda da aktif liste (id'leriyle) Claude'a bağlam
olarak veriliyor; iptal isteğinde Claude doğru id'yi seçip gizli bir
===IPTAL=== bloğu üretiyor, sistem o öğeyi "iptal_edildi" işaretliyor.

Portföyüne "0.5 BTC'm var" gibi miktar ekleyebilir/güncelleyebilirsin
(state/portfoy.json). "Portföyüm ne durumda" dediğinde Claude cevap YAZMAZ
(===PORTFOY_SORGU=== işareti üretir) — sistem CoinGecko'dan canlı fiyat
çekip toplam değeri + 24s değişimi Python'da hesaplar, uydurma sayı riski
olmasın diye.

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

Yalnızca TELEGRAM_ADMIN_CHAT_ID VE (varsa) TELEGRAM_GRUP_CHAT_ID'den gelen
mesajlar cevaplanır — botla konuşan rastgele biri Claude aboneliğini/mail
kotasını tüketmesin diye. Grup üyeleri de admin ile TAMAMEN AYNI yetkilere
sahiptir (alarm/mail/portföy dahil); paylaşılan TEK bir state üzerinde
çalışılır. Cevaplar, sorunun geldiği sohbete (admin özel ya da grup) gider.

Kullanım (ek):
  python asistan.py --sohbetleri-listele   Son güncellemelerdeki tüm
                                 sohbetleri (chat_id, tür, başlık) yazdırır;
                                 state'e DOKUNMAZ. Grubun chat_id'sini bulmak
                                 için kurulumda BİR KEZ kullanılır — önce
                                 gruba bir mesaj at, sonra bunu çalıştır.

Ortam değişkenleri:
  Mevcut (report.py ile paylaşılır): CLAUDE_CODE_OAUTH_TOKEN,
    TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID
  Grup desteği için YENİ (opsiyonel): TELEGRAM_GRUP_CHAT_ID
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
PORTFOY_YOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "portfoy.json")
HAFIZA_UST_SINIR = 200  # notlar bunu aşarsa en eskiler düşürülür

# SORU PROMPTU — admin'in tek bir mesajına verilecek cevabı üretmek için
# headless Claude Code'a verilir. {soru}, {simdi}, {hafiza}, {aktif_ozet} ve
# {portfoy} çalışma anında doldurulur.
SORU_PROMPTU = """Sen Telegram'da çalışan bir kripto/piyasa asistanısın. Kullanıcı (botun sahibi ya da güvendiği grubundaki biri — ikisi de aynı yetkiye sahip) sana aşağıdaki mesajı yazdı.

BUGÜNÜN TARİHİ VE SAATİ (TSİ): {simdi}

KULLANICI HAKKINDA BİLDİKLERİN (varsa, cevabını buna göre kişiselleştir):
{hafiza}

AKTİF ALARMLARIN VE BEKLEYEN GÖREVLERİN (id'ler dahil — 'listele' sorularında ve 'iptal et' isteklerinde bunu kullan):
{aktif_ozet}

PORTFÖYÜNDEKİ VARLIKLARIN (miktar; CANLI DEĞER YOK — güncel değer sorulursa DURUM F'yi kullan):
{portfoy}

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

DURUM D — Kullanıcı senden bir ALARMI ya da GÖREVİ (bekleyen maili) İPTAL etmeni istiyor (ör. "BTC alarmını iptal et", "yarınki maili iptal et"):
  1. Yukarıdaki AKTİF ALARMLARIN VE BEKLEYEN GÖREVLERİN listesinden hangi öğeyi kastettiğini (sembol/açıklamaya göre) bul.
  2. Net şekilde eşleştirebilirsen: kullanıcıya TEK CÜMLELİK kısa bir onay yaz (ör. "Tamam, BTC alarmını iptal ettim."), hemen altına TAM bu formatta bir iptal bloğu ekle (Telegram'a GİTMEYECEK):
===IPTAL===
{{"tur": "alarm" veya "gorev", "id": "listeden AYNEN kopyaladığın id"}}
===IPTAL-SON===
     Bu durumda NORMAL cevap yazma, SADECE onay cümlesi + iptal bloğunu yaz.
  3. Eşleştiremezsen (liste boş, ya da hangi öğe belli değilse): İPTAL bloğu YAZMA, DURUM B gibi kullanıcıdan netleştirme iste.

DURUM E — Kullanıcı PORTFÖYÜNE bir varlık ekliyor/güncelliyor/çıkarıyor (ör. "0.5 BTC'm var", "portföyüme 2 ETH ekle", "3000 HYPE aldım", "tüm SOL'umu sattım"):
  1. Kullanıcıya TEK CÜMLELİK kısa bir onay yaz (ör. "Tamam, portföyüne 0.5 BTC kaydettim.").
  2. Onay cümlesinin hemen altına, TAM bu formatta bir portföy bloğu ekle (Telegram'a GİTMEYECEK):
===PORTFOY===
{{"coingecko_id": "coingecko.com'daki DOĞRU api id'si", "sembol": "gösterim sembolü", "miktar": sayı (pozitif), "islem": "belirle" veya "ekle" veya "cikar"}}
===PORTFOY-SON===
  - "X kadar Y'im var / toplam Z" derse islem="belirle" (mevcut miktarı bu sayıya EŞİTLE).
  - "aldım / ekle" derse islem="ekle" (mevcut miktara EKLE).
  - "sattım / çıkar" derse islem="cikar" (mevcut miktardan DÜŞ); "hepsini/tamamını sattım" gibi miktar belirtilmeyen durumlarda, yukarıdaki PORTFÖYÜNDEKİ VARLIKLARIN listesindeki mevcut miktarı miktar alanına yaz.
  - Bu durumda NORMAL cevap yazma, SADECE onay cümlesi + portföy bloğunu yaz.

DURUM F — Kullanıcı portföyünün GÜNCEL DEĞERİNİ/DURUMUNU soruyor (ör. "portföyüm ne durumda", "portföy değerim ne kadar", "ne kadar kazandım"):
  NORMAL cevap YAZMA (canlı fiyata erişimin yok, uydurma sayı verme yasak). SADECE tam bu iki satırı yaz, başka HİÇBİR ŞEY ekleme:
===PORTFOY_SORGU===
===PORTFOY_SORGU-SON===

DURUM B — Diğer her şey (soru, haber talebi, "neden düştü/battı" gibi açıklama istekleri, aktif alarm/görevleri LİSTELEME istekleri, genel sohbet):
  Doğrudan cevap ver. Soru güncel bir olayla ilgiliyse WebSearch ile son gelişmeleri araştır; yalnızca doğruladığın bilgiyi yaz, uydurma, önemli iddialarda kaynak belirt. Kullanıcı aktif alarm/görevlerini sorarsa (ör. "alarmlarım neler", "bekleyen görevlerim var mı"), yukarıdaki AKTİF ALARMLARIN VE BEKLEYEN GÖREVLERİN bilgisini düzenli bir liste halinde sun (id'leri gösterme, sadece sembol/hedef/zaman gibi anlamlı bilgiyi).

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

GENEL KURAL — HAFIZA GÜNCELLEME (DURUM A/B/C/D/E/F fark etmez):
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


def _yetkili_mesajlari_ayikla(guncellemeler, yetkili_id_seti):
    """Güncellemeler arasından yetkili sohbetlerden (admin ve varsa grup)
    gelen metin mesajlarını çıkarır. ((chat_id, metin) çiftleri listesi,
    en_buyuk_update_id) döndürür — ikincisi None ise hiç güncelleme yok
    demektir. son_id, yetkisiz sohbetlerden gelenler dahil TÜM güncellemeler
    üzerinden hesaplanır (offset doğru ilerlesin diye)."""
    yetkili_id_seti = {str(x) for x in yetkili_id_seti}
    mesajlar = []
    son_id = None
    for g in guncellemeler:
        son_id = g["update_id"] if son_id is None else max(son_id, g["update_id"])
        msg = g.get("message") or {}
        metin = msg.get("text")
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        if metin and chat_id in yetkili_id_seti:
            mesajlar.append((chat_id, metin))
    return mesajlar, son_id


def sohbetleri_listele(bot_token):
    """Son güncellemelerdeki TÜM sohbetleri (id, tür, başlık, son mesaj)
    yazdırır; state'e dokunmaz, offset'i İLERLETMEZ. Kurulumda grup
    chat_id'sini bulmak için kullanılır."""
    durum = _durum_oku()
    ud = durum.get("son_update_id")
    guncellemeler = _guncellemeleri_al(bot_token, ud + 1 if ud else None)
    if not guncellemeler:
        print("[bilgi] Yeni güncelleme yok. Önce gruba (ya da bota özelden) bir mesaj at, "
              "sonra tekrar çalıştır.", file=sys.stderr)
        return
    gorulen = {}
    for g in guncellemeler:
        msg = g.get("message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None:
            continue
        gorulen[cid] = {
            "tur": chat.get("type"),
            "baslik": chat.get("title") or chat.get("username") or chat.get("first_name") or "",
            "son_mesaj": (msg.get("text") or "")[:50],
        }
    if not gorulen:
        print("[bilgi] Güncellemeler var ama içlerinde okunabilir bir sohbet yok.", file=sys.stderr)
        return
    for cid, bilgi in gorulen.items():
        print(f"chat_id={cid}  tur={bilgi['tur']}  baslik={bilgi['baslik']!r}  "
              f"son_mesaj={bilgi['son_mesaj']!r}")


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


def _iptal_ayikla(cevap):
    """Claude'un ham cevabından ===IPTAL===...===IPTAL-SON=== bloğunu ayıklar.
    (temiz_cevap, iptal_dict_or_None) döndürür."""
    m = re.search(r"===IPTAL===\s*(.*?)\s*===IPTAL-SON===", cevap, re.S)
    iptal = None
    if m:
        try:
            v = json.loads(m.group(1).strip())
            if isinstance(v, dict) and v.get("tur") in ("alarm", "gorev") and v.get("id"):
                iptal = v
        except ValueError:
            iptal = None
    temiz = re.sub(r"===IPTAL===.*?===IPTAL-SON===", "", cevap, flags=re.S).strip()
    return temiz, iptal


def _portfoy_ayikla(cevap):
    """Claude'un ham cevabından ===PORTFOY===...===PORTFOY-SON=== bloğunu ayıklar.
    (temiz_cevap, islem_dict_or_None) döndürür."""
    m = re.search(r"===PORTFOY===\s*(.*?)\s*===PORTFOY-SON===", cevap, re.S)
    islem = None
    if m:
        try:
            v = json.loads(m.group(1).strip())
            if (isinstance(v, dict) and v.get("coingecko_id")
                    and v.get("islem") in ("belirle", "ekle", "cikar")
                    and isinstance(v.get("miktar"), (int, float)) and v["miktar"] >= 0):
                islem = v
        except ValueError:
            islem = None
    temiz = re.sub(r"===PORTFOY===.*?===PORTFOY-SON===", "", cevap, flags=re.S).strip()
    return temiz, islem


def _portfoy_sorgu_ayikla(cevap):
    """===PORTFOY_SORGU===...===PORTFOY_SORGU-SON=== bloğunun varlığını
    kontrol eder. (temiz_cevap, sorgulandi_mi) döndürür."""
    sorgulandi = bool(re.search(r"===PORTFOY_SORGU===", cevap))
    temiz = re.sub(r"===PORTFOY_SORGU===.*?===PORTFOY_SORGU-SON===", "", cevap, flags=re.S).strip()
    return temiz, sorgulandi


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


def _aktif_ozet_olustur():
    """Aktif alarm ve bekleyen görevleri, Claude'a bağlam olarak verilecek
    kısa bir metin halinde özetler (id'ler dahil — 'listele'/'iptal et'
    isteklerinde kullanılır)."""
    alarmlar = [a for a in _alarmlari_oku() if a.get("durum") == "aktif"]
    gorevler = [g for g in _gorevleri_oku() if g.get("durum") == "bekliyor"]
    if not alarmlar and not gorevler:
        return "Şu an aktif alarm veya bekleyen görev yok."

    satirlar = []
    for a in alarmlar:
        yon_tr = "üzerine çıkarsa" if a.get("yon") == "uzerinde" else "altına inerse"
        satirlar.append(
            f"- [ALARM id={a.get('id')}] {a.get('sembol')} "
            f"{_fiyat_bicimle(a.get('hedef_fiyat', 0))} {yon_tr}"
        )
    for g in gorevler:
        satirlar.append(
            f"- [GOREV id={g.get('id')}] {g.get('hedef_zaman')} — "
            f"{str(g.get('icerik_talebi', ''))[:80]}"
        )
    return "\n".join(satirlar)


def _alarmlari_kontrol_et_ve_bildir(bot_token, admin_id):
    """Aktif fiyat alarmlarını günceli fiyatlarla karşılaştırır; koşulu
    sağlayanları alarmı KURAN sohbete (grup ise gruba, yoksa admin'e)
    Telegram'dan bildirip 'tetiklendi' işaretler. Claude'a hiç dokunmaz —
    sadece CoinGecko + Telegram kullanır."""
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
            bot_token, a.get("chat_id") or admin_id,
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


# --------------------------------------------------------------------------- #
# Portföy takibi (miktar bazlı, canlı değer sorgusu Python'da hesaplanır)
# --------------------------------------------------------------------------- #

def _portfoyu_oku():
    try:
        with open(PORTFOY_YOL, encoding="utf-8") as f:
            v = json.load(f).get("varliklar", [])
        return v if isinstance(v, list) else []
    except (FileNotFoundError, ValueError, OSError):
        return []


def _portfoyu_yaz(varliklar):
    os.makedirs(os.path.dirname(PORTFOY_YOL), exist_ok=True)
    with open(PORTFOY_YOL, "w", encoding="utf-8") as f:
        json.dump({"varliklar": varliklar}, f, ensure_ascii=False, indent=2)


def _portfoy_baglam_metni():
    """Portföy içeriğini (canlı fiyat OLMADAN) Claude'a bağlam olarak
    verilecek kısa bir metin halinde özetler."""
    varliklar = _portfoyu_oku()
    if not varliklar:
        return "Portföyünde henüz kayıtlı varlık yok."
    return "\n".join(f"- {v.get('sembol')}: {v.get('miktar')}" for v in varliklar)


def _portfoy_islemini_uygula(islem):
    """Bir PORTFOY işlemini (belirle/ekle/cikar) uygular ve kaydeder.
    Sonuç miktar 0 ya da altına inerse varlık listeden tamamen kaldırılır
    (tamamı satılmış demektir). Yeni miktarı döndürür."""
    varliklar = _portfoyu_oku()
    cid = str(islem["coingecko_id"]).strip()
    sembol = str(islem.get("sembol") or cid).strip()
    miktar = float(islem["miktar"])

    mevcut = next((v for v in varliklar if v.get("coingecko_id") == cid), None)
    mevcut_miktar = mevcut["miktar"] if mevcut else 0.0
    if islem["islem"] == "belirle":
        yeni_miktar = miktar
    elif islem["islem"] == "ekle":
        yeni_miktar = mevcut_miktar + miktar
    else:  # "cikar"
        yeni_miktar = mevcut_miktar - miktar

    if mevcut:
        varliklar.remove(mevcut)
    if yeni_miktar > 0:
        varliklar.append({"coingecko_id": cid, "sembol": sembol, "miktar": yeni_miktar})
    _portfoyu_yaz(varliklar)
    return yeni_miktar


def _portfoy_ozeti_olustur():
    """Portföydeki varlıkların CANLI fiyatlarını çekip toplam değeri ve 24s
    değişimi hesaplar. Sayılar CoinGecko'dan gelir, Claude'a hiç sorulmaz."""
    varliklar = _portfoyu_oku()
    if not varliklar:
        return ("Portföyünde henüz kayıtlı bir varlık yok. \"0.5 BTC'm var\" gibi "
                "yazarak ekleyebilirsin.")

    idler = [v["coingecko_id"] for v in varliklar]
    try:
        veri = _get_json(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(sorted(set(idler))), "vs_currencies": "usd",
                    "include_24hr_change": "true"},
        )
    except Exception as e:                                # noqa: BLE001
        return f"⚠️ Portföy değeri hesaplanamadı: {html.escape(str(e)[:200])}"

    satirlar = []
    toplam_deger = 0.0
    toplam_24s_onceki = 0.0
    for v in varliklar:
        d = veri.get(v["coingecko_id"])
        if not d or "usd" not in d:
            satirlar.append(f"{v['sembol']}: fiyat alınamadı")
            continue
        fiyat = d["usd"]
        degisim = d.get("usd_24h_change")
        deger = v["miktar"] * fiyat
        toplam_deger += deger
        toplam_24s_onceki += deger / (1 + degisim / 100) if degisim is not None else deger
        degisim_str = f"{degisim:+.1f}%" if degisim is not None else "n/a"
        satirlar.append(f"{v['sembol']}: {v['miktar']:g} × {_fiyat_bicimle(fiyat)} = "
                        f"{_fiyat_bicimle(deger)} ({degisim_str} 24s)")

    toplam_degisim_str = ""
    if toplam_24s_onceki > 0:
        toplam_degisim_yuzde = (toplam_deger - toplam_24s_onceki) / toplam_24s_onceki * 100
        toplam_degisim_str = f" ({toplam_degisim_yuzde:+.1f}% 24s)"

    return ("💼 <b>Portföyün</b>\n" + "\n".join(satirlar)
            + f"\n\n<b>Toplam: {_fiyat_bicimle(toplam_deger)}</b>{toplam_degisim_str}")


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
    her görevin durumunu günceller ve görevi KURAN sohbeti (grup ise gruba,
    yoksa admin'e) Telegram'dan bilgilendirir."""
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

        hedef_sohbet = g.get("chat_id") or admin_id
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
            telegram_gonder(bot_token, hedef_sohbet,
                            f"✅ Mail gönderildi: <i>{html.escape(icerik_talebi[:150])}</i>")
        except Exception as e:                       # noqa: BLE001
            g["durum"] = "hata"
            g["hata"] = str(e)[:300]
            print(f"[uyarı] Görev maili gönderilemedi: {_gizle(e)}", file=sys.stderr)
            telegram_gonder(bot_token, hedef_sohbet,
                            f"⚠️ Zamanlanmış mail gönderilemedi: {html.escape(str(e)[:300])}")
        degisti = True

    if degisti:
        _gorevleri_yaz(gorevler)


def kontrol_et(bot_token, admin_id, grup_id=None):
    """Yeni yetkili (admin ve varsa grup) mesajı YA DA vadesi gelmiş mail
    görevi var mı bakar (Claude'a dokunmadan) VE aktif fiyat alarmlarını
    kontrol edip tetiklenenleri Telegram'dan bildirir (bu da Claude
    gerektirmez — sadece CoinGecko)."""
    yetkili_id_seti = {admin_id} | ({grup_id} if grup_id else set())
    durum = _durum_oku()
    ud = durum.get("son_update_id")
    guncellemeler = _guncellemeleri_al(bot_token, ud + 1 if ud else None)
    mesajlar, _ = _yetkili_mesajlari_ayikla(guncellemeler, yetkili_id_seti)
    gorev_vadesi_geldi = _vadesi_gelmis_gorev_var_mi()
    islenecek_var = bool(mesajlar) or gorev_vadesi_geldi
    _github_output_yaz("mesaj_var", "true" if islenecek_var else "false")
    print(f"[bilgi] {len(guncellemeler)} güncelleme, {len(mesajlar)} yetkili mesajı, "
          f"vadesi gelmiş görev: {gorev_vadesi_geldi}.", file=sys.stderr)

    _alarmlari_kontrol_et_ve_bildir(bot_token, admin_id)


def cevapla(bot_token, admin_id, grup_id=None):
    """Bekleyen yetkili mesaj(lar)ını (admin ve varsa grup) Claude ile
    cevaplar (mail görevlerini state/gorevler.json'a kaydeder), state'i
    ilerletir, ardından vadesi gelmiş mail görevlerini üretip gönderir.
    Her cevap, sorunun geldiği sohbete gider — admin ve grup TAMAMEN AYNI
    yetkiye (alarm/mail/portföy dahil) sahiptir, paylaşılan tek state
    üzerinde çalışılır."""
    yetkili_id_seti = {admin_id} | ({grup_id} if grup_id else set())
    durum = _durum_oku()
    ud = durum.get("son_update_id")
    guncellemeler = _guncellemeleri_al(bot_token, ud + 1 if ud else None)
    mesajlar, son_id = _yetkili_mesajlari_ayikla(guncellemeler, yetkili_id_seti)

    if not mesajlar:
        print("[bilgi] Cevaplanacak yeni yetkili mesajı yok.", file=sys.stderr)
        if son_id is not None:
            _durum_yaz(son_id)
    else:
        simdi_str = datetime.now(IST).strftime("%d.%m.%Y %H:%M, %A")
        for chat_id, soru in mesajlar:
            print(f"[bilgi] ({chat_id}) Soru cevaplanıyor: {soru[:80]!r}", file=sys.stderr)
            notlar = _hafizayi_oku()
            hafiza_str = "\n".join(f"- {n}" for n in notlar) if notlar else "Henüz bir şey kaydedilmedi."
            aktif_ozet = _aktif_ozet_olustur()
            portfoy_str = _portfoy_baglam_metni()
            try:
                ham = _claude_calistir(
                    SORU_PROMPTU.format(soru=soru, simdi=simdi_str, hafiza=hafiza_str,
                                        aktif_ozet=aktif_ozet, portfoy=portfoy_str),
                    min_uzunluk=10)
                cevap, gorev = _gorev_ayikla(ham)
                cevap, alarm = _alarm_ayikla(cevap)
                cevap, iptal = _iptal_ayikla(cevap)
                cevap, portfoy_islem = _portfoy_ayikla(cevap)
                cevap, portfoy_sorgu = _portfoy_sorgu_ayikla(cevap)
                cevap, yeni_notlar = _hafiza_notlarini_ayikla(cevap)
                if yeni_notlar:
                    print(f"[bilgi] Hafızaya {len(yeni_notlar)} yeni not eklendi.", file=sys.stderr)
                    _hafizaya_ekle(yeni_notlar)
            except Exception as e:                   # noqa: BLE001
                cevap = f"⚠️ Bu soruyu cevaplarken bir hata oluştu: {html.escape(str(e)[:300])}"
                gorev = None
                alarm = None
                iptal = None
                portfoy_islem = None
                portfoy_sorgu = False

            if portfoy_sorgu:
                print("[bilgi] Portföy değeri sorgulandı, canlı hesaplanıyor...", file=sys.stderr)
                cevap = _portfoy_ozeti_olustur()

            if portfoy_islem:
                yeni_miktar = _portfoy_islemini_uygula(portfoy_islem)
                etiket = portfoy_islem.get("sembol") or portfoy_islem["coingecko_id"]
                print(f"[bilgi] Portföy güncellendi: {etiket} -> {yeni_miktar}", file=sys.stderr)

            if iptal:
                bulundu = False
                if iptal["tur"] == "alarm":
                    alarmlar = _alarmlari_oku()
                    for a in alarmlar:
                        if a.get("id") == iptal["id"] and a.get("durum") == "aktif":
                            a["durum"] = "iptal_edildi"
                            bulundu = True
                            break
                    if bulundu:
                        _alarmlari_yaz(alarmlar)
                else:
                    gorevler = _gorevleri_oku()
                    for g in gorevler:
                        if g.get("id") == iptal["id"] and g.get("durum") == "bekliyor":
                            g["durum"] = "iptal_edildi"
                            bulundu = True
                            break
                    if bulundu:
                        _gorevleri_yaz(gorevler)
                if bulundu:
                    print(f"[bilgi] İptal edildi: {iptal}", file=sys.stderr)
                else:
                    print(f"[uyarı] İptal edilecek öğe bulunamadı: {iptal}", file=sys.stderr)
                    cevap += ("\n\n⚠️ Bu öğeyi bulamadım, zaten iptal edilmiş ya da "
                              "tetiklenmiş/gönderilmiş olabilir.")

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
                    "chat_id": chat_id,
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
                        "chat_id": chat_id,
                    })
                    _gorevleri_yaz(gorevler)
                except (ValueError, KeyError) as e:
                    print(f"[uyarı] Görev zamanı geçersiz, kaydedilmedi: {e}", file=sys.stderr)
                    cevap += ("\n\n⚠️ Görevi zamanlarken bir sorun oldu, tarihi daha net "
                              "belirtir misin? (ör. \"25 Temmuz 09:00\")")

            for parca in mesaji_bol(cevap):
                telegram_gonder(bot_token, chat_id, parca)

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
    grup_id = os.environ.get("TELEGRAM_GRUP_CHAT_ID") or None

    if "--sohbetleri-listele" in sys.argv:
        if not bot_token:
            print("HATA: TELEGRAM_BOT_TOKEN tanımlı değil.", file=sys.stderr)
            sys.exit(1)
        sohbetleri_listele(bot_token)
        return

    if not bot_token or not admin_id:
        print("HATA: TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_CHAT_ID tanımlı değil.", file=sys.stderr)
        sys.exit(1)

    try:
        if "--kontrol" in sys.argv:
            kontrol_et(bot_token, admin_id, grup_id)
        else:
            cevapla(bot_token, admin_id, grup_id)
    except Exception as e:                           # noqa: BLE001
        print(f"[HATA] {_gizle(e)}", file=sys.stderr)
        admin_hata_bildir(_gizle(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
