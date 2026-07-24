# -*- coding: utf-8 -*-
"""asistan.py için basit birim testleri (ağ veya secret GEREKTİRMEZ)."""
import unittest

import asistan

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


if __name__ == "__main__":
    unittest.main()
