# Sistem Blueprint

## 1. Çekirdek Tasarım İlkeleri

- Timeline merkezli tasarım: tüm AI işlemleri timeline'a veri üretir.
- Metadata veritabanında, büyük medya dosyaları dosya sisteminde yaşar.
- Her kritik işlem audit event üretir.
- Her üretilen çıktı artifact olarak izlenir.
- Her iş zorunlu state machine üzerinden akar.
- AI modelleri provider tabanlı soyutlanır, hardcoded model bağımlılığı oluşmaz.
- GPU worker yapısı tek GPU ile başlar, çoklu GPU'ya ölçeklenebilir kalır.

Temel veri akışı:

```text
Video
-> Source Artifact
-> Proxy / Audio Extraction
-> Transcript Segments
-> Translation Segments
-> Dub Segments
-> Timeline Clips
-> Render Artifacts
```

## 2. Kesin Monorepo Klasör Yapısı

```text
AIDublajStudio/
├─ apps/
│  ├─ api/
│  │  ├─ app/
│  │  │  ├─ api/
│  │  │  ├─ core/
│  │  │  ├─ db/
│  │  │  ├─ models/
│  │  │  ├─ repositories/
│  │  │  ├─ schemas/
│  │  │  ├─ services/
│  │  │  ├─ providers/
│  │  │  └─ main.py
│  │  ├─ tests/
│  │  └─ requirements/
│  └─ web/
│     ├─ src/
│     │  ├─ app/
│     │  ├─ pages/
│     │  ├─ features/
│     │  ├─ components/
│     │  ├─ stores/
│     │  ├─ services/
│     │  ├─ hooks/
│     │  ├─ lib/
│     │  ├─ types/
│     │  └─ styles/
│     ├─ public/
│     └─ tests/
├─ workers/
│  ├─ gpu/
│  │  ├─ app/
│  │  │  ├─ jobs/
│  │  │  ├─ pipelines/
│  │  │  ├─ providers/
│  │  │  ├─ scoring/
│  │  │  └─ main.py
│  └─ media/
│     ├─ app/
│     │  ├─ jobs/
│     │  ├─ ffmpeg/
│     │  ├─ waveform/
│     │  └─ main.py
├─ packages/
│  ├─ shared-py/
│  │  ├─ domain/
│  │  ├─ contracts/
│  │  ├─ events/
│  │  └─ utils/
│  └─ shared-ts/
│     ├─ api-client/
│     ├─ types/
│     └─ timeline/
├─ infra/
│  ├─ postgres/
│  │  └─ init/
│  ├─ redis/
│  └─ scripts/
├─ docs/
├─ storage/
│  ├─ projects/
│  └─ tmp/
└─ docker-compose.yml
```

## 3. Storage Klasör Yapısı

Fiziksel medya verisi yalnız dosya sisteminde tutulur.

```text
storage/
├─ projects/
│  └─ project_{project_id}/
│     ├─ source/
│     │  └─ original.mp4
│     ├─ proxies/
│     │  ├─ proxy_720p.mp4
│     │  └─ thumb.jpg
│     ├─ audio/
│     │  ├─ source_audio.wav
│     │  ├─ dialog.wav
│     │  ├─ music.wav
│     │  ├─ effects.wav
│     │  └─ ambient.wav
│     ├─ transcripts/
│     │  ├─ asr_v1.json
│     │  └─ asr_v1.srt
│     ├─ translations/
│     │  └─ tr_v1.json
│     ├─ tts/
│     │  └─ segment_{segment_id}.wav
│     ├─ lipsync/
│     │  └─ clip_{clip_id}.mp4
│     ├─ renders/
│     │  ├─ draft/
│     │  └─ final/
│     ├─ waveforms/
│     ├─ versions/
│     └─ snapshots/
└─ tmp/
```

Depolama kuralı:

- DB sadece metadata tutar.
- Her fiziksel dosyanın DB'de bir `artifact` kaydı olur.
- Dosya yolu mutlak değil, `storage root` altına göreli saklanır.
- Her artifact checksum ile doğrulanır.

## 4. PostgreSQL Başlangıç Şeması Mantığı

Temel kararlar:

- `pgvector` zorunlu.
- Audit event tablosu zorunlu.
- `jobs` state machine zorunlu.
- Artifact registry zorunlu.
- Segment zinciri ayrı tablolarda tutulur.

Çekirdek tablolar:

- `users`
- `projects`
- `project_members`
- `project_versions`
- `artifacts`
- `artifact_links`
- `project_events`
- `jobs`
- `job_attempts`
- `provider_configs`
- `model_registry`
- `character_profiles`
- `voice_profiles`
- `embeddings`
- `transcript_segments`
- `translation_segments`
- `dub_segments`
- `timeline_clips`

Embedding yaklaşımı:

- `pgvector` için değişken boyutlu `vector` tipi kullanılır.
- İndeksler model bazlı partial index ile eklenir.
- Aynı tabloda farklı embedding boyutlarını desteklemek için `model_registry_id` ve `dimensions` tutulur.

## 5. FastAPI Modül Sınırları

`apps/api/app/core`

- config
- security
- logging
- exception handling
- dependency injection

`apps/api/app/db`

- engine
- session
- migrations
- seed

`apps/api/app/models`

- SQLAlchemy modelleri

`apps/api/app/schemas`

- request/response DTO'ları

`apps/api/app/repositories`

- veri erişim katmanı

`apps/api/app/services`

- iş kuralları
- orchestrator çağrıları
- artifact kayıtları
- audit event üretimi

`apps/api/app/providers`

- ASR
- translation
- TTS
- diarization
- lip sync

Provider örneği:

```text
providers/
├─ asr/
│  ├─ base.py
│  ├─ faster_whisper.py
│  ├─ whisperx.py
│  └─ registry.py
├─ tts/
│  ├─ base.py
│  ├─ cosyvoice.py
│  ├─ f5tts.py
│  └─ registry.py
└─ translation/
   ├─ base.py
   ├─ openai_provider.py
   ├─ ollama_provider.py
   └─ registry.py
```

`apps/api/app/api`

- `auth.py`
- `projects.py`
- `uploads.py`
- `artifacts.py`
- `transcripts.py`
- `translations.py`
- `timeline.py`
- `jobs.py`
- `renders.py`
- `characters.py`
- `voices.py`
- `admin.py`

## 6. React Uygulama Klasör Yapısı

```text
apps/web/src/
├─ app/
│  ├─ router.tsx
│  ├─ providers.tsx
│  └─ query-client.ts
├─ pages/
│  ├─ login/
│  ├─ dashboard/
│  ├─ projects/
│  ├─ editor/
│  └─ admin/
├─ features/
│  ├─ auth/
│  ├─ projects/
│  ├─ upload/
│  ├─ transcript/
│  ├─ translation/
│  ├─ timeline/
│  ├─ jobs/
│  ├─ render/
│  └─ library/
├─ components/
│  ├─ layout/
│  ├─ forms/
│  ├─ tables/
│  ├─ modals/
│  └─ media/
├─ stores/
│  ├─ auth-store.ts
│  ├─ project-store.ts
│  └─ timeline-store.ts
├─ services/
│  ├─ api.ts
│  └─ websocket.ts
├─ lib/
│  ├─ time.ts
│  ├─ timeline.ts
│  └─ permissions.ts
├─ types/
└─ styles/
```

React ilkeleri:

- Server state için TanStack Query
- UI state için Zustand
- Timeline state ayrı store'da
- Feature-sliced yapı
- Media editor ekranında transcript, translation ve dub görünümü aynı timeline modeline bağlanır

## 7. Job State Machine

Zorunlu state'ler:

- `PENDING`
- `QUEUED`
- `PROCESSING`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

Kurallar:

- Her state değişimi `project_events` ve `job_attempts` üzerinde iz bırakır.
- `PROCESSING -> QUEUED` geri dönüşü sadece retry için ve yeni attempt ile yapılır.
- `COMPLETED`, `FAILED`, `CANCELLED` terminal state kabul edilir.
- `CANCELLED` olan iş yeni job oluşturmadan devam ettirilmez.

## 8. Artifact Sistemi

Her üretilen şey artifact'tır.

Örnek `artifact_type` değerleri:

- `source_video`
- `proxy_video`
- `thumbnail_image`
- `source_audio`
- `dialog_audio`
- `music_audio`
- `effects_audio`
- `ambient_audio`
- `transcript_json`
- `translation_json`
- `waveform_json`
- `tts_audio`
- `lipsync_video`
- `final_render`
- `snapshot_bundle`

Artifact kuralları:

- Her artifact bir `project_id` taşır.
- İsteğe bağlı olarak `project_version_id` taşır.
- `created_by_job_id` alanı zorunluya yakın düşünülmeli.
- `parent_artifact_id` ve `artifact_links` ile türetim zinciri izlenmeli.

## 9. Audit / Event Mantığı

Her kritik aksiyon event üretir.

Örnek `event_type` değerleri:

- `PROJECT_CREATED`
- `VIDEO_UPLOADED`
- `PROXY_GENERATED`
- `TRANSCRIPT_GENERATED`
- `TRANSCRIPT_EDITED`
- `TRANSLATION_GENERATED`
- `TRANSLATION_MODIFIED`
- `VOICE_PROFILE_ASSIGNED`
- `TTS_GENERATED`
- `RENDER_STARTED`
- `RENDER_FINISHED`
- `JOB_FAILED`

Her event şu alanları taşımalı:

- `project_id`
- `actor_user_id`
- `entity_type`
- `entity_id`
- `event_type`
- `payload_json`
- `created_at`

Bu yapı tam event sourcing değildir ama event sourcing benzeri güçlü bir audit omurgası sağlar.

## 10. Provider ve Plugin Mimarisi

Amaç:

- modeli değil capability'yi kodlamak
- provider değişimini servis katmanında çözmek

Örnek capability seti:

- `ASR`
- `TRANSLATION`
- `DIARIZATION`
- `TTS`
- `LIP_SYNC`
- `SOURCE_SEPARATION`

Seçim mantığı:

- sistem default provider belirler
- proje ayarı provider override edebilir
- job düzeyinde kullanılan provider ve model `model_registry` üstünden kaydedilir

Bu sayede:

- `FasterWhisper -> WhisperX`
- `CosyVoice -> F5TTS`
- `OpenAI -> Local Ollama`

geçişleri veri modelini kırmadan yapılır.

## 11. GPU Worker İzolasyonu

Şimdiden çoklu GPU uyumlu tasarım:

```text
worker-gpu-0 -> gpu-0
worker-gpu-1 -> gpu-1
worker-gpu-n -> gpu-n
```

Kurallar:

- Job queue, worker capability ve `gpu_device_id` bilir.
- Her GPU worker kendi concurrency sınırını ilan eder.
- Ağır işler capability queue'larına ayrılır.

Örnek queue'lar:

- `media`
- `asr`
- `translation`
- `tts`
- `lipsync`
- `render`

İlk sürüm:

- tek aktif GPU işi
- ayrı media worker
- tek Redis instance

Ama veri modeli ve worker kayıt yapısı ikinci GPU'ya hazır kalır.

## 12. API Endpoint Listesi

Auth:

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`

Health:

- `GET /api/v1/health`
- `GET /api/v1/health/db`
- `GET /api/v1/health/redis`

Projects:

- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{projectId}`
- `PATCH /api/v1/projects/{projectId}`
- `DELETE /api/v1/projects/{projectId}`
- `GET /api/v1/projects/{projectId}/versions`
- `POST /api/v1/projects/{projectId}/versions`

Uploads and Artifacts:

- `POST /api/v1/projects/{projectId}/upload`
- `GET /api/v1/projects/{projectId}/artifacts`
- `GET /api/v1/projects/{projectId}/artifacts/{artifactId}`

Transcripts:

- `POST /api/v1/projects/{projectId}/transcripts/generate`
- `GET /api/v1/projects/{projectId}/transcript-segments`
- `PATCH /api/v1/projects/{projectId}/transcript-segments/{segmentId}`
- `POST /api/v1/projects/{projectId}/transcript-segments/reorder`

Translations:

- `POST /api/v1/projects/{projectId}/translations/generate`
- `GET /api/v1/projects/{projectId}/translation-segments`
- `PATCH /api/v1/projects/{projectId}/translation-segments/{segmentId}`
- `POST /api/v1/projects/{projectId}/translation-segments/{segmentId}/regenerate`

Timeline:

- `GET /api/v1/projects/{projectId}/timeline`
- `POST /api/v1/projects/{projectId}/timeline/clips`
- `PATCH /api/v1/projects/{projectId}/timeline/clips/{clipId}`
- `DELETE /api/v1/projects/{projectId}/timeline/clips/{clipId}`

Jobs:

- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{jobId}`
- `POST /api/v1/jobs/{jobId}/cancel`
- `POST /api/v1/projects/{projectId}/jobs/retry-failed`

TTS and Render:

- `POST /api/v1/projects/{projectId}/dub/generate`
- `GET /api/v1/projects/{projectId}/dub-segments`
- `POST /api/v1/projects/{projectId}/renders`
- `GET /api/v1/projects/{projectId}/renders`

Characters and Voice Library:

- `GET /api/v1/characters`
- `POST /api/v1/characters`
- `GET /api/v1/voice-profiles`
- `POST /api/v1/voice-profiles`
- `POST /api/v1/voice-profiles/{voiceProfileId}/assign`

Admin:

- `GET /api/v1/admin/jobs`
- `POST /api/v1/admin/jobs/{jobId}/cancel`
- `GET /api/v1/admin/events`
- `GET /api/v1/admin/providers`

## 13. Sprint 1 Görev Listesi

Hedef: güvenli proje iskeleti ve ingest başlangıcı

Not:

- Sprint 1-2-3 boyunca gerçek AI entegrasyonu yapılmaz.
- Sadece provider contract ve mock provider yapısı hazırlanır.

- monorepo klasörlerinin oluşturulması
- `docker-compose` ile Postgres + Redis + dev container ortamı
- FastAPI temel uygulama iskeleti
- React temel uygulama iskeleti
- PostgreSQL şema kurulumu
- `pgvector` aktivasyonu
- JWT auth
- kullanıcı ve rol yönetimi temel akışı
- proje oluşturma/listeme/detay endpoint'leri
- artifact kayıt omurgası
- source video upload endpoint'i
- storage path resolver servisi
- middleware/event-bus tabanlı audit akışı
- merkezi hata sözleşmesi
- health endpoint'leri
- checksum tabanlı duplicate detection

Sprint 1 teslim kriteri:

- editor giriş yapabilir
- proje oluşturabilir
- video yükleyebilir
- source video artifact kaydı oluşur
- audit event kayıtları oluşur

## 14. Sprint 2 Görev Listesi

Hedef: sağlam ingest ve proxy pipeline

Not:

- Proxy, metadata ve waveform üretimi media pipeline'dır.
- ASR, TTS, lip sync gibi gerçek AI entegrasyonları Sprint 2'de de devreye girmez.

- ffmpeg servis katmanı
- video metadata extraction
- duration / codec / fps / resolution analizi
- 720p proxy üretimi
- thumbnail üretimi
- source audio extraction
- waveform üretimi
- artifact linkage zinciri
- media worker queue entegrasyonu
- job attempts ve retry mantığı
- upload sonrası otomatik ingest job akışı

Sprint 2 teslim kriteri:

- yüklenen video için proxy oluşur
- metadata DB'de görünür
- waveform görünür
- iş durumları UI'de izlenir

## 15. Sprint 3 Görev Listesi

Hedef: ilk kullanılabilir transcript ve timeline omurgası

Not:

- Sprint 3 sonunda provider contract kullanılabilir hale gelir.
- Gerçek ASR motoru entegrasyonu sonraki sprintte açılır.

- Faster-Whisper provider entegrasyonu
- ASR job pipeline
- transcript artifact üretimi
- `transcript_segments` kayıtları
- transcript edit endpoint'leri
- translation segment placeholder yapısı
- timeline read model
- editor ekranında transcript segment listesi
- segment onay/düzenleme akışı
- transcript kaynaklı audit event'ler

Sprint 3 teslim kriteri:

- kullanıcı video yükler
- transcript job başlatır
- zaman kodlu segmentleri görür
- segmentleri düzenler
- timeline omurgası görünür hale gelir

Bu noktadan sonra sistem ilk kez gerçek kullanım değerine ulaşır.
