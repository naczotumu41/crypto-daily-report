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


class MesajAyiklama(unittest.TestCase):
    def test_sadece_admin_mesajlari_donuyor(self):
        guncellemeler = [
            _mesaj(1, ADMIN, "BTC neden düştü?"),
            _mesaj(2, BASKASI, "bu bota yazan başka biri"),
            _mesaj(3, ADMIN, "haberleri özetle"),
        ]
        mesajlar, son_id = asistan._admin_mesajlarini_ayikla(guncellemeler, ADMIN)
        self.assertEqual(mesajlar, ["BTC neden düştü?", "haberleri özetle"])
        self.assertEqual(son_id, 3)

    def test_admin_mesaji_yoksa_bos_liste_ama_son_id_ilerler(self):
        guncellemeler = [_mesaj(5, BASKASI, "merhaba")]
        mesajlar, son_id = asistan._admin_mesajlarini_ayikla(guncellemeler, ADMIN)
        self.assertEqual(mesajlar, [])
        self.assertEqual(son_id, 5)

    def test_guncelleme_yoksa_son_id_none(self):
        mesajlar, son_id = asistan._admin_mesajlarini_ayikla([], ADMIN)
        self.assertEqual(mesajlar, [])
        self.assertIsNone(son_id)

    def test_metinsiz_mesaj_atlanir(self):
        guncellemeler = [{"update_id": 9, "message": {"chat": {"id": ADMIN}}}]  # foto vb.
        mesajlar, son_id = asistan._admin_mesajlarini_ayikla(guncellemeler, ADMIN)
        self.assertEqual(mesajlar, [])
        self.assertEqual(son_id, 9)


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
