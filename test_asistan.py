# -*- coding: utf-8 -*-
"""asistan.py için basit birim testleri (ağ veya secret GEREKTİRMEZ)."""
import unittest
from datetime import datetime, timedelta

import asistan
from report import IST

ADMIN = "111"
BASKASI = "222"


def _mesaj(update_id, chat_id, metin):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": metin}}


def _kanal_gonderisi(update_id, chat_id, metin):
    return {"update_id": update_id, "channel_post": {"chat": {"id": chat_id, "type": "channel"},
                                                       "text": metin}}


class MesajAyiklama(unittest.TestCase):
    def test_sadece_yetkili_mesajlari_donuyor(self):
        guncellemeler = [
            _mesaj(1, ADMIN, "BTC neden düştü?"),
            _mesaj(2, BASKASI, "bu bota yazan başka biri"),
            _mesaj(3, ADMIN, "haberleri özetle"),
        ]
        mesajlar, son_id = asistan._yetkili_mesajlari_ayikla(guncellemeler, {ADMIN})
        self.assertEqual(mesajlar, [(ADMIN, "BTC neden düştü?"), (ADMIN, "haberleri özetle")])
        self.assertEqual(son_id, 3)

    def test_grup_id_de_yetkili_sayilir(self):
        grup = "999"
        guncellemeler = [
            _mesaj(1, ADMIN, "admin sorusu"),
            _mesaj(2, grup, "grup sorusu"),
            _mesaj(3, BASKASI, "yabancı mesaj"),
        ]
        mesajlar, son_id = asistan._yetkili_mesajlari_ayikla(guncellemeler, {ADMIN, grup})
        self.assertEqual(mesajlar, [(ADMIN, "admin sorusu"), (grup, "grup sorusu")])
        self.assertEqual(son_id, 3)

    def test_yetkili_mesaji_yoksa_bos_liste_ama_son_id_ilerler(self):
        guncellemeler = [_mesaj(5, BASKASI, "merhaba")]
        mesajlar, son_id = asistan._yetkili_mesajlari_ayikla(guncellemeler, {ADMIN})
        self.assertEqual(mesajlar, [])
        self.assertEqual(son_id, 5)

    def test_guncelleme_yoksa_son_id_none(self):
        mesajlar, son_id = asistan._yetkili_mesajlari_ayikla([], {ADMIN})
        self.assertEqual(mesajlar, [])
        self.assertIsNone(son_id)

    def test_metinsiz_mesaj_atlanir(self):
        guncellemeler = [{"update_id": 9, "message": {"chat": {"id": ADMIN}}}]  # foto vb.
        mesajlar, son_id = asistan._yetkili_mesajlari_ayikla(guncellemeler, {ADMIN})
        self.assertEqual(mesajlar, [])
        self.assertEqual(son_id, 9)


class KanalEtiketAyiklama(unittest.TestCase):
    KANAL = "-100777"

    def test_kanalda_bot_etiketlenmis_gonderi_kabul_edilir(self):
        guncellemeler = [_kanal_gonderisi(1, self.KANAL, "@naczotumu_bot BTC ne durumda?")]
        mesajlar, son_id = asistan._yetkili_mesajlari_ayikla(
            guncellemeler, {ADMIN}, kanal_id=self.KANAL, bot_kullanici_adi="naczotumu_bot")
        self.assertEqual(mesajlar, [(self.KANAL, "@naczotumu_bot BTC ne durumda?")])
        self.assertEqual(son_id, 1)

    def test_kanalda_etiketsiz_gonderi_reddedilir(self):
        guncellemeler = [_kanal_gonderisi(1, self.KANAL, "BTC bugün yükseldi")]
        mesajlar, son_id = asistan._yetkili_mesajlari_ayikla(
            guncellemeler, {ADMIN}, kanal_id=self.KANAL, bot_kullanici_adi="naczotumu_bot")
        self.assertEqual(mesajlar, [])
        self.assertEqual(son_id, 1)  # offset yine de ilerler

    def test_etiket_kontrolu_buyuk_kucuk_harf_duyarsiz(self):
        guncellemeler = [_kanal_gonderisi(1, self.KANAL, "@NaczoTumu_Bot btc?")]
        mesajlar, _ = asistan._yetkili_mesajlari_ayikla(
            guncellemeler, {ADMIN}, kanal_id=self.KANAL, bot_kullanici_adi="naczotumu_bot")
        self.assertEqual(len(mesajlar), 1)

    def test_baska_kanaldan_etiketli_gonderi_de_reddedilir(self):
        guncellemeler = [_kanal_gonderisi(1, "-100999", "@naczotumu_bot selam")]
        mesajlar, _ = asistan._yetkili_mesajlari_ayikla(
            guncellemeler, {ADMIN}, kanal_id=self.KANAL, bot_kullanici_adi="naczotumu_bot")
        self.assertEqual(mesajlar, [])

    def test_kanal_id_yoksa_kanal_gonderisi_hic_kabul_edilmez(self):
        guncellemeler = [_kanal_gonderisi(1, self.KANAL, "@naczotumu_bot selam")]
        mesajlar, _ = asistan._yetkili_mesajlari_ayikla(guncellemeler, {ADMIN})
        self.assertEqual(mesajlar, [])

    def test_admin_grup_ve_kanal_ayni_anda_calisir(self):
        guncellemeler = [
            _mesaj(1, ADMIN, "admin sorusu"),
            _kanal_gonderisi(2, self.KANAL, "etiketsiz, atlanır"),
            _kanal_gonderisi(3, self.KANAL, "@naczotumu_bot etiketli soru"),
        ]
        mesajlar, son_id = asistan._yetkili_mesajlari_ayikla(
            guncellemeler, {ADMIN}, kanal_id=self.KANAL, bot_kullanici_adi="naczotumu_bot")
        self.assertEqual(mesajlar, [(ADMIN, "admin sorusu"), (self.KANAL, "@naczotumu_bot etiketli soru")])
        self.assertEqual(son_id, 3)


class GorevAyiklama(unittest.TestCase):
    def test_gorev_blogu_ayiklanir_ve_metinden_temizlenir(self):
        ham = (
            "Tamam, 25 Temmuz 2026 14:00 TSİ'de mail göndereceğim.\n"
            "===GOREV===\n"
            '{"hedef_zaman": "2026-07-25T14:00:00+03:00", '
            '"icerik_talebi": "BTC ve ETH güncel fiyatlarını özetle"}\n'
            "===GOREV-SON==="
        )
        temiz, gorev = asistan._gorev_ayikla(ham)
        self.assertEqual(temiz, "Tamam, 25 Temmuz 2026 14:00 TSİ'de mail göndereceğim.")
        self.assertEqual(gorev["hedef_zaman"], "2026-07-25T14:00:00+03:00")
        self.assertEqual(gorev["icerik_talebi"], "BTC ve ETH güncel fiyatlarını özetle")

    def test_gorev_blogu_yoksa_none_doner(self):
        temiz, gorev = asistan._gorev_ayikla("Sadece normal bir cevap.")
        self.assertEqual(temiz, "Sadece normal bir cevap.")
        self.assertIsNone(gorev)

    def test_bozuk_json_gorevi_yoksayar(self):
        ham = "Tamam.\n===GOREV===\nbu json değil\n===GOREV-SON==="
        temiz, gorev = asistan._gorev_ayikla(ham)
        self.assertEqual(temiz, "Tamam.")
        self.assertIsNone(gorev)

    def test_eksik_alanli_gorev_yoksayilir(self):
        ham = '===GOREV===\n{"hedef_zaman": "2026-07-25T14:00:00+03:00"}\n===GOREV-SON==='
        _, gorev = asistan._gorev_ayikla(ham)
        self.assertIsNone(gorev)


class HafizaAyiklama(unittest.TestCase):
    def test_hafiza_blogu_ayiklanir_ve_metinden_temizlenir(self):
        ham = (
            "BTC bugün %3 düştü.\n"
            "===HAFIZA===\n"
            '["Uzun vadeli yatırımcı, kısa vadeli işlem önerisi istemiyor"]\n'
            "===HAFIZA-SON==="
        )
        temiz, notlar = asistan._hafiza_notlarini_ayikla(ham)
        self.assertEqual(temiz, "BTC bugün %3 düştü.")
        self.assertEqual(notlar, ["Uzun vadeli yatırımcı, kısa vadeli işlem önerisi istemiyor"])

    def test_hafiza_blogu_yoksa_bos_liste_doner(self):
        temiz, notlar = asistan._hafiza_notlarini_ayikla("Sadece normal bir cevap.")
        self.assertEqual(temiz, "Sadece normal bir cevap.")
        self.assertEqual(notlar, [])

    def test_gorev_ve_hafiza_blogu_birlikte_temizlenir(self):
        ham = (
            "Tamam, yarın göndereceğim.\n"
            "===GOREV===\n"
            '{"hedef_zaman": "2026-07-25T09:00:00+03:00", "icerik_talebi": "BTC özeti"}\n'
            "===GOREV-SON===\n"
            "===HAFIZA===\n"
            '["Her sabah BTC özeti istiyor"]\n'
            "===HAFIZA-SON==="
        )
        temiz1, gorev = asistan._gorev_ayikla(ham)
        temiz2, notlar = asistan._hafiza_notlarini_ayikla(temiz1)
        self.assertEqual(temiz2, "Tamam, yarın göndereceğim.")
        self.assertEqual(gorev["icerik_talebi"], "BTC özeti")
        self.assertEqual(notlar, ["Her sabah BTC özeti istiyor"])


class HafizaKaydetme(unittest.TestCase):
    def setUp(self):
        self._orig_oku = asistan._hafizayi_oku
        self._orig_yaz = asistan._hafizayi_yaz
        self._yazilan = None

    def tearDown(self):
        asistan._hafizayi_oku = self._orig_oku
        asistan._hafizayi_yaz = self._orig_yaz

    def test_yeni_not_eklenir(self):
        asistan._hafizayi_oku = lambda: ["mevcut not"]
        asistan._hafizayi_yaz = lambda notlar: setattr(self, "_yazilan", notlar)
        asistan._hafizaya_ekle(["yeni not"])
        self.assertEqual(self._yazilan, ["mevcut not", "yeni not"])

    def test_tekrar_eden_not_eklenmez(self):
        asistan._hafizayi_oku = lambda: ["aynı not"]
        asistan._hafizayi_yaz = lambda notlar: setattr(self, "_yazilan", notlar)
        asistan._hafizaya_ekle(["aynı not"])
        self.assertEqual(self._yazilan, ["aynı not"])

    def test_bos_liste_yazmayi_tetiklemez(self):
        asistan._hafizayi_oku = lambda: ["mevcut not"]
        asistan._hafizayi_yaz = lambda notlar: setattr(self, "_yazilan", notlar)
        asistan._hafizaya_ekle([])
        self.assertIsNone(self._yazilan)

    def test_ust_sinir_asilinca_en_eskiler_dusurulur(self):
        eski = [f"not {i}" for i in range(asistan.HAFIZA_UST_SINIR)]
        asistan._hafizayi_oku = lambda: eski
        asistan._hafizayi_yaz = lambda notlar: setattr(self, "_yazilan", notlar)
        asistan._hafizaya_ekle(["en yeni not"])
        self.assertEqual(len(self._yazilan), asistan.HAFIZA_UST_SINIR)
        self.assertEqual(self._yazilan[-1], "en yeni not")
        self.assertNotIn("not 0", self._yazilan)


class AlarmAyiklama(unittest.TestCase):
    def test_alarm_blogu_ayiklanir_ve_metinden_temizlenir(self):
        ham = (
            "Tamam, BTC $65,000 üzerine çıkınca haber vereceğim.\n"
            "===ALARM===\n"
            '{"coingecko_id": "bitcoin", "sembol": "BTC", "yon": "uzerinde", "hedef_fiyat": 65000}\n'
            "===ALARM-SON==="
        )
        temiz, alarm = asistan._alarm_ayikla(ham)
        self.assertEqual(temiz, "Tamam, BTC $65,000 üzerine çıkınca haber vereceğim.")
        self.assertEqual(alarm["coingecko_id"], "bitcoin")
        self.assertEqual(alarm["yon"], "uzerinde")
        self.assertEqual(alarm["hedef_fiyat"], 65000)

    def test_alarm_blogu_yoksa_none_doner(self):
        temiz, alarm = asistan._alarm_ayikla("Sadece normal bir cevap.")
        self.assertEqual(temiz, "Sadece normal bir cevap.")
        self.assertIsNone(alarm)

    def test_gecersiz_yon_yoksayilir(self):
        ham = ('===ALARM===\n{"coingecko_id": "bitcoin", "yon": "yanlis", "hedef_fiyat": 100}\n'
               "===ALARM-SON===")
        _, alarm = asistan._alarm_ayikla(ham)
        self.assertIsNone(alarm)

    def test_negatif_hedef_fiyat_yoksayilir(self):
        ham = ('===ALARM===\n{"coingecko_id": "bitcoin", "yon": "uzerinde", "hedef_fiyat": -5}\n'
               "===ALARM-SON===")
        _, alarm = asistan._alarm_ayikla(ham)
        self.assertIsNone(alarm)

    def test_eksik_alanli_alarm_yoksayilir(self):
        ham = '===ALARM===\n{"coingecko_id": "bitcoin"}\n===ALARM-SON==='
        _, alarm = asistan._alarm_ayikla(ham)
        self.assertIsNone(alarm)

    def test_yuzde_alarm_blogu_kabul_edilir(self):
        ham = (
            "Tamam, BTC 1 saatte %5'ten fazla hareket ederse haber vereceğim.\n"
            "===ALARM===\n"
            '{"tur": "yuzde", "coingecko_id": "bitcoin", "sembol": "BTC", '
            '"yuzde_esik": 5, "pencere_dakika": 60}\n'
            "===ALARM-SON==="
        )
        temiz, alarm = asistan._alarm_ayikla(ham)
        self.assertEqual(temiz, "Tamam, BTC 1 saatte %5'ten fazla hareket ederse haber vereceğim.")
        self.assertEqual(alarm["tur"], "yuzde")
        self.assertEqual(alarm["yuzde_esik"], 5)
        self.assertEqual(alarm["pencere_dakika"], 60)

    def test_yuzde_alarm_esik_eksikse_yoksayilir(self):
        ham = ('===ALARM===\n{"tur": "yuzde", "coingecko_id": "bitcoin", "pencere_dakika": 60}\n'
               "===ALARM-SON===")
        _, alarm = asistan._alarm_ayikla(ham)
        self.assertIsNone(alarm)

    def test_yuzde_alarm_negatif_esik_yoksayilir(self):
        ham = ('===ALARM===\n{"tur": "yuzde", "coingecko_id": "bitcoin", "yuzde_esik": -5}\n'
               "===ALARM-SON===")
        _, alarm = asistan._alarm_ayikla(ham)
        self.assertIsNone(alarm)


class YuzdeDegisimiHesaplama(unittest.TestCase):
    def setUp(self):
        self._orig_get_json = asistan._get_json

    def tearDown(self):
        asistan._get_json = self._orig_get_json

    def test_esik_asan_degisim_dogru_hesaplanir(self):
        simdi_ms = 1_000_000_000_000
        asistan._get_json = lambda url, params=None: {"prices": [
            [simdi_ms - 60 * 60 * 1000, 100.0],   # 60 dk önce
            [simdi_ms - 30 * 60 * 1000, 103.0],   # 30 dk önce
            [simdi_ms, 106.0],                    # şimdi
        ]}
        sonuc = asistan._yuzde_degisimi_hesapla("bitcoin", 60)
        self.assertIsNotNone(sonuc)
        eski, guncel, yuzde = sonuc
        self.assertEqual(eski, 100.0)
        self.assertEqual(guncel, 106.0)
        self.assertAlmostEqual(yuzde, 6.0, places=3)

    def test_yetersiz_veri_none_doner(self):
        asistan._get_json = lambda url, params=None: {"prices": [[1, 100.0]]}
        self.assertIsNone(asistan._yuzde_degisimi_hesapla("bitcoin", 60))

    def test_pencereden_uzun_veri_en_eskiyi_kullanir(self):
        # pencere_dakika=1000 ama elimizdeki veri sadece son 60 dk'yı kapsıyor
        simdi_ms = 1_000_000_000_000
        asistan._get_json = lambda url, params=None: {"prices": [
            [simdi_ms - 60 * 60 * 1000, 100.0],
            [simdi_ms, 110.0],
        ]}
        sonuc = asistan._yuzde_degisimi_hesapla("bitcoin", 1000)
        self.assertEqual(sonuc[0], 100.0)  # en eski veri noktası kullanıldı


class YuzdeAlarmKontrolu(unittest.TestCase):
    def setUp(self):
        self._orig_oku = asistan._alarmlari_oku
        self._orig_yaz = asistan._alarmlari_yaz
        self._orig_hesapla = asistan._yuzde_degisimi_hesapla
        self._orig_gonder = asistan.telegram_gonder
        self._gonderilenler = []
        self._yazilan = None
        asistan.telegram_gonder = lambda *a, **k: self._gonderilenler.append((a, k))

    def tearDown(self):
        asistan._alarmlari_oku = self._orig_oku
        asistan._alarmlari_yaz = self._orig_yaz
        asistan._yuzde_degisimi_hesapla = self._orig_hesapla
        asistan.telegram_gonder = self._orig_gonder

    def test_esik_asilinca_tetiklenir_ama_aktif_kalir(self):
        asistan._alarmlari_oku = lambda: [
            {"id": "y1", "tur": "yuzde", "coingecko_id": "bitcoin", "sembol": "BTC",
             "yuzde_esik": 5, "pencere_dakika": 60, "durum": "aktif"}
        ]
        asistan._yuzde_degisimi_hesapla = lambda cid, dk: (100.0, 107.0, 7.0)
        asistan._alarmlari_yaz = lambda alarmlar: setattr(self, "_yazilan", alarmlar)
        asistan._alarmlari_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(len(self._gonderilenler), 1)
        self.assertEqual(self._yazilan[0]["durum"], "aktif")  # tek seferlik DEĞİL
        self.assertIn("son_tetiklenme_zamani", self._yazilan[0])

    def test_esik_altindaysa_tetiklenmez(self):
        asistan._alarmlari_oku = lambda: [
            {"id": "y1", "tur": "yuzde", "coingecko_id": "bitcoin", "sembol": "BTC",
             "yuzde_esik": 5, "pencere_dakika": 60, "durum": "aktif"}
        ]
        asistan._yuzde_degisimi_hesapla = lambda cid, dk: (100.0, 102.0, 2.0)
        asistan._alarmlari_yaz = lambda alarmlar: setattr(self, "_yazilan", alarmlar)
        asistan._alarmlari_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(self._gonderilenler, [])

    def test_cooldown_suresinde_tekrar_tetiklenmez(self):
        yakin_gecmis = (datetime.now(IST) - timedelta(minutes=5)).isoformat()
        asistan._alarmlari_oku = lambda: [
            {"id": "y1", "tur": "yuzde", "coingecko_id": "bitcoin", "sembol": "BTC",
             "yuzde_esik": 5, "pencere_dakika": 60, "durum": "aktif",
             "son_tetiklenme_zamani": yakin_gecmis}
        ]
        asistan._yuzde_degisimi_hesapla = lambda cid, dk: (_ for _ in ()).throw(
            AssertionError("cooldown içindeyken hesaplama yapılmamalı"))
        asistan._alarmlari_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(self._gonderilenler, [])

    def test_cooldown_gecince_tekrar_tetiklenebilir(self):
        uzak_gecmis = (datetime.now(IST) - timedelta(minutes=120)).isoformat()
        asistan._alarmlari_oku = lambda: [
            {"id": "y1", "tur": "yuzde", "coingecko_id": "bitcoin", "sembol": "BTC",
             "yuzde_esik": 5, "pencere_dakika": 60, "durum": "aktif",
             "son_tetiklenme_zamani": uzak_gecmis}
        ]
        asistan._yuzde_degisimi_hesapla = lambda cid, dk: (100.0, 108.0, 8.0)
        asistan._alarmlari_yaz = lambda alarmlar: setattr(self, "_yazilan", alarmlar)
        asistan._alarmlari_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(len(self._gonderilenler), 1)


class AlarmKontrolu(unittest.TestCase):
    def setUp(self):
        self._orig_oku = asistan._alarmlari_oku
        self._orig_yaz = asistan._alarmlari_yaz
        self._orig_fiyat = asistan._fiyatlari_cek
        self._orig_gonder = asistan.telegram_gonder
        self._gonderilenler = []
        self._yazilan = None
        asistan.telegram_gonder = lambda *a, **k: self._gonderilenler.append((a, k))

    def tearDown(self):
        asistan._alarmlari_oku = self._orig_oku
        asistan._alarmlari_yaz = self._orig_yaz
        asistan._fiyatlari_cek = self._orig_fiyat
        asistan.telegram_gonder = self._orig_gonder

    def test_hedef_ustunde_tetiklenir(self):
        asistan._alarmlari_oku = lambda: [
            {"coingecko_id": "bitcoin", "sembol": "BTC", "yon": "uzerinde",
             "hedef_fiyat": 65000, "durum": "aktif"}
        ]
        asistan._fiyatlari_cek = lambda idler: {"bitcoin": 65500}
        asistan._alarmlari_yaz = lambda alarmlar: setattr(self, "_yazilan", alarmlar)
        asistan._alarmlari_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(len(self._gonderilenler), 1)
        self.assertEqual(self._yazilan[0]["durum"], "tetiklendi")

    def test_hedefe_ulasmadiysa_tetiklenmez(self):
        asistan._alarmlari_oku = lambda: [
            {"coingecko_id": "bitcoin", "sembol": "BTC", "yon": "uzerinde",
             "hedef_fiyat": 65000, "durum": "aktif"}
        ]
        asistan._fiyatlari_cek = lambda idler: {"bitcoin": 64000}
        asistan._alarmlari_yaz = lambda alarmlar: setattr(self, "_yazilan", alarmlar)
        asistan._alarmlari_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(self._gonderilenler, [])
        self.assertIsNone(self._yazilan)

    def test_hedef_altinda_tetiklenir(self):
        asistan._alarmlari_oku = lambda: [
            {"coingecko_id": "ethereum", "sembol": "ETH", "yon": "altinda",
             "hedef_fiyat": 3000, "durum": "aktif"}
        ]
        asistan._fiyatlari_cek = lambda idler: {"ethereum": 2900}
        asistan._alarmlari_yaz = lambda alarmlar: setattr(self, "_yazilan", alarmlar)
        asistan._alarmlari_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(len(self._gonderilenler), 1)
        self.assertEqual(self._yazilan[0]["durum"], "tetiklendi")

    def test_tetiklenmis_alarm_tekrar_kontrol_edilmez(self):
        asistan._alarmlari_oku = lambda: [
            {"coingecko_id": "bitcoin", "sembol": "BTC", "yon": "uzerinde",
             "hedef_fiyat": 65000, "durum": "tetiklendi"}
        ]
        asistan._fiyatlari_cek = lambda idler: (_ for _ in ()).throw(
            AssertionError("aktif olmayan alarm için fiyat çekilmemeli"))
        asistan._alarmlari_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(self._gonderilenler, [])

    def test_aktif_alarm_yoksa_fiyat_hic_cekilmez(self):
        asistan._alarmlari_oku = lambda: []
        asistan._fiyatlari_cek = lambda idler: (_ for _ in ()).throw(
            AssertionError("alarm yokken fiyat çekilmemeli"))
        asistan._alarmlari_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(self._gonderilenler, [])


class IptalAyiklama(unittest.TestCase):
    def test_iptal_blogu_ayiklanir_ve_metinden_temizlenir(self):
        ham = (
            "Tamam, BTC alarmını iptal ettim.\n"
            "===IPTAL===\n"
            '{"tur": "alarm", "id": "a1b2c3d4"}\n'
            "===IPTAL-SON==="
        )
        temiz, iptal = asistan._iptal_ayikla(ham)
        self.assertEqual(temiz, "Tamam, BTC alarmını iptal ettim.")
        self.assertEqual(iptal["tur"], "alarm")
        self.assertEqual(iptal["id"], "a1b2c3d4")

    def test_iptal_blogu_yoksa_none_doner(self):
        temiz, iptal = asistan._iptal_ayikla("Sadece normal bir cevap.")
        self.assertEqual(temiz, "Sadece normal bir cevap.")
        self.assertIsNone(iptal)

    def test_gecersiz_tur_yoksayilir(self):
        ham = '===IPTAL===\n{"tur": "baska_bir_sey", "id": "x"}\n===IPTAL-SON==='
        _, iptal = asistan._iptal_ayikla(ham)
        self.assertIsNone(iptal)

    def test_id_eksikse_yoksayilir(self):
        ham = '===IPTAL===\n{"tur": "gorev"}\n===IPTAL-SON==='
        _, iptal = asistan._iptal_ayikla(ham)
        self.assertIsNone(iptal)

    def test_haber_izleme_turu_kabul_edilir(self):
        ham = '===IPTAL===\n{"tur": "haber_izleme", "id": "i1"}\n===IPTAL-SON==='
        _, iptal = asistan._iptal_ayikla(ham)
        self.assertEqual(iptal["tur"], "haber_izleme")
        self.assertEqual(iptal["id"], "i1")


class HaberIzlemeAyiklama(unittest.TestCase):
    def test_haber_izleme_blogu_ayiklanir_ve_metinden_temizlenir(self):
        ham = (
            "Tamam, HYPE ile ilgili önemli bir gelişme olursa haber vereceğim.\n"
            "===HABER_IZLEME===\n"
            '{"coingecko_id": "hyperliquid", "sembol": "HYPE"}\n'
            "===HABER_IZLEME-SON==="
        )
        temiz, izleme = asistan._haber_izleme_ayikla(ham)
        self.assertEqual(temiz, "Tamam, HYPE ile ilgili önemli bir gelişme olursa haber vereceğim.")
        self.assertEqual(izleme["coingecko_id"], "hyperliquid")
        self.assertEqual(izleme["sembol"], "HYPE")

    def test_haber_izleme_blogu_yoksa_none_doner(self):
        temiz, izleme = asistan._haber_izleme_ayikla("Sadece normal bir cevap.")
        self.assertEqual(temiz, "Sadece normal bir cevap.")
        self.assertIsNone(izleme)

    def test_coingecko_id_eksikse_yoksayilir(self):
        ham = '===HABER_IZLEME===\n{"sembol": "HYPE"}\n===HABER_IZLEME-SON==='
        _, izleme = asistan._haber_izleme_ayikla(ham)
        self.assertIsNone(izleme)

    def test_gecersiz_json_yoksayilir(self):
        ham = "===HABER_IZLEME===\nbu json degil\n===HABER_IZLEME-SON==="
        _, izleme = asistan._haber_izleme_ayikla(ham)
        self.assertIsNone(izleme)


class AktifOzetOlusturma(unittest.TestCase):
    def setUp(self):
        self._orig_alarm_oku = asistan._alarmlari_oku
        self._orig_gorev_oku = asistan._gorevleri_oku
        self._orig_izleme_oku = asistan._izlenenleri_oku
        asistan._izlenenleri_oku = lambda: []

    def tearDown(self):
        asistan._alarmlari_oku = self._orig_alarm_oku
        asistan._gorevleri_oku = self._orig_gorev_oku
        asistan._izlenenleri_oku = self._orig_izleme_oku

    def test_hicbir_sey_yoksa_bilgi_mesaji(self):
        asistan._alarmlari_oku = lambda: []
        asistan._gorevleri_oku = lambda: []
        self.assertEqual(
            asistan._aktif_ozet_olustur(),
            "Şu an aktif alarm, bekleyen görev ya da haber izlemesi yok.")

    def test_sadece_aktif_ve_bekleyenler_listelenir(self):
        asistan._alarmlari_oku = lambda: [
            {"id": "a1", "sembol": "BTC", "yon": "uzerinde", "hedef_fiyat": 65000, "durum": "aktif"},
            {"id": "a2", "sembol": "ETH", "yon": "altinda", "hedef_fiyat": 3000, "durum": "tetiklendi"},
        ]
        asistan._gorevleri_oku = lambda: [
            {"id": "g1", "hedef_zaman": "2026-07-25T09:00:00+03:00",
             "icerik_talebi": "BTC özeti", "durum": "bekliyor"},
            {"id": "g2", "hedef_zaman": "2026-07-20T09:00:00+03:00",
             "icerik_talebi": "eski görev", "durum": "gonderildi"},
        ]
        ozet = asistan._aktif_ozet_olustur()
        self.assertIn("id=a1", ozet)
        self.assertIn("id=g1", ozet)
        self.assertNotIn("id=a2", ozet)
        self.assertNotIn("id=g2", ozet)

    def test_sadece_aktif_haber_izlemeleri_listelenir(self):
        asistan._alarmlari_oku = lambda: []
        asistan._gorevleri_oku = lambda: []
        asistan._izlenenleri_oku = lambda: [
            {"id": "i1", "sembol": "HYPE", "coingecko_id": "hyperliquid", "durum": "aktif"},
            {"id": "i2", "sembol": "SOL", "coingecko_id": "solana", "durum": "iptal_edildi"},
        ]
        ozet = asistan._aktif_ozet_olustur()
        self.assertIn("id=i1", ozet)
        self.assertIn("HYPE", ozet)
        self.assertNotIn("id=i2", ozet)


class PortfoyAyiklama(unittest.TestCase):
    def test_portfoy_blogu_ayiklanir_ve_metinden_temizlenir(self):
        ham = (
            "Tamam, portföyüne 0.5 BTC kaydettim.\n"
            "===PORTFOY===\n"
            '{"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 0.5, "islem": "belirle"}\n'
            "===PORTFOY-SON==="
        )
        temiz, islem = asistan._portfoy_ayikla(ham)
        self.assertEqual(temiz, "Tamam, portföyüne 0.5 BTC kaydettim.")
        self.assertEqual(islem["coingecko_id"], "bitcoin")
        self.assertEqual(islem["islem"], "belirle")
        self.assertEqual(islem["miktar"], 0.5)

    def test_portfoy_blogu_yoksa_none_doner(self):
        temiz, islem = asistan._portfoy_ayikla("Sadece normal bir cevap.")
        self.assertEqual(temiz, "Sadece normal bir cevap.")
        self.assertIsNone(islem)

    def test_gecersiz_islem_yoksayilir(self):
        ham = ('===PORTFOY===\n{"coingecko_id": "bitcoin", "islem": "yanlis", "miktar": 1}\n'
               "===PORTFOY-SON===")
        _, islem = asistan._portfoy_ayikla(ham)
        self.assertIsNone(islem)

    def test_negatif_miktar_yoksayilir(self):
        ham = ('===PORTFOY===\n{"coingecko_id": "bitcoin", "islem": "ekle", "miktar": -1}\n'
               "===PORTFOY-SON===")
        _, islem = asistan._portfoy_ayikla(ham)
        self.assertIsNone(islem)

    def test_portfoy_sorgu_blogu_algilanir_ve_temizlenir(self):
        ham = "===PORTFOY_SORGU===\n===PORTFOY_SORGU-SON==="
        temiz, sorgulandi = asistan._portfoy_sorgu_ayikla(ham)
        self.assertEqual(temiz, "")
        self.assertTrue(sorgulandi)

    def test_portfoy_sorgu_yoksa_false_doner(self):
        temiz, sorgulandi = asistan._portfoy_sorgu_ayikla("Sadece normal bir cevap.")
        self.assertEqual(temiz, "Sadece normal bir cevap.")
        self.assertFalse(sorgulandi)


class PortfoyIslemUygulama(unittest.TestCase):
    def setUp(self):
        self._orig_oku = asistan._portfoyu_oku
        self._orig_yaz = asistan._portfoyu_yaz
        self._yazilan = None

    def tearDown(self):
        asistan._portfoyu_oku = self._orig_oku
        asistan._portfoyu_yaz = self._orig_yaz

    def test_belirle_yeni_varlik_ekler(self):
        asistan._portfoyu_oku = lambda: []
        asistan._portfoyu_yaz = lambda v: setattr(self, "_yazilan", v)
        sonuc = asistan._portfoy_islemini_uygula(
            {"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 0.5, "islem": "belirle"})
        self.assertEqual(sonuc, 0.5)
        self.assertEqual(self._yazilan, [{"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 0.5}])

    def test_belirle_mevcut_varligin_ustune_yazar(self):
        asistan._portfoyu_oku = lambda: [{"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 1.0}]
        asistan._portfoyu_yaz = lambda v: setattr(self, "_yazilan", v)
        asistan._portfoy_islemini_uygula(
            {"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 2.0, "islem": "belirle"})
        self.assertEqual(self._yazilan, [{"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 2.0}])

    def test_ekle_mevcut_miktara_ekler(self):
        asistan._portfoyu_oku = lambda: [{"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 1.0}]
        asistan._portfoyu_yaz = lambda v: setattr(self, "_yazilan", v)
        sonuc = asistan._portfoy_islemini_uygula(
            {"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 0.5, "islem": "ekle"})
        self.assertEqual(sonuc, 1.5)

    def test_cikar_miktardan_duser(self):
        asistan._portfoyu_oku = lambda: [{"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 1.0}]
        asistan._portfoyu_yaz = lambda v: setattr(self, "_yazilan", v)
        sonuc = asistan._portfoy_islemini_uygula(
            {"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 0.4, "islem": "cikar"})
        self.assertEqual(sonuc, 0.6)

    def test_cikar_tamamini_satinca_varlik_kaldirilir(self):
        asistan._portfoyu_oku = lambda: [{"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 1.0}]
        asistan._portfoyu_yaz = lambda v: setattr(self, "_yazilan", v)
        sonuc = asistan._portfoy_islemini_uygula(
            {"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 1.0, "islem": "cikar"})
        self.assertEqual(sonuc, 0)
        self.assertEqual(self._yazilan, [])


class PortfoyBaglamMetni(unittest.TestCase):
    def setUp(self):
        self._orig_oku = asistan._portfoyu_oku

    def tearDown(self):
        asistan._portfoyu_oku = self._orig_oku

    def test_bos_portfoyde_bilgi_mesaji(self):
        asistan._portfoyu_oku = lambda: []
        self.assertEqual(asistan._portfoy_baglam_metni(), "Portföyünde henüz kayıtlı varlık yok.")

    def test_varliklar_listelenir(self):
        asistan._portfoyu_oku = lambda: [{"coingecko_id": "bitcoin", "sembol": "BTC", "miktar": 0.5}]
        self.assertIn("BTC: 0.5", asistan._portfoy_baglam_metni())


class HedefZamanAyristirma(unittest.TestCase):
    def test_ofsetli_zaman_aynen_kullanilir(self):
        hz = asistan._hedef_zamani_ayristir("2026-07-25T14:00:00+03:00")
        self.assertEqual(hz.utcoffset().total_seconds(), 3 * 3600)

    def test_ofsetsiz_zamana_tsi_atanir(self):
        hz = asistan._hedef_zamani_ayristir("2026-07-25T14:00:00")
        self.assertEqual(hz.tzinfo, IST)


class VadesiGelmisGorevKontrolu(unittest.TestCase):
    def setUp(self):
        self._orig_oku = asistan._gorevleri_oku

    def tearDown(self):
        asistan._gorevleri_oku = self._orig_oku

    def test_gecmis_bekleyen_gorev_vadesi_gelmis_sayilir(self):
        gecmis = (datetime.now(IST) - timedelta(minutes=5)).isoformat()
        asistan._gorevleri_oku = lambda: [
            {"durum": "bekliyor", "hedef_zaman": gecmis}
        ]
        self.assertTrue(asistan._vadesi_gelmis_gorev_var_mi())

    def test_gelecekteki_gorev_vadesi_gelmemis_sayilir(self):
        gelecek = (datetime.now(IST) + timedelta(hours=1)).isoformat()
        asistan._gorevleri_oku = lambda: [
            {"durum": "bekliyor", "hedef_zaman": gelecek}
        ]
        self.assertFalse(asistan._vadesi_gelmis_gorev_var_mi())

    def test_gonderilmis_gorev_sayilmaz(self):
        gecmis = (datetime.now(IST) - timedelta(minutes=5)).isoformat()
        asistan._gorevleri_oku = lambda: [
            {"durum": "gonderildi", "hedef_zaman": gecmis}
        ]
        self.assertFalse(asistan._vadesi_gelmis_gorev_var_mi())


if __name__ == "__main__":
    unittest.main()
