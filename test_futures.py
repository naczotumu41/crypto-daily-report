# -*- coding: utf-8 -*-
"""futures.py için basit birim testleri (ağ veya secret GEREKTİRMEZ)."""
import unittest

import futures


def _duz_mumlar(sayi, fiyat=100.0, genlik=1.0):
    """Yatay (trendsiz) mumlar üretir — her mum aynı fiyat civarında."""
    return [{"open": fiyat, "high": fiyat + genlik, "low": fiyat - genlik, "close": fiyat}
            for _ in range(sayi)]


def _yukselen_mumlar(sayi, baslangic=100.0, adim=1.0, genlik=0.5):
    """Her mumda `adim` kadar yükselen (net LONG trend) mumlar üretir."""
    mumlar = []
    fiyat = baslangic
    for _ in range(sayi):
        mumlar.append({"open": fiyat, "high": fiyat + genlik, "low": fiyat - genlik,
                       "close": fiyat + adim})
        fiyat += adim
    return mumlar


def _dusen_mumlar(sayi, baslangic=1000.0, adim=1.0, genlik=0.5):
    """Her mumda `adim` kadar düşen (net SHORT trend) mumlar üretir."""
    mumlar = []
    fiyat = baslangic
    for _ in range(sayi):
        mumlar.append({"open": fiyat, "high": fiyat + genlik, "low": fiyat - genlik,
                       "close": fiyat - adim})
        fiyat -= adim
    return mumlar


class AtrHesabi(unittest.TestCase):
    def test_yeterli_mum_yoksa_hata(self):
        with self.assertRaises(ValueError):
            futures._atr_hesapla(_duz_mumlar(5), periyot=14)

    def test_sabit_genlikli_mumlarda_atr_genlige_yakin(self):
        mumlar = _duz_mumlar(20, fiyat=100.0, genlik=2.0)
        atr = futures._atr_hesapla(mumlar, periyot=14)
        # Yatay mumlarda TR ~ high-low = 2*genlik = 4.0
        self.assertAlmostEqual(atr, 4.0, delta=0.01)


class EmaHesabi(unittest.TestCase):
    def test_yeterli_mum_yoksa_hata(self):
        with self.assertRaises(ValueError):
            futures._ema_hesapla([1, 2, 3], periyot=20)

    def test_sabit_fiyatta_ema_fiyata_esit(self):
        kapanislar = [100.0] * 60
        self.assertAlmostEqual(futures._ema_hesapla(kapanislar, 20), 100.0, delta=0.001)


class YonBelirleme(unittest.TestCase):
    def test_yukselen_trend_long_doner(self):
        mumlar = _yukselen_mumlar(60, baslangic=100.0, adim=1.0)
        kapanislar = [m["close"] for m in mumlar]
        self.assertEqual(futures._yon_belirle(kapanislar), "long")

    def test_dusen_trend_short_doner(self):
        mumlar = _dusen_mumlar(60, baslangic=1000.0, adim=1.0)
        kapanislar = [m["close"] for m in mumlar]
        self.assertEqual(futures._yon_belirle(kapanislar), "short")

    def test_yatay_trend_none_doner(self):
        mumlar = _duz_mumlar(60, fiyat=100.0)
        kapanislar = [m["close"] for m in mumlar]
        self.assertIsNone(futures._yon_belirle(kapanislar))


class SeviyeHesabi(unittest.TestCase):
    def test_net_trend_yoksa_yon_none(self):
        s = futures._seviyeleri_hesapla(_duz_mumlar(60, fiyat=100.0))
        self.assertIsNone(s["yon"])

    def test_long_sinyalde_stop_giristen_dusuk_hedef_yuksek(self):
        mumlar = _yukselen_mumlar(60, baslangic=100.0, adim=1.0)
        s = futures._seviyeleri_hesapla(mumlar)
        self.assertEqual(s["yon"], "long")
        self.assertLess(s["stop"], s["giris"])
        self.assertGreater(s["hedef"], s["giris"])

    def test_short_sinyalde_stop_giristen_yuksek_hedef_dusuk(self):
        mumlar = _dusen_mumlar(60, baslangic=1000.0, adim=1.0)
        s = futures._seviyeleri_hesapla(mumlar)
        self.assertEqual(s["yon"], "short")
        self.assertGreater(s["stop"], s["giris"])
        self.assertLess(s["hedef"], s["giris"])

    def test_hedef_direncle_sinirlanmiyor_tam_rr_hesabi_kullanilir(self):
        # Yükselen trendde pencere içindeki en yüksek high ("direnç") giriş
        # fiyatına çok yakın çıkar; hedef yine de TAM R:R mesafesinde olmalı
        # (önceki hatalı davranışta direnç hedefi neredeyse sıfıra indiriyordu).
        mumlar = _yukselen_mumlar(60, baslangic=50.0, adim=1.0, genlik=0.5)
        s = futures._seviyeleri_hesapla(mumlar)
        beklenen_hedef = s["giris"] + (s["giris"] - s["stop"]) * futures.RR_ORANI
        self.assertAlmostEqual(s["hedef"], beklenen_hedef, delta=0.01)

    def test_yol_ustunde_direnc_varsa_not_ekleniyor_ama_hedefi_degistirmiyor(self):
        mumlar = _yukselen_mumlar(45, baslangic=50.0, adim=1.0, genlik=0.5)
        s0 = futures._seviyeleri_hesapla(mumlar)
        self.assertEqual(s0["yon"], "long")
        self.assertIsNone(s0["yol_ustunde_seviye"])  # doğal veride direnç giriş altında kalıyor

        # Giriş ile hedef arasına yapay bir direnç enjekte et (ATR penceresi
        # dışında bir mumun high'ını değiştirerek — ATR/hedef etkilenmemeli).
        orta_nokta = (s0["giris"] + s0["hedef"]) / 2
        mumlar[-18]["high"] = orta_nokta
        s = futures._seviyeleri_hesapla(mumlar)

        self.assertEqual(s["yol_ustunde_seviye"], orta_nokta)
        self.assertAlmostEqual(s["hedef"], s0["hedef"], delta=0.01)  # hedef SINIRLANMADI

    def test_sermaye_riski_max_siniri_asmaz(self):
        # Çok yüksek volatilite (geniş ATR) olsa bile sermaye riski
        # MAX_SERMAYE_RISKI'ni (yüzde olarak) aşmamalı.
        mumlar = _yukselen_mumlar(60, baslangic=100.0, adim=1.0, genlik=20.0)
        s = futures._seviyeleri_hesapla(mumlar)
        self.assertLessEqual(s["sermaye_riski_yuzde"], futures.MAX_SERMAYE_RISKI * 100 + 0.01)

    def test_genis_atrda_stop_sinirlandi_true(self):
        # genlik büyük -> ATR mesafesi risk mesafesinden büyük -> sermaye limiti bağlayıcı
        mumlar = _yukselen_mumlar(60, baslangic=100.0, adim=1.0, genlik=20.0)
        s = futures._seviyeleri_hesapla(mumlar)
        self.assertTrue(s["stop_sinirlandi"])

    def test_dar_atrda_stop_sinirlandi_false(self):
        # genlik çok küçük -> ATR mesafesi risk mesafesinden küçük -> ATR bağlayıcı
        mumlar = _yukselen_mumlar(60, baslangic=100.0, adim=1.0, genlik=0.01)
        s = futures._seviyeleri_hesapla(mumlar)
        self.assertFalse(s["stop_sinirlandi"])


class DestekDirenc(unittest.TestCase):
    def test_min_max_dogru_bulunur(self):
        mumlar = [
            {"open": 100, "high": 105, "low": 95, "close": 100},
            {"open": 100, "high": 110, "low": 90, "close": 100},
            {"open": 100, "high": 102, "low": 98, "close": 100},
        ]
        destek, direnc = futures._destek_direnc(mumlar, pencere=3)
        self.assertEqual(destek, 90)
        self.assertEqual(direnc, 110)


class SinyalBlogu(unittest.TestCase):
    def test_trend_yoksa_atlandi_mesaji(self):
        blok = futures._sinyal_blogu("BTC", {"yon": None})
        self.assertIn("net trend yok", blok)

    def test_long_sinyalde_beklenen_alanlar_var(self):
        s = {"yon": "long", "giris": 65000.0, "stop": 63000.0, "hedef": 69000.0,
             "atr": 500.0, "sermaye_riski_yuzde": 9.2, "stop_sinirlandi": False,
             "yol_ustunde_seviye": None}
        blok = futures._sinyal_blogu("BTC", s)
        self.assertIn("LONG", blok)
        self.assertIn("$65,000", blok)
        self.assertIn("$63,000", blok)
        self.assertIn("$69,000", blok)
        self.assertNotIn("Yolda", blok)

    def test_yol_ustunde_seviye_varsa_uyari_notu_eklenir(self):
        s = {"yon": "long", "giris": 65000.0, "stop": 63000.0, "hedef": 69000.0,
             "atr": 500.0, "sermaye_riski_yuzde": 9.2, "stop_sinirlandi": False,
             "yol_ustunde_seviye": 67000.0}
        blok = futures._sinyal_blogu("BTC", s)
        self.assertIn("Yolda", blok)
        self.assertIn("$67,000", blok)
        self.assertIn("direnç", blok)


if __name__ == "__main__":
    unittest.main()
