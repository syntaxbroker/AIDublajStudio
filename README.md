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

## Health Endpointleri

- API: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)
- DB: [http://localhost:8000/api/v1/health/db](http://localhost:8000/api/v1/health/db)
- Redis: [http://localhost:8000/api/v1/health/redis](http://localhost:8000/api/v1/health/redis)
- Provider status: [http://localhost:8000/api/v1/runtime/providers](http://localhost:8000/api/v1/runtime/providers)

## Provider Safety

Mock provider'lar yalnizca otomatik test ve hizli smoke kosulari icindir. Mock ASR sahte 3 segmentlik timeline uretebilir; Mock TTS konusma yerine sine-wave bip sesi uretir. Bu nedenle mock provider ile uretilen video urun kalitesi kabul ciktisi sayilmaz.

Web UI gercek kullanici islemlerinde mock provider'lari sessizce kullanmaz. `ASR_PROVIDER`, `TRANSLATION_PROVIDER`, `TTS_PROVIDER`, `VOICE_CLONE_PROVIDER` veya `LIP_SYNC_PROVIDER` degerlerinden herhangi biri `mock` ise UI'da provider banner'i gorunur ve processing cagirilari `ALLOW_MOCK_PROVIDERS=true` acik degilse bloke edilir.

Test-only mock calistirma:

```powershell
$env:ALLOW_MOCK_PROVIDERS = "true"
$env:ASR_PROVIDER = "mock"
$env:TRANSLATION_PROVIDER = "mock"
$env:TTS_PROVIDER = "mock"
$env:VOICE_CLONE_PROVIDER = "mock"
$env:LIP_SYNC_PROVIDER = "mock"
docker compose --profile app up -d --build
```

Gercek local demo icin onerilen provider seti:

```powershell
$env:ALLOW_MOCK_PROVIDERS = "false"
$env:ASR_PROVIDER = "faster_whisper"
$env:TRANSLATION_PROVIDER = "ollama" # veya openai
$env:TTS_PROVIDER = "edge_tts" # cloned voice akisi icin voice clone profili kullanin
$env:VOICE_CLONE_PROVIDER = "cosyvoice"
$env:LIP_SYNC_PROVIDER = "musetalk"
$env:COSYVOICE_SERVICE_URL = "http://cosyvoice-service:8010"
$env:MUSETALK_SERVICE_URL = "http://musetalk-service:8020"
docker compose --profile app --profile cosyvoice --profile musetalk up -d --build
```

Proje sure diagnostics raporu:

- `GET /api/v1/projects/{project_id}/diagnostics/durations`
- SOURCE_VIDEO, PROXY_VIDEO, FINAL_DUB_AUDIO, LIPSYNC_VIDEO, FINAL_RENDER surelerini, max timeline end_ms degerini ve active provider listesini dondurur.

## MuseTalk Quality Presets

Sprint 50 itibariyle varsayilan politika kaynak cozunurlugunu korumaktir:

```powershell
$env:MUSETALK_QUALITY_PRESET = "source-native"
$env:MUSETALK_USE_SOURCE_FPS = "true"
$env:MUSETALK_RESOLUTION = "source"
$env:MUSETALK_PAD_MODE = "clone"
$env:MUSETALK_BATCH_SIZE = "2"
```

Bu preset kaynak videonun fps ve cozunurluk degerlerini korur. Pipeline artik kaynak videoyu sessizce 720p/1080p'ye dusurmemelidir; `LIPSYNC_VIDEO` veya `FINAL_RENDER` kaynak cozunurlugunden dusukse job fail-fast davranir ve metadata'da resolution preservation hatasi gorunur. Daha dusuk calisma cozunurlugu sadece bilerek yapilan deneysel bir override olarak kullanilmalidir, production default degildir.

- `MUSETALK_QUALITY_PRESET=current`, `MUSETALK_USE_SOURCE_FPS=false`, `MUSETALK_RESOLUTION=source`
- Deneysel downscale override: `MUSETALK_RESOLUTION=720p` veya `1080p`. Bu ayarlar input=output resolution politikasini bozdugu icin release kabulunde kullanilmamalidir.

Her `LIPSYNC_VIDEO` artifact metadata'si provider, mock durumu, fps, resolution, source_resolution, lipsync_resolution, resolution_preserved, processing_time_ms, source_video_artifact_id, audio_artifact_id ve quality_preset alanlarini tasir.

## Product Evaluation

Sprint 29 product evaluation yeni AI ozelligi eklemez; 10 gercek videoyu mevcut real-provider zincirinden gecirip teknik metrik ve bos insan degerlendirme alanlariyla JSON raporu uretir.

Gerekli provider seti:

```powershell
$env:ALLOW_MOCK_PROVIDERS = "false"
$env:ASR_PROVIDER = "faster_whisper"
$env:TRANSLATION_PROVIDER = "ollama"
$env:DIARIZATION_PROVIDER = "pyannote"
$env:VOICE_CLONE_PROVIDER = "cosyvoice"
$env:TTS_PROVIDER = "cosyvoice"
$env:LIP_SYNC_PROVIDER = "musetalk"
```

Input manifest yolu:

- `storage/tmp/sprint29_inputs/manifest.json`

Manifest ornegi:

```json
{
  "videos": [
    {
      "name": "news_sample_01",
      "category": "haber videosu",
      "source_language": "sr",
      "target_language": "tr",
      "path": "news_sample_01.mp4"
    }
  ]
}
```

Calistirma:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint29_product_evaluation.ps1
```

Cikti:

- `storage/tmp/sprint29_product_evaluation.json`

Script manifestte en az 10 video yoksa veya herhangi bir provider mock ise PASS uretmez.

## Fresh Clone Test

Temiz bir ortamda hızlı doğrulama için:

1. `git clone <repo-url>`
2. `cd AIDublajStudio`
3. `copy .env.example .env`
4. `docker compose --profile app up -d --build`
5. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint12_acceptance_tests.ps1`

Beklenen sonuç:

- web `http://localhost:3000`
- api `http://localhost:8000/api/v1/health`
- acceptance script sonunda `Sprint 12 acceptance tests passed.`

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

## Sprint 11 Acceptance

- Final audio mix acceptance testi: [infra/scripts/run_sprint11_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint11_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint11_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- mock zincir + TTS sonrası final dub audio mix akışını çalıştırır
- Sprint 11 integration testleri
- completed `AUDIO_MIX` job restart kontrolü

## Sprint 12 Acceptance

- Video render acceptance testi: [infra/scripts/run_sprint12_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint12_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint12_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- mock zincir + final dub audio sonrası MP4 render akışını çalıştırır
- Sprint 12 integration testleri
- completed `RENDER` job restart kontrolü

## Sprint 13 Web Kullanımı

Sprint 13 ile birlikte project detail ekranına TTS, Audio Mix ve Render kontrol butonları eklendi. Final dub audio ve final MP4 artifact'leri UI üzerinden görülebilir, açılabilir ve indirilebilir.

Çalıştırma:

1. `docker compose --profile app up -d --build`
2. Tarayıcıda `http://localhost:3000` açın
3. `editor@example.com / editor123` ile giriş yapın
4. Bir proje açın veya yeni proje oluşturun
5. Sırasıyla `TTS Başlat`, `Audio Mix Başlat`, `Render Başlat` butonlarını kullanın
6. `Final Dub Audio` ve `Final Render` panellerinden artifact'leri açın veya indirin

Beklenen görünür sonuçlar:

- project detail içinde TTS / AUDIO_MIX / RENDER job durumları
- `FINAL_DUB_AUDIO` artifact görünümü
- `FINAL_RENDER` artifact görünümü
- `Play / Open` ve `Download` aksiyonları
- failed job varsa hata mesajının ekranda görünmesi

## Sprint 15 Smoke

- Gerçek Edge TTS smoke testi: [infra/scripts/run_sprint15_edge_tts_smoke_test.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint15_edge_tts_smoke_test.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint15_edge_tts_smoke_test.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- `TTS_PROVIDER=edge_tts` ile gerçek Türkçe ses üretir
- aynı ses ile `AUDIO_MIX` ve `RENDER` zincirini doğrular
- hatalı voice config ile provider failure senaryosunu doğrular

Notlar:

- Varsayılan gerçek provider `edge_tts`
- Ses seçimi `EDGE_TTS_VOICE` veya `TTS_VOICE_NAME` ile değiştirilebilir
- `piper` config/registry desteği eklidir, ancak gerçek implementasyonu bu sprintte tamamlanmadı

## Sprint 16 Acceptance

- Voice profile / voice library temel veri katmanı acceptance testi: [infra/scripts/run_sprint16_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint16_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint16_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- default Türkçe `voice_profiles` bootstrap kontrolünü doğrular
- `GET /voice-profiles` ve character voice assignment akışını test eder
- mock TTS üzerinde assigned voice ve default fallback davranışını doğrular
- completed `TTS` job restart kontrolünü yapar

Yeni endpoint'ler:

- `GET /api/v1/voice-profiles`
- `POST /api/v1/voice-profiles`
- `PATCH /api/v1/voice-profiles/{id}`
- `POST /api/v1/projects/{project_id}/characters/{character_id}/voice-profile`

## Sprint 17 Web Kullanımı

Sprint 17 ile birlikte web arayüzünde voice profile yönetimi project detail ekranına taşındı.

Kullanım:

1. `docker compose --profile app up -d --build`
2. Tarayıcıda `http://localhost:3000` açın
3. `editor@example.com / editor123` ile giriş yapın
4. Bir proje açın
5. Gerekirse `Generate Characters` ile karakterleri üretin
6. `Voice Profiles` panelinden mevcut Türkçe sesleri görün
7. `Characters` panelinde bir karakter için `Voice Profile` seçin ve `Save Voice` ile kaydedin
8. `TTS Başlat` ile yeni atamaya göre dub segmentlerini üretin
9. `Dub Segments` tablosunda kullanılan `voice_id` değerini doğrulayın
10. İsterseniz `Audio Mix Başlat` ve `Render Başlat` ile final zinciri tamamlayın

Beklenen görünür sonuçlar:

- karakter kartında `Assigned: ...` bilgisi görünür
- sayfa yenileme sonrası voice profile ataması korunur
- `Dub Segments` tablosunda seçilen veya fallback edilen `voice_id` görünür
- `FINAL_DUB_AUDIO` ve `FINAL_RENDER` artifact’leri üretilebilir

## Sprint 18 Acceptance

- Voice cloning temel katmanı acceptance testi: [infra/scripts/run_sprint18_acceptance_tests.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint18_acceptance_tests.ps1)

Çalıştırma:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint18_acceptance_tests.ps1`

Bu script şunları yapar:

- `docker compose down -v`
- `docker compose --profile app up -d --build`
- mock ASR, translation, diarization, TTS ve mock voice clone ile zinciri çalıştırır
- karakterden ses örneği çıkarır
- `VOICE_SAMPLE_AUDIO` ve `VOICE_REFERENCE_AUDIO` artifact'lerini doğrular
- cloned `voice_profile` oluşturur ve karaktere atar
- cloned profile ile TTS, audio mix ve render zincirini doğrular
- Sprint 18 integration testlerini çalıştırır

## Sprint 18 Web Kullanımı

Sprint 18 ile birlikte karakter kartlarında ses örneği ve klon profil akışı görünür hale geldi.

Kullanım:

1. `docker compose --profile app up -d --build`
2. Tarayıcıda `http://localhost:3000` açın
3. `editor@example.com / editor123` ile giriş yapın
4. Bir proje açın ve gerekirse `Generate Characters` ile karakterleri üretin
5. Karakter kartında `Ses Ornegi Cikar` butonuna basın
6. Sample ve reference artifact bilgisinin karakter kartında göründüğünü doğrulayın
7. `Klon Ses Profili Olustur` ile cloned profile oluşturun
8. Gerekirse `Save Voice` ile farklı bir profile dönün veya cloned profile'ın seçili kaldığını doğrulayın
9. `TTS Baslat`, `Audio Mix Baslat` ve `Render Baslat` ile zinciri tamamlayın
10. `Dub Segments` tablosunda cloned karakter için provider / profile type bilgilerini kontrol edin

## Sprint 19 CosyVoice Smoke

- Gerçek voice cloning provider smoke testi: [infra/scripts/run_sprint19_cosyvoice_smoke_test.ps1](C:/xampp/htdocs/AIDublajStudio/infra/scripts/run_sprint19_cosyvoice_smoke_test.ps1)

Çalıştırma öncesi iki yol vardır.

### Yol 1: Kendi synth komutunuz

Gerekli env:

- `VOICE_CLONE_PROVIDER=cosyvoice`
- `COSYVOICE_SERVICE_URL=http://cosyvoice-service:8010`
- `COSYVOICE_SYNTH_COMMAND=...`

Örnek:

```powershell
$env:VOICE_CLONE_PROVIDER = "cosyvoice"
$env:COSYVOICE_SERVICE_URL = "http://cosyvoice-service:8010"
$env:COSYVOICE_SYNTH_COMMAND = "python /workspace/services/cosyvoice/app/run_cosyvoice.py --repo-dir /opt/cosyvoice/CosyVoice --model-dir /models/CosyVoice-300M --device auto --text-file {text_file} --reference-audio {reference_audio} --output-audio {output_audio} --language-code {language_code} --voice-profile-id {voice_profile_id} --model-name {model_name} --reference-text-file {reference_text_file}"
```

### Yol 2: Dahili runner + hazır runtime

Gerekli env:

- `VOICE_CLONE_PROVIDER=cosyvoice`
- `COSYVOICE_SERVICE_URL=http://cosyvoice-service:8010`
- `COSYVOICE_REPO_DIR=/opt/cosyvoice/CosyVoice`
- `COSYVOICE_MODEL_DIR=/models/CosyVoice-300M`

Opsiyonel bootstrap env:

- `COSYVOICE_BOOTSTRAP=1`
- `COSYVOICE_REPO_URL=https://github.com/FunAudioLLM/CosyVoice.git`
- `COSYVOICE_MODEL_ID=FunAudioLLM/CosyVoice-300M`
- `COSYVOICE_DEVICE=auto`
- `COSYVOICE_INSTALL_MODE=minimal`

Örnek:

```powershell
$env:VOICE_CLONE_PROVIDER = "cosyvoice"
$env:COSYVOICE_SERVICE_URL = "http://cosyvoice-service:8010"
$env:COSYVOICE_BOOTSTRAP = "1"
$env:COSYVOICE_REPO_URL = "https://github.com/FunAudioLLM/CosyVoice.git"
$env:COSYVOICE_MODEL_ID = "FunAudioLLM/CosyVoice-300M"
$env:COSYVOICE_REPO_DIR = "/opt/cosyvoice/CosyVoice"
$env:COSYVOICE_MODEL_DIR = "/models/CosyVoice-300M"
$env:COSYVOICE_DEVICE = "auto"
$env:COSYVOICE_INSTALL_MODE = "minimal"
```

Notlar:

- Sprint 19, API/worker tarafını gerçek bir CosyVoice HTTP servisine bağlar.
- Repository içindeki `cosyvoice-service`, gerçek model komutunu `COSYVOICE_SYNTH_COMMAND` ile dışarıdan çalıştırabilen hafif bir köprüdür.
- İsterseniz `COSYVOICE_BOOTSTRAP=1` ile service repo ve modeli kendi named volume’larına indirebilir.
- `COSYVOICE_INSTALL_MODE=minimal` inference için gereken daha dar paket setini kurar; `repo` modu upstream `requirements.txt`’in tamamını yükler.
- `COSYVOICE_DEVICE=auto` ise servis önce CUDA dener, yoksa CPU fallback kullanır.
- `COSYVOICE_DEVICE=cuda` iken GPU görünmüyorsa servis açık hata verir.
- Gerçek model/runtime bu repoda vendor edilmez; ancak service runner ve bootstrap yolu repoda hazırdır.

Smoke komutu:

1. `powershell -ExecutionPolicy Bypass -File .\infra\scripts\run_sprint19_cosyvoice_smoke_test.ps1`

Bu script şunları doğrular:

- cloned profile ile `cosyvoice` provider seçimi
- `reference_audio_artifact_id` üzerinden gerçek clone synthesis çağrısı
- `DubSegment.metadata_json` içinde `cloned`, `model_name`, `reference_audio_artifact_id`
- `AUDIO_MIX` ve `RENDER` zincirinin bozulmaması
- eksik reference ve çok kısa sample failure senaryoları

## Demo Akışı

Demo sırasında önerilen tam sıra:

1. `docker compose --profile app up -d --build`
2. Tarayıcıda `http://localhost:3000` açın
3. `editor@example.com / editor123` ile login olun
4. Yeni proje oluşturun
5. Geçerli bir MP4 upload edin
6. Project detail ekranında ingest, transcribe ve translate job'larının tamamlanmasını bekleyin
7. `TTS Başlat`
8. `Audio Mix Başlat`
9. `Render Başlat`
10. `Final Render` panelinde `Play / Open` veya `Download` kullanın
11. Sayfayı yenileyip final artifact'lerin kalıcı kaldığını doğrulayın

## Demo Checklist

- [ ] `/health`, `/health/db`, `/health/redis` ayakta
- [ ] Login başarılı
- [ ] Proje oluşturuldu
- [ ] Video upload edildi
- [ ] Transcript oluştu
- [ ] Translation oluştu
- [ ] TTS tamamlandı
- [ ] Final dub audio oluştu
- [ ] Render tamamlandı
- [ ] Final MP4 açıldı veya indirildi
- [ ] Refresh sonrası proje durumu korundu
- [ ] Yetkisiz artifact erişimi reddedildi

## Hatalı Video Senaryosu

Bozuk veya ffmpeg tarafından işlenemeyen bir video upload edilirse:

- upload kabul edilse bile ilgili worker job `FAILED` olabilir
- web arayüzünde failed job hata mesajı görünür
- proje detay ekranı açılmaya devam eder
- kullanıcı yeni bir geçerli video ile yeniden deneyebilir
