# AI Dublaj Stüdyosu

Bu repository, lokal ağ üzerinde çalışan AI destekli video dublaj sistemi için başlangıç mimarisini, veri modelini ve geliştirme ortamı iskeletini içerir.

İlk hedef:

- `upload -> transcript -> translation -> TTS -> render` omurgasını kurmak
- timeline merkezli veri modelini baştan oturtmak
- audit, artifact ve job state machine yapılarını çekirdeğe almak
- çoklu provider ve çoklu GPU genişlemesine hazır kalmak

Ana teknik doküman:

- [docs/system-blueprint.md](C:/xampp/htdocs/AIDublajStudio/docs/system-blueprint.md)

Veritabanı başlangıç dosyaları:

- [infra/postgres/init/001_extensions.sql](C:/xampp/htdocs/AIDublajStudio/infra/postgres/init/001_extensions.sql)
- [infra/postgres/init/002_schema.sql](C:/xampp/htdocs/AIDublajStudio/infra/postgres/init/002_schema.sql)

Geliştirme ortamı:

- [docker-compose.yml](C:/xampp/htdocs/AIDublajStudio/docker-compose.yml)
- [.env.example](C:/xampp/htdocs/AIDublajStudio/.env.example)

## Sprint 1 Durumu

Hazır olan platform omurgası:

- FastAPI backend iskeleti
- UUIDv7 tabanlı kimlik üretimi
- auth login ve `me` endpoint'i
- project create, list, detail endpoint'leri
- source video upload akışı
- artifact kaydı
- audit event kaydı
- ingest job oluşturma ve state transition omurgası
- boş AI provider contract'ları ve mock provider registry

Henüz bilinçli olarak yapılmayanlar:

- gerçek ASR entegrasyonu
- gerçek TTS entegrasyonu
- gerçek lip sync entegrasyonu

## Hızlı Başlangıç

1. `.env.example` dosyasını `.env` olarak kopyalayın ve gerekirse değiştirin.
2. `docker compose --profile app up --build` çalıştırın.
3. API açıldıktan sonra varsayılan kullanıcılarla giriş yapın:
   - `admin@example.com / admin123`
   - `editor@example.com / editor123`

## Entegrasyon Testleri

- Otomatik entegrasyon testi: [infra/scripts/run_sprint1_integration_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint1_integration_tests.ps1)
- Restart/resume testi: [infra/scripts/restart_resume_test.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/restart_resume_test.ps1)

Pytest kapsamı:

- auth -> project -> upload -> artifact -> audit -> job -> project detail
- duplicate upload davranışı
- büyük ve özel karakter içeren dosya adı
- opsiyonel 1 GB upload testi (`RUN_LARGE_UPLOAD=1`)

## Sprint 2 Smoke Test

- Media pipeline smoke testi: [infra/scripts/run_sprint2_smoke_test.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint2_smoke_test.ps1)

## Sprint 2 Acceptance

- Temiz ortam kabul testi: [infra/scripts/run_sprint2_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint2_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint2_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- örnek geçerli MP4 üretimi
- Sprint 2 integration testleri
- worker restart acceptance
- processing recovery acceptance

## Sprint 3 Acceptance

- Mock ASR acceptance testi: [infra/scripts/run_sprint3_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint3_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint3_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- örnek geçerli MP4 üretimi
- Sprint 3 integration testleri
- completed transcribe worker restart acceptance
- transcribe processing recovery acceptance

## Sprint 4 Smoke

- Faster-Whisper smoke testi: [infra/scripts/run_sprint4_faster_whisper_smoke_test.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint4_faster_whisper_smoke_test.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint4_faster_whisper_smoke_test.ps1`

Opsiyonlar:

- `-Language en|sr|auto`
- `-SampleVideoPath C:\path\to\sample.mp4`
- `-SkipFailureCase`

Notlar:

- Varsayılan smoke testi İngilizce örnek videoyu lokal olarak üretir.
- Sırpça smoke testi için örnek bir konuşma videosu `-SampleVideoPath` ile verilebilir.
- Script başarı senaryosundan sonra isteğe bağlı provider failure senaryosunu da doğrular.

## Sprint 5 Acceptance

- Translation layer acceptance testi: [infra/scripts/run_sprint5_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint5_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint5_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- mock ASR ve mock translation ile zinciri çalıştırır
- Sprint 5 integration testleri
- completed translate worker restart acceptance
- translate processing recovery acceptance

## Sprint 6 Acceptance

- Speaker diarization acceptance testi: [infra/scripts/run_sprint6_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint6_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint6_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- mock ASR, mock translation ve mock diarization ile zinciri çalıştırır
- Sprint 6 integration testleri
- completed diarize worker restart acceptance
- diarize processing recovery acceptance

## Sprint 7 Acceptance

- Character layer acceptance testi: [infra/scripts/run_sprint7_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint7_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint7_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- mock ASR, mock translation, mock diarization ve character generation ile zinciri çalıştırır
- Sprint 7 integration testleri

## Sprint 8 Acceptance

- Timeline edit acceptance testi: [infra/scripts/run_sprint8_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint8_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint8_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- mock ASR, mock translation, mock diarization, character layer ve timeline edit zincirini çalıştırır
- Sprint 8 integration testleri

## Sprint 9 Web Kullanımı

Sprint 9 ile birlikte minimal React arayüzü eklendi. Amaç, çalışan backend pipeline'ını tarayıcıdan test edebilmek.

Çalıştırma:

1. `docker compose --profile app up -d --build`
2. Tarayıcıda `http://localhost:3000` açın
3. API health kontrolü için isterseniz `http://localhost:8000/api/v1/health` açın

Varsayılan kullanıcılar:

- `editor@example.com / editor123`
- `admin@example.com / admin123`

Web arayüzünde yapabilecekleriniz:

- login
- project list
- create project
- video upload
- project detail görüntüleme
- pipeline / job status izleme
- artifact listesi görüntüleme
- transcript, translation ve speaker segmentlerini okuma
- character üretme ve rename
- timeline clip `text`, `translation_text` ve `character_id` düzenleme

Sprint 9 manuel kabul akışı için önerilen sıra:

1. Login olun.
2. Yeni proje oluşturun.
3. Video upload edin.
4. Project detail sayfasında artifact ve job durumlarını izleyin.
5. Transcript, translation ve speaker segmentlerinin dolduğunu doğrulayın.
6. `Generate Characters` ile speaker bazlı karakterleri üretin.
7. Character rename yapın.
8. Timeline clip text / translation / character düzenleyin.
9. Sayfayı yenileyip değişikliklerin kalıcı olduğunu doğrulayın.

## Sprint 10 Acceptance

- TTS layer acceptance testi: [infra/scripts/run_sprint10_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint10_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint10_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- mock ASR, translation, diarization ve mock TTS ile zinciri çalıştırır
- Sprint 10 integration testleri
- completed TTS job restart kontrolü
