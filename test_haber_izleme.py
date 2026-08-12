# -*- coding: utf-8 -*-
"""haber_izleme.py için basit birim testleri (ağ veya secret GEREKTİRMEZ)."""
import unittest

import haber_izleme


class HaberAyiklama(unittest.TestCase):
    def test_gecerli_liste_ayiklanir(self):
        ham = (
            "===HABER===\n"
            '[{"coingecko_id": "hyperliquid", "sembol": "HYPE", "baslik": "X oldu", '
            '"ozet": "kısa özet", "kaynak_url": "https://example.com"}]\n'
            "===HABER-SON==="
        )
        haberler = haber_izleme._haber_ayikla(ham)
        self.assertEqual(len(haberler), 1)
        self.assertEqual(haberler[0]["coingecko_id"], "hyperliquid")
        self.assertEqual(haberler[0]["baslik"], "X oldu")

    def test_bos_liste_bos_liste_doner(self):
        ham = "===HABER===[]===HABER-SON==="
        self.assertEqual(haber_izleme._haber_ayikla(ham), [])

    def test_blok_yoksa_bos_liste_doner(self):
        self.assertEqual(haber_izleme._haber_ayikla("Sadece normal bir cevap."), [])

    def test_gecersiz_json_bos_liste_doner(self):
        ham = "===HABER===\nbu json degil\n===HABER-SON==="
        self.assertEqual(haber_izleme._haber_ayikla(ham), [])

    def test_coingecko_id_veya_baslik_eksik_ogeler_elenir(self):
        ham = (
            "===HABER===\n"
            '[{"coingecko_id": "hyperliquid", "baslik": "tam"}, '
            '{"sembol": "HYPE", "baslik": "id eksik"}, '
            '{"coingecko_id": "solana"}]\n'
            "===HABER-SON==="
        )
        haberler = haber_izleme._haber_ayikla(ham)
        self.assertEqual(len(haberler), 1)
        self.assertEqual(haberler[0]["coingecko_id"], "hyperliquid")


class HaberleriKontrolEtVeBildir(unittest.TestCase):
    def setUp(self):
        self._orig_oku = haber_izleme._izlenenleri_oku
        self._orig_yaz = haber_izleme._izlenenleri_yaz
        self._orig_claude = haber_izleme._claude_calistir
        self._orig_gonder = haber_izleme.telegram_gonder
        self._gonderilenler = []
        self._yazilan = None
        haber_izleme.telegram_gonder = lambda *a, **k: self._gonderilenler.append((a, k))

    def tearDown(self):
        haber_izleme._izlenenleri_oku = self._orig_oku
        haber_izleme._izlenenleri_yaz = self._orig_yaz
        haber_izleme._claude_calistir = self._orig_claude
        haber_izleme.telegram_gonder = self._orig_gonder

    def test_izlenen_coin_yoksa_claude_hic_cagrilmaz(self):
        haber_izleme._izlenenleri_oku = lambda: []
        haber_izleme._claude_calistir = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("izlenen coin yokken Claude çağrılmamalı"))
        haber_izleme.haberleri_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(self._gonderilenler, [])

    def test_yeni_haber_bulununca_bildirilir_ve_baslik_kaydedilir(self):
        haber_izleme._izlenenleri_oku = lambda: [
            {"id": "i1", "coingecko_id": "hyperliquid", "sembol": "HYPE",
             "chat_id": "555", "durum": "aktif", "bilinen_basliklar": []}
        ]
        haber_izleme._claude_calistir = lambda *a, **k: (
            '===HABER===\n'
            '[{"coingecko_id": "hyperliquid", "sembol": "HYPE", "baslik": "Yeni ortaklık", '
            '"ozet": "kısa özet", "kaynak_url": "https://example.com"}]\n'
            '===HABER-SON==='
        )
        haber_izleme._izlenenleri_yaz = lambda izlenenler: setattr(self, "_yazilan", izlenenler)
        haber_izleme.haberleri_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(len(self._gonderilenler), 1)
        (args, _kwargs) = self._gonderilenler[0]
        self.assertEqual(args[1], "555")  # izlemeyi kuran sohbete gitti, admin'e değil
        self.assertIn("Yeni ortaklık", args[2])
        self.assertIsNotNone(self._yazilan)
        self.assertIn("Yeni ortaklık", self._yazilan[0]["bilinen_basliklar"])

    def test_bilinen_baslik_tekrar_bildirilmez(self):
        haber_izleme._izlenenleri_oku = lambda: [
            {"id": "i1", "coingecko_id": "hyperliquid", "sembol": "HYPE",
             "chat_id": "555", "durum": "aktif", "bilinen_basliklar": ["Eski haber"]}
        ]
        haber_izleme._claude_calistir = lambda *a, **k: (
            '===HABER===\n'
            '[{"coingecko_id": "hyperliquid", "sembol": "HYPE", "baslik": "Eski haber", '
            '"ozet": "x", "kaynak_url": "https://example.com"}]\n'
            '===HABER-SON==='
        )
        haber_izleme._izlenenleri_yaz = lambda izlenenler: setattr(self, "_yazilan", izlenenler)
        haber_izleme.haberleri_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(self._gonderilenler, [])
        self.assertIsNone(self._yazilan)

    def test_bos_haber_listesinde_hicbir_sey_yazilmaz(self):
        haber_izleme._izlenenleri_oku = lambda: [
            {"id": "i1", "coingecko_id": "hyperliquid", "sembol": "HYPE",
             "chat_id": "555", "durum": "aktif", "bilinen_basliklar": []}
        ]
        haber_izleme._claude_calistir = lambda *a, **k: "===HABER===[]===HABER-SON==="
        haber_izleme._izlenenleri_yaz = lambda izlenenler: setattr(self, "_yazilan", izlenenler)
        haber_izleme.haberleri_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(self._gonderilenler, [])
        self.assertIsNone(self._yazilan)

    def test_iptal_edilmis_izlemeler_arastirilmaz(self):
        haber_izleme._izlenenleri_oku = lambda: [
            {"id": "i1", "coingecko_id": "hyperliquid", "sembol": "HYPE",
             "chat_id": "555", "durum": "iptal_edildi", "bilinen_basliklar": []}
        ]
        haber_izleme._claude_calistir = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("iptal edilmiş izleme için Claude çağrılmamalı"))
        haber_izleme.haberleri_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(self._gonderilenler, [])

    def test_claude_hata_verirse_sessizce_cikar(self):
        haber_izleme._izlenenleri_oku = lambda: [
            {"id": "i1", "coingecko_id": "hyperliquid", "sembol": "HYPE",
             "chat_id": "555", "durum": "aktif", "bilinen_basliklar": []}
        ]

        def _patlar(*a, **k):
            raise RuntimeError("claude cli hata")

        haber_izleme._claude_calistir = _patlar
        haber_izleme.haberleri_kontrol_et_ve_bildir("token", "admin")
        self.assertEqual(self._gonderilenler, [])


if __name__ == "__main__":
    unittest.main()
