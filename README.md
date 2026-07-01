# dboss-backend

**dboss** yapay zeka destekli sohbet uygulamasının backend (sunucu) bileşenidir. Kullanıcı yönetimi, kimlik doğrulama, sohbet geçmişi ve büyük dil modeli (LLM) entegrasyonunu yöneten merkezi API sunucusudur.

Bu backend, iki farklı istemciye hizmet verir: bir **React web arayüzü** ([dboss-web](https://github.com/zeynepgunall/dboss-web)) ve bir **Python komut satırı aracı** ([dboss-cli](https://github.com/zeynepgunall/dboss-cli)). Backend beyin, istemciler onun yüzüdür.

**Canlı API:** https://dboss-backend.onrender.com
**API Dokümantasyonu (Swagger):** https://dboss-backend.onrender.com/docs

---

## İçindekiler

- [Mimari](#mimari)
- [Kullanılan Teknolojiler](#kullanılan-teknolojiler)
- [Proje Yapısı](#proje-yapısı)
- [Veritabanı Şeması](#veritabanı-şeması)
- [API Endpoint'leri](#api-endpointleri)
- [Kimlik Doğrulama](#kimlik-doğrulama)
- [Yapay Zeka Entegrasyonu](#yapay-zeka-entegrasyonu)
- [Kurulum ve Çalıştırma](#kurulum-ve-çalıştırma)
- [Ortam Değişkenleri](#ortam-değişkenleri)
- [Deploy (Canlıya Alma)](#deploy-canlıya-alma)
- [Güvenlik Notları](#güvenlik-notları)

---

## Mimari

dboss üç bileşenden oluşur ve hepsi canlı ortamda çalışır:

```
┌─────────────┐        ┌─────────────┐
│  dboss-web  │        │  dboss-cli  │
│   (React)   │        │  (Python)   │
└──────┬──────┘        └──────┬──────┘
       │                      │
       │   HTTP / REST API    │
       └──────────┬───────────┘
                  │
         ┌────────▼─────────┐
         │  dboss-backend   │
         │    (FastAPI)     │
         └────────┬─────────┘
                  │
        ┌─────────┴──────────┐
        │                    │
  ┌─────▼──────┐      ┌──────▼──────┐
  │ PostgreSQL │      │  Groq (LLM) │
  │(veritabanı)│      │   (model)   │
  └────────────┘      └─────────────┘
```

Backend, tüm iş mantığını merkezileştirir: istemciler (web, CLI) doğrudan veritabanına ya da modele erişmez; her şey backend API'si üzerinden geçer. Bu yaklaşım, güvenliği tek noktada toplar ve yeni istemciler (örneğin ileride bir mobil uygulama) eklemeyi kolaylaştırır.

---

## Kullanılan Teknolojiler

| Teknoloji | Amaç |
|-----------|------|
| **FastAPI** | Modern, hızlı Python web framework'ü. Otomatik API dokümantasyonu sağlar. |
| **SQLAlchemy** | Veritabanı ORM'i (nesne-ilişkisel eşleme). SQL yazmadan Python nesneleriyle çalışmayı sağlar. |
| **PostgreSQL** | Canlı ortam veritabanı (yerelde SQLite kullanılır). |
| **Pydantic** | Veri doğrulama ve şema tanımlama. Gelen/giden verinin doğruluğunu garanti eder. |
| **python-jose** | JWT (JSON Web Token) üretme ve doğrulama. |
| **passlib + bcrypt** | Şifre hashleme (şifreler asla düz metin saklanmaz). |
| **groq** | Groq LLM API istemcisi (yapay zeka cevapları için). |
| **uvicorn** | ASGI sunucusu (FastAPI'yi çalıştırır). |

---

## Proje Yapısı

```
dboss-backend/
├── app/
│   ├── main.py        # FastAPI uygulaması, endpoint tanımları, CORS
│   ├── database.py    # Veritabanı bağlantısı ve oturum yönetimi
│   ├── models.py      # SQLAlchemy modelleri (User, Thread, Message)
│   ├── schemas.py     # Pydantic şemaları (istek/yanıt doğrulama)
│   ├── auth.py        # Kimlik doğrulama (JWT, şifre hashleme)
│   └── llm.py         # Yapay zeka entegrasyonu (model çağrısı, başlık üretimi)
├── requirements.txt   # Python bağımlılıkları
└── README.md
```

Her dosyanın tek bir sorumluluğu vardır (separation of concerns): modeller ayrı, şemalar ayrı, kimlik doğrulama ayrı, yapay zeka ayrı. Bu, kodun bakımını ve anlaşılmasını kolaylaştırır.

---

## Veritabanı Şeması

Üç tablo, ilişkisel yapıda:

```
users (kullanıcılar)
  ├── id (birincil anahtar)
  ├── username (benzersiz)
  ├── email (benzersiz)
  ├── hashed_password (bcrypt ile hash'lenmiş)
  └── created_at
        │
        │ bir kullanıcının çok sohbeti olur (1-N)
        ▼
threads (sohbetler)
  ├── id (birincil anahtar)
  ├── user_id (users.id'ye bağlı)
  ├── title (yapay zekanın ürettiği başlık, başta boş)
  ├── created_at
  └── updated_at (her yeni mesajda güncellenir)
        │
        │ bir sohbetin çok mesajı olur (1-N)
        ▼
messages (mesajlar)
  ├── id (birincil anahtar)
  ├── thread_id (threads.id'ye bağlı)
  ├── role (user / assistant / system)
  ├── content (mesaj içeriği)
  ├── model (hangi modelin ürettiği)
  ├── message_metadata (JSON: token sayısı, gecikme, sağlayıcı)
  └── created_at
```

**Tasarım kararları:**

- **Cascade silme:** Bir sohbet silinince, ona bağlı tüm mesajlar da otomatik silinir. Böylece "öksüz" (sahipsiz) mesaj kalmaz.
- **`updated_at` manuel güncelleme:** Yeni mesaj eklenince `threads.updated_at` elle güncellenir. Sebebi: mesaj `messages` tablosuna yazılır, `threads` tablosuna dokunulmaz — o yüzden otomatik güncelleme tetiklenmez. Bu alan, sohbet listesinde "son aktif sohbet üstte" sıralaması için gereklidir.
- **Model bilgisi mesaj başına:** Her mesaj hangi modelden geldiğini saklar. Böylece kullanıcı mesaj başına farklı model seçebilir.
- **`message_metadata` (JSON):** Her yapay zeka çağrısının token kullanımı, gecikme ve sağlayıcı bilgisini saklar. İleride maliyet/performans analizi için değerlidir.

---

## API Endpoint'leri

### Kimlik Doğrulama

| Metod | Yol | Açıklama |
|-------|-----|----------|
| `POST` | `/register` | Yeni kullanıcı kaydı |
| `POST` | `/login` | Giriş yapar, JWT token döner |
| `GET` | `/me` | Mevcut kullanıcı bilgisini döner (token gerekli) |

### Sohbet Yönetimi (hepsi token korumalı)

| Metod | Yol | Açıklama |
|-------|-----|----------|
| `POST` | `/threads` | Yeni sohbet oluşturur |
| `GET` | `/threads` | Kullanıcının sohbetlerini listeler (son aktif üstte) |
| `DELETE` | `/threads/{id}` | Sohbeti siler (mesajları da cascade ile gider) |
| `GET` | `/threads/{id}/messages` | Sohbetin mesajlarını getirir |
| `POST` | `/threads/{id}/messages` | Sohbete manuel mesaj ekler |
| `POST` | `/threads/{id}/chat` | Asıl sohbet: mesaj gönderir, AI cevap üretir |

### Diğer

| Metod | Yol | Açıklama |
|-------|-----|----------|
| `GET` | `/models` | Kullanılabilir yapay zeka modellerini listeler |

### Sohbet Akışı (`POST /threads/{id}/chat`)

Bu endpoint uygulamanın kalbidir. Kullanıcı mesaj gönderince şu adımlar izlenir:

1. Kullanıcının mesajı veritabanına kaydedilir.
2. Sohbetin tüm geçmişi (yeni mesaj dahil) alınır.
3. Geçmiş + yeni mesaj yapay zeka modeline gönderilir.
4. Modelin cevabı kaydedilir (model adı ve metadata ile birlikte).
5. Eğer bu sohbetin ilk mesajıysa, yapay zeka ile otomatik bir başlık üretilir.
6. Sohbetin `updated_at` alanı güncellenir.

Tüm bu işlem **tek bir veritabanı işlemi (transaction)** içinde yapılır. Eğer herhangi bir adımda hata olursa (örneğin model erişilemezse), hiçbir şey yarım kaydedilmez — işlem geri alınır (rollback) ve `502` hatası döner.

---

## Kimlik Doğrulama

Sistem **JWT (JSON Web Token)** tabanlı kimlik doğrulama kullanır:

1. Kullanıcı `/login` ile giriş yapar.
2. Backend, kullanıcı kimliğini içeren imzalı bir token üretir (HS256 algoritması, 30 dakika geçerli).
3. İstemci, sonraki her istekte bu token'ı `Authorization: Bearer <token>` başlığında gönderir.
4. Backend her korumalı istekte token'ı doğrular ve kullanıcıyı tanır.

**Şifre güvenliği:** Şifreler asla düz metin olarak saklanmaz. `bcrypt` algoritması ile hash'lenir. Giriş sırasında, girilen şifrenin hash'i saklanan hash ile karşılaştırılır.

**Yetkilendirme:** Her kullanıcı yalnızca kendi verilerine erişebilir. Sohbet sorguları hem sohbet id'si hem kullanıcı id'si ile filtrelenir. Başkasının sohbetine erişim denemesi `404` döner (bilinçli olarak `403` değil — çünkü `403` verinin varlığını sızdırır, `404` hiçbir bilgi vermez).

---

## Yapay Zeka Entegrasyonu

Yapay zeka entegrasyonu `app/llm.py` dosyasında, soyut bir katman olarak tasarlanmıştır. Bu sayede model sağlayıcısı değişse bile (örneğin Groq'tan başka bir servise geçiş), yalnızca bu dosya güncellenir; çağıran kod değişmez.

**Kullanılan sağlayıcı:** [Groq](https://groq.com) — hızlı çıkarım (inference) sunan, ücretsiz katmanı olan bir LLM API'si.

**Desteklenen modeller** (`GET /models` ile listelenir):

| Model | Özellik |
|-------|---------|
| `openai/gpt-oss-120b` | Güçlü, dengeli (varsayılan model) |
| `openai/gpt-oss-20b` | Hızlı, ekonomik (başlık üretimi için de kullanılır) |
| `qwen/qwen3.6-27b` | Akıl yürütme (reasoning) yeteneği yüksek |

**Ana fonksiyonlar:**

- **`generate_reply(history, model)`** — Sohbet geçmişini alır, seçilen modele gönderir, cevabı ve metadata'yı (token sayısı, sağlayıcı) döner. Geçersiz model gelirse varsayılana düşer.
- **`generate_title(first_message)`** — İlk mesajdan kısa bir sohbet başlığı üretir. Küçük iş olduğu için hızlı/ekonomik model kullanır.

**Türkçe yönlendirme:** Modele bir sistem promptu verilir — her zaman düzgün ve akıcı Türkçe yanıt vermesi, başka dillerden karakter karıştırmaması istenir.

**Reasoning bloğu temizliği:** Qwen gibi akıl yürüten modeller, cevaptan önce bir düşünme süreci (`<think>...</think>`) üretir. Bu, kullanıcıya gösterilmeden önce temizlenir; yalnızca asıl cevap saklanır.

---

## Kurulum ve Çalıştırma

### Gereksinimler

- Python 3.10+
- (İsteğe bağlı) Bir Groq API anahtarı (yapay zeka cevapları için)

### Adımlar

```bash
# Depoyu klonla
git clone https://github.com/zeynepgunall/dboss-backend.git
cd dboss-backend

# Sanal ortam oluştur ve aktifleştir
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# Bağımlılıkları kur
pip install -r requirements.txt

# Ortam değişkenlerini ayarla (aşağıya bakınız)
# Windows PowerShell örneği:
$env:GROQ_API_KEY = "gsk_..."

# Sunucuyu başlat
uvicorn app.main:app --reload
```

Sunucu başladıktan sonra:
- API: http://localhost:8000
- Dokümantasyon: http://localhost:8000/docs

Yerel ortamda veritabanı olarak otomatik olarak SQLite kullanılır (ayrı kurulum gerektirmez). Tablolar uygulama başlangıcında otomatik oluşturulur.

---

## Ortam Değişkenleri

| Değişken | Zorunlu mu? | Açıklama |
|----------|-------------|----------|
| `GROQ_API_KEY` | Evet (AI için) | Groq API anahtarı. Yapay zeka cevapları için gerekli. |
| `DATABASE_URL` | Hayır | Veritabanı bağlantı adresi. Belirtilmezse yerel SQLite kullanılır. Canlıda PostgreSQL adresi verilir. |
| `SECRET_KEY` | Canlıda evet | JWT imzalama anahtarı. Belirtilmezse güvensiz bir varsayılan kullanılır (yalnızca geliştirme için). |
| `CORS_ORIGINS` | Hayır | İzin verilen kaynak adresler (virgülle ayrılmış). Web arayüzünün adresi buraya eklenir. Belirtilmezse yerel geliştirme adresleri kullanılır. |

**Güvenlik uyarısı:** `GROQ_API_KEY` ve `SECRET_KEY` gibi hassas değerler asla kodun içine yazılmaz veya depoya gönderilmez. Yalnızca ortam değişkeni olarak sağlanır.

---

## Deploy (Canlıya Alma)

Backend, [Render](https://render.com) platformunda canlıdır ve GitHub deposuna bağlıdır. `main` dalına yapılan her push, otomatik olarak yeniden deploy tetikler (sürekli dağıtım / CD).

**Canlı ortam yapılandırması:**
- Veritabanı: Render PostgreSQL
- Başlatma komutu: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Ortam değişkenleri (`GROQ_API_KEY`, `SECRET_KEY`, `DATABASE_URL`, `CORS_ORIGINS`) Render panelinden ayarlanır.

**Not:** Render'ın ücretsiz katmanı, 15 dakika istek gelmezse sunucuyu uykuya alır. Uykudaki sunucuya gelen ilk istek, sunucunun uyanması nedeniyle 30-50 saniye sürebilir.

---

## Güvenlik Notları

- **Şifreler** bcrypt ile hash'lenir, asla düz metin saklanmaz.
- **JWT token'ları** imzalıdır ve 30 dakika sonra geçersiz olur.
- **Yetkilendirme** her istekte kontrol edilir; kullanıcılar yalnızca kendi verilerine erişir.
- **Hassas anahtarlar** (API key, secret key) yalnızca ortam değişkeni olarak tutulur, kaynak kodda bulunmaz.
- **CORS** ile yalnızca izin verilen adreslerden (web arayüzü) gelen tarayıcı istekleri kabul edilir.
- **Bilgi sızıntısı önleme:** Yetkisiz erişim denemelerinde `404` döndürülerek verinin varlığı gizlenir.

Bu proje, Databoss bünyesinde mentörlük eşliğinde geliştirilmektedir.
