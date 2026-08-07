# 🌅 Günaydın Kripto — Telegram Sabah Botu

> Her sabah **08:00'de**, sen uyanmadan, piyasayı **1 dakikada** anlatan arkadaşın.

Bu bir "otomatik rapor" değil. Uyandığında tam ihtiyacın olan bilgiyi — gereksiz hiçbir şey olmadan — Telegram kanalına koyan bir sabah rutini. Bilgisayarın **kapalıyken de çalışır** (GitHub'ın ücretsiz sunucularında koşar).

> ⚠️ **Yatırım tavsiyesi değildir.** Bilgilendirme amaçlıdır; al/sat önerisi vermez.

---

## ✨ Her sabah kanalına ne düşer?

- 📊 **Kart + 60 saniyelik brief** (tek mesaj) — piyasa havası, BTC/ETH, **"piyasa neden hareket etti"**, günün kritik saatleri ve ana risk. Bir bakışta, bir dakikada okunur. Kartı **Instagram/WhatsApp'ta paylaşabilirsin**.
- 🎙️ **~45 saniyelik sesli özet** — yolda ya da hazırlanırken dinle. Ücretsiz Türkçe doğal ses.
- ⏮️ **Dünden hesap** — dün "dikkat" dediğimiz olayların bugünkü **sonucunu** gösterir. Sistem dünü hatırlar.
- 📄 **Detay** — piyasa tablosu, günün en önemli 3 gelişmesi (kaynak linkli), Türkiye mevzuatı, bugünün ekonomik takvimi (TSİ), riskler.

**Sayılar uydurma değildir:** Fiyat, dominans, hacim ve Fear & Greed doğrudan ücretsiz API'lerden gelir — yapay zekâya asla uydurtulmaz. Yalnızca haber/analiz kısmını Claude, canlı web araması yaparak yazar.

---

## 💬 Soru-cevap asistanı + zamanlı mail + fiyat alarmları (yeni)

Günlük rapora ek olarak, bota **özelden** yazdığın sorulara da cevap verir: haberleri sorabilir, "bu kripto neden düştü/battı" diye sorabilir, genel piyasa sorularını sorabilirsin. Cevaplar Claude'un canlı web araması yaparak ürettiği metinlerdir; net bir alım/satım fiyat seviyesi istersen bunu şu an hesaplayamadığını söyler (uydurma sayı vermez) — bu, ayrıca geliştirilmekte olan bir sonraki özellik.

Ayrıca **"25 Temmuz saat 09:00'da bana BTC durumunu mail at"** gibi zamanlı görevler verebilirsin: bot "tamam, o saatte göndereceğim" diye onaylar, tam vaktinde (en fazla ~5 dk gecikmeyle) o anki güncel bilgiyle bir mail hazırlayıp gönderir ve Telegram'dan "mail gönderildi" diye haber verir. Görev tek seferliktir (tekrarlayan/periyodik görev desteklenmiyor).

- Yalnızca **admin** (senin özel sohbetin, `TELEGRAM_ADMIN_CHAT_ID`) sorduğunda/görev verdiğinde işlem yapılır; kanaldaki ya da botla konuşan başka biri Claude/mail kotasını tüketemez.
- `.github/workflows/asistan.yml` her 5 dakikada bir "yeni mesaj / vadesi gelmiş görev var mı" diye bakar (ücretsiz, hafif bir adım); bir şey varsa Claude Code'u çalıştırıp cevabı/maili üretir. Yani hem cevaplar hem mailler anlık değil, en fazla ~5 dakika gecikebilir.
- Botuna Telegram'dan özel mesaj at, birkaç dakika içinde cevap gelir.
- **Mail özelliği için 3 EK secret gerekir** (Gmail SMTP, tamamen ücretsiz) — aşağıdaki secret tablosuna bak. Bu 3'ü eklemezsen soru-cevap kısmı yine çalışır, sadece mail görevi verdiğinde hata bildirimi alırsın.

**Ayrıca seni zamanla "tanır":** Her cevaptan sonra, hakkında öğrendiği kalıcı bir bilgi/tercih varsa (ör. hangi coin'lerle ilgilendiğin, risk toleransın, sevdiğin rapor üslubu) bunu `state/hafiza.json`'a sessizce kaydeder ve bir sonraki soruda bunu bağlam olarak kullanır — bu ekstra secret ya da kurulum gerektirmez, otomatik işler.

**Fiyat alarmları:** **"BTC 68.000'i geçerse haber ver"** ya da **"ETH 3.000'in altına inerse söyle"** gibi yaz, bot onaylar ve arka planda izlemeye başlar. Bu kontrol Claude gerektirmez — sadece CoinGecko'dan anlık fiyat çeker — bu yüzden `.github/workflows/asistan.yml`'nin *her* çalıştırmasında (Claude Code hiç kurulmadan) kontrol edilir; alarm tetiklenince Telegram'dan anında bildirim gelir ve alarm otomatik kapanır (tek seferlik, tekrar tetiklenmez). `state/alarmlar.json`'da tutulur, ekstra secret gerekmez.

---

## 🔧 Perde arkası (3 adım)

1. **Sabit veriler** — CoinGecko + Alternative.me'den fiyatlar, dominans, hacim, Fear & Greed (LLM yok → halüsinasyon yok).
2. **Haber & analiz** — Headless Claude Code web araması yaparak son 24 saati Türkçe yazar. (Claude aboneliğinden düşer, **ek API ücreti yok**.)
3. **Gönderim** — Telegram'a kart + brief + ses + detay olarak, saniyesi saniyesine **08:00'de**.

Kart görseli (Pillow) ve sesli özet (edge-tts) de dahil **her şey ücretsiz** — hiçbir ödemeli servis yok.

---

## 🤖 En kolay kurulum: bırak Claude Code yapsın

Teknik bilgin yoksa hiç uğraşma:

1. Bu repoyu indir (yeşil **Code → Download ZIP**) veya klonla.
2. Klasörde **[Claude Code](https://claude.com/claude-code)**'u aç.
3. Şunu yaz: **"Bu repoyu kurmak istiyorum, beni baştan sona yönlendir."**

Claude Code, repodaki `CLAUDE.md` talimatlarını okuyup seni adım adım kurar: Telegram botu, kanal, chat_id bulma, token'lar ve GitHub'ı **senin yerine** halleder. Sana kalan sadece birkaç token yapıştırmak ve bir kez tarayıcı girişi.

---

## ⚡ Hızlı kurulum (manuel)

Zor kısımları (chat_id bulma, test, GitHub reposu + secret'lar) **`setup.py` sihirbazı** yapıyor. Sana kalan:

### 1) Telegram botu oluştur
**@BotFather** → `/newbot` → isim ver → **token'ı kopyala** (`123456:ABC-...`).

### 2) Kanalı hazırla
- Raporun gideceği **kanalı** oluştur.
- Kanal → **Yöneticiler → Yönetici Ekle** → botunu ekle ("Mesaj Gönderme" yetkisi yeter).
- Kanala **bir mesaj at** (bot kanalı görebilsin) ve **kendi botuna** bir kez **/start** yaz.

### 3) Claude token'ı üret
```bash
claude setup-token
```
Çıkan token'ı kopyala. (Pro/Max aboneliği yeter, ek ücret yok. Token ~1 yıl geçerli.)

### 4) Sihirbazı çalıştır — gerisi otomatik
```bash
pip install -r requirements.txt
python setup.py
```
Sihirbaz senden **iki token** (bot + Claude) ister, kalan her şeyi kendi yapar:
- ✅ Kanalın ve senin chat_id'ni **otomatik bulur**
- ✅ **Test mesajı** atıp çalıştığını kanıtlar
- ✅ `.env` dosyasını yazar
- ✅ **GitHub girişini başlatır** + repoyu oluşturur + dosyaları yükler + **4 secret'ı ekler**
- ✅ **Sızıntı taraması** yapıp repoyu **public** oluşturur — saatinde teslim için gerekli (aşağıda anlatılıyor). Tarama temiz değilse otomatik **private**'a düşer ve seni uyarır.

**Bitti.** Artık her sabah 08:00'de kanala tam rapor gelir. 🎉

---

## Test etme

**Yerel:**
```bash
python report.py --test    # rapor kanala DEĞİL, sadece sana (admin) gider
```

**GitHub üzerinden:** Repo → **Actions → Günlük Kripto Raporu → Run workflow** → **mode**: `test` (sadece sana), `both` (sana + kanala) ya da `normal` (kanala). `deliver_at` ile belirli bir saate de gönderebilirsin.

---

## Manuel GitHub kurulumu (sihirbaz kullanmazsan)

1. [github.com](https://github.com)'da yeni repo oluştur.
2. Dosyaları yükle (`git add . && git commit -m "kurulum" && git push`).
3. Repo → **Settings → Secrets and variables → Actions**. Şu 4 secret'ı ekle:

   | Secret | Değer |
   |---|---|
   | `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` çıktısı |
   | `TELEGRAM_BOT_TOKEN` | BotFather token'ı |
   | `TELEGRAM_CHAT_ID` | Kanal id (`@kanal` veya `-100...`) |
   | `TELEGRAM_ADMIN_CHAT_ID` | Senin özel chat id'in |

   **Zamanlı mail özelliğini de istiyorsan** (opsiyonel) şu 3 secret'ı da ekle:

   | Secret | Değer |
   |---|---|
   | `SMTP_GMAIL_ADRES` | Gönderici Gmail adresin |
   | `SMTP_UYGULAMA_SIFRESI` | Google hesabında 2 adımlı doğrulamayı açtıktan sonra [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)'tan üretilen 16 haneli uygulama şifresi (normal Gmail şifren DEĞİL) |
   | `ALICI_EMAIL` | Maillerin gideceği adres |

---

## Sık sorulanlar

**Rapor tam 08:00'de mi gelir?** Evet — ve bunun için özel bir düzenek var.

GitHub'ın ücretsiz zamanlayıcısı "best-effort"tur: alarmı bazen dakikalarca, nadiren **saatlerce** geç çalar. Tek alarma güvenmek bu yüzden yetmiyor. Çözüm iki katmanlı:

1. **Beş nöbetçi.** Workflow 04:07 / 07:10 / 07:25 / 07:40 / 07:55 TSİ'de ayrı ayrı uyanmayı dener. Hangisi vaktinde uyanırsa **tam 08:00'e kadar bekler**, öyle gönderir (`DELIVER_AT_TR`).
2. **Çift rapor koruması.** Rapor gidince `state/takip.json`'a günün tarihi yazılır. Geç uyanan nöbetçiler bunu görüp saniyeler içinde çıkar — ikinci rapor gitmez.

**Repo neden public?** Public repolarda GitHub Actions süresi ücretsiz ve sınırsızdır. Bu sayede en erken nöbetçi 04:07'de uyanıp saati bekleyebiliyor — yani GitHub **4 saat** geç kalsa bile rapor yine 08:00'de gider. Private repoda aylık 2.000 dakika sınırı olduğu için bu kadar bekleyemeyiz; orada erken nöbetçi otomatik atlanır ve pay ~50 dakikaya iner.

**Public olması güvenli mi?** Evet. Token'ların **kodda durmaz** — GitHub Secrets'ta şifreli tutulur ve Actions loglarında maskelenir. `.env` dosyası `.gitignore`'dadır, hiç yüklenmez. Ayrıca `setup.py` repoyu public yapmadan önce **sızıntı taraması** çalıştırır: `.env` takip ediliyor mu, dosyalarda veya **git geçmişinde** gerçek token kalıbı var mı diye bakar. En ufak şüphede repoyu public yapmaz, private oluşturur ve neyi bulduğunu sana söyler.

Saati değiştirmek için workflow'daki `DELIVER_AT_TR` değerini (ve istersen cron satırlarını) güncelle.

**Kart/ses gelmezse?** İkisi de "best-effort"; biri üretilemezse rapor yine gider. Rapor üretimi hata verirse sistem birkaç kez dener, yine olmazsa sana hata bildirimi gelir.

**Ücret?** Yok. GitHub Actions ücretsiz katmanı, kripto API'leri ücretsiz, kart/ses ücretsiz kütüphaneler, rapor Claude aboneliğinden düşer.

---

## Dosya yapısı

```
.
├── report.py            # Ana akış: veri → rapor → kart + brief + ses + detay gönderimi
├── asistan.py           # Soru-cevap asistanı: admin sorularını Claude ile cevaplar, zamanlı mail görevlerini ve fiyat alarmlarını yönetir
├── kart.py              # Paylaşılabilir sabah kartı (Pillow)
├── ses.py               # 45 sn sesli özet (edge-tts + ffmpeg)
├── setup.py             # Kurulum sihirbazı (chat_id, test, .env, GitHub)
├── requirements.txt     # requests, Pillow, edge-tts, tzdata
├── state/takip.json     # "Dünden hesap" hafızası (otomatik oluşur)
├── state/asistan.json   # Soru-cevap asistanının son okuduğu mesaj (otomatik oluşur)
├── state/gorevler.json  # Zamanlı mail görevleri (bekliyor/gönderildi/hata) (otomatik oluşur)
├── state/hafiza.json    # Kullanıcı hakkında öğrenilen kalıcı notlar (otomatik oluşur)
├── state/alarmlar.json  # Fiyat alarmları (aktif/tetiklendi) (otomatik oluşur)
├── .github/workflows/   # daily-report.yml (08:00 TSİ) + asistan.yml (5 dk'da bir) + tests.yml
├── CLAUDE.md            # Claude Code'un otomatik kurulum rehberi
├── test_report.py       # Birim testler
├── test_asistan.py      # Soru-cevap asistanı için birim testler
├── LICENSE              # MIT
└── .env.example
```

---

## 🎁 Ücretsiz & topluluk için

Bu araç **DogukanLive** tarafından hazırlanıp topluluğa **ücretsiz** sunulmuştur. Satılık değildir — dilediğin gibi kur, kullan, kendine göre değiştir. Beğendiysen paylaş, bir arkadaşının sabahını da güzelleştir. ☕

<sub>Made with ❤️ by <b>DogukanLive</b> · <a href="https://youtube.com/@DogukanLive">youtube.com/@DogukanLive</a> · MIT License</sub>
