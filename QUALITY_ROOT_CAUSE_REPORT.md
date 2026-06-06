# Sprint 32 Quality Root Cause Report

Date: 2026-06-05

Scope: root cause analysis only. No new provider, feature, or schema change was added.

Analyzed project: `019e9868-7978-7523-9419-57f9c4b19ea0` (`Sprint 29 01 general - Final`)

Note: newer local projects existed, but this was the latest project found with the full real chain including `LIPSYNC_VIDEO`, `FINAL_DUB_AUDIO`, CosyVoice TTS, and `FINAL_RENDER`. Therefore this is the correct sample for translation + voice clone + MuseTalk quality RCA.

## Executive Decision

Result: FAIL

The final render is technically complete, but not product-quality. The biggest quality loss is not a single provider failure. It is a cascade:

1. Translation/timing adaptation loses meaning and over-compresses Turkish text.
2. CosyVoice produces speech, but generated TTS duration is far shorter than the source speech timeline.
3. MuseTalk receives sparse/short audio and also outputs a visually degraded, temporally suspicious video.

Estimated quality-loss distribution:

| Stage | Share | Reason |
| --- | ---: | --- |
| Translation and duration adaptation | 45% | 3 of 4 segments have major semantic errors; translated speech is too short. |
| TTS / voice clone timing and identity | 30% | Reference sample is good, but TTS total speech is only 44.5% of source speech duration; acoustic profile drifts from reference. |
| MuseTalk lip sync/video output | 25% | Duration/fps are correct, but frame comparisons show scene/time mismatch and strong visual degradation. |

## Active Real Providers

| Capability | Provider | Mock |
| --- | --- | --- |
| ASR | faster_whisper | false |
| Translation | ollama / `gemma3:4b` metadata | false |
| Diarization | pyannote | false |
| Voice clone | cosyvoice | false |
| Lip sync | musetalk | false |

No mock provider was identified in the analyzed final chain.

## Artifact Overview

| Artifact | Duration | Size | Key Metadata |
| --- | ---: | ---: | --- |
| SOURCE_VIDEO | 26.64s | 72,763,978 bytes | 3840x2160, 25 fps |
| PROXY_VIDEO | 26.64s | 5,459,269 bytes | 1280x720, 25 fps, 666 frames, video bitrate ~1502 kb/s |
| VOICE_SAMPLE_AUDIO | 24.98s | 1,101,692 bytes | normalized=true, silence_trimmed=true, sample_quality_score=1.00 |
| VOICE_REFERENCE_AUDIO | 24.98s | 1,101,692 bytes | reference_audio_artifact_id=`019e9869-18f3-7d85-8f58-38aa22607415` |
| TTS_AUDIO total | 11.34s | 500,400 bytes | provider=cosyvoice, device=cuda, cloned=true |
| FINAL_DUB_AUDIO | 26.64s | 1,174,902 bytes | padded to video duration, voiced ratio ~0.373 |
| LIPSYNC_VIDEO | 26.64s | 575,142 bytes | provider=musetalk, mock=false, 1280x720, 25 fps, 666 frames |
| FINAL_RENDER | 26.64s | 965,896 bytes | 1920x1080, 25 fps, audio stream count=1, source=LIPSYNC_VIDEO |

## Transcript Review

ASR looks mostly usable. The Serbian transcript is coherent and confidence is high enough for this sample:

| # | Time | Speaker | Confidence | Transcript |
| --- | --- | --- | ---: | --- |
| 1 | 0-6340 ms | SPEAKER_00 | 0.951 | Znam da te nervira što tvoj novac stoji na računu samo zato što si preporačio broj dnevnih isplata. |
| 2 | 6460-11920 ms | SPEAKER_00 | 0.918 | Dok te drugi ograničavaju, mi rušimo taj zastrli sistem. |
| 3 | 12360-17520 ms | SPEAKER_00 | 0.926 | Pod nas ne postoji dnevna kota za tvoj novac. |
| 4 | 17660-26180 ms | SPEAKER_00 | 0.871 | Ne dozvoli da tvoj novac spava na tuđem računu, pređi na brahiz i raspolaži svojim dobitkom bez granica. |

ASR issue: the brand/name near `brahiz` may be uncertain, but this is not the main quality blocker.

## Translation Report

| # | Source | Turkish Output | Human Evaluation |
| --- | --- | --- | --- |
| 1 | Znam da te nervira što tvoj novac stoji na računu samo zato što si preporačio broj dnevnih isplata. | Para akmıyor çünkü harcamalarını durdurdun. | Bad. The source says money is stuck in the account because daily withdrawal count was exceeded. The Turkish output incorrectly says spending was stopped. |
| 2 | Dok te drugi ograničavaju, mi rušimo taj zastrli sistem. | Sanki sen de başkasını kısıtlıyorsan, biz onu yok ederiz. | Bad. The source says others limit you and we break that outdated system. The Turkish output changes the subject and meaning. |
| 3 | Pod nas ne postoji dnevna kota za tvoj novac. | Para sana hiç bitmiyor. | Bad. The source says there is no daily quota for your money. The Turkish output says money never runs out, a different claim. |
| 4 | Ne dozvoli da tvoj novac spava na tuđem računu, pređi na brahiz i raspolaži svojim dobitkom bez granica. | Paranın başka birinin hesabında kalmaması lazım, Braxis’i kullanıp karını istediğin gibi yönetmelisin. | Partly acceptable. The general intent survives, but wording is less natural and brand handling is uncertain. |

Translation conclusion: this is the largest semantic quality loss. The duration-aware translation appears to compress too aggressively and sacrifices meaning.

## Timeline and Duration Fit

| # | Source Duration | Translated Duration Estimate | TTS Duration | Main Problem |
| --- | ---: | ---: | ---: | --- |
| 1 | 6340 ms | 2960 ms | 3750 ms | Meaning changed; speech too short for source slot. |
| 2 | 5460 ms | 3700 ms | 1938 ms | Meaning changed; TTS much too short. |
| 3 | 5160 ms | 1480 ms | 2798 ms | Meaning changed; adaptation collapsed content. |
| 4 | 8520 ms | 7030 ms | 2856 ms | TTS much shorter than even the translated estimate. |

Source speech duration: 25.48s

TTS speech duration total: 11.34s

TTS/source speech ratio: 44.5%

Final dub duration is correctly padded to 26.64s, but the audio bed contains too much silence or low-energy space. This directly hurts voice naturalness and makes lip sync look worse even if MuseTalk itself runs.

## Voice Clone Report

Reference sample:

| Metric | Value |
| --- | ---: |
| Duration | 24.98s |
| RMS | -17.60 dBFS |
| Peak | 0.8413 |
| Voiced ratio > -40 dB | 0.984 |
| Sample quality score | 1.00 |
| normalized | true |
| silence_trimmed | true |

TTS outputs:

| # | Duration | RMS | Spectral Centroid | Delta vs Reference |
| --- | ---: | ---: | ---: | --- |
| 1 | 3.750s | -14.77 dBFS | 1740.6 Hz | +2.83 dB, +328.0 Hz |
| 2 | 1.939s | -15.78 dBFS | 2687.0 Hz | +1.82 dB, +1274.4 Hz |
| 3 | 2.798s | -14.26 dBFS | 2431.5 Hz | +3.34 dB, +1018.9 Hz |
| 4 | 2.856s | -15.67 dBFS | 2071.2 Hz | +1.93 dB, +658.6 Hz |

Voice clone conclusion: the reference sample itself is not the main failure. It is long enough, normalized, and mostly voiced. The perceived mismatch likely comes from cross-lingual timbre transfer limits plus overly short/generated Turkish utterances. Segment 2 and 3 have a large spectral shift from the reference, which supports the human complaint that the clone does not sound like the character.

## MuseTalk Report

MuseTalk metadata says the real provider ran:

| Field | Value |
| --- | --- |
| provider | musetalk |
| mock | false |
| quality_preset | source-fps-720p |
| processing_time_ms | 152,138 |
| face_crop_detection_status | completed |
| input video | 3840x2160, 25 fps, 666 frames |
| input audio | 26.64s |
| output video | 1280x720, 25 fps, 666 frames |
| output duration | 26.64s |

Video metrics:

| Comparison | Value |
| --- | ---: |
| Proxy video bitrate | ~1502 kb/s |
| Lip sync video bitrate | ~134 kb/s |
| Final render video bitrate | ~250 kb/s |
| Proxy vs lip sync SSIM All | 0.703 |
| Proxy vs lip sync PSNR Average | 14.72 dB |

Frame comparison outputs:

| Timestamp | Comparison Image |
| --- | --- |
| 3s | `storage/tmp/sprint32_frames/compare_003.jpg` |
| 10s | `storage/tmp/sprint32_frames/compare_010.jpg` |
| 18s | `storage/tmp/sprint32_frames/compare_018.jpg` |

Manual frame review: proxy/source frames and lipsync frames do not appear to show the same visual moment. At 3s, proxy/source shows a phone close-up while lipsync shows the person in a different scene/pose. At 10s and 18s the mismatch persists. This suggests MuseTalk output is not preserving the original visual timeline, or it is using/generated from an incorrectly aligned intermediate. This is more severe than ordinary mouth-sync imperfection.

MuseTalk conclusion: duration and frame count are technically correct, but visual correctness is not. There are two blockers:

1. Upstream audio timing is sparse and too short for the source timeline.
2. MuseTalk output appears temporally/content-wise mismatched and heavily compressed.

## Final Render Check

| Metric | Value |
| --- | ---: |
| Duration | 26.64s |
| Resolution | 1920x1080 |
| FPS | 25 |
| Frame count | 666 |
| Audio stream count | 1 |
| Video source artifact | LIPSYNC_VIDEO |
| Audio duration | 26.64s |

Render duration handling is correct in this sample. The render did not collapse to the short TTS duration. The quality failure is upstream of final render, not in final duration preservation.

## Root Cause Ranking

Top 3 quality problems:

1. Turkish translation is semantically wrong in most segments.
2. TTS duration is far too short: 11.34s of generated speech for 25.48s of source speech.
3. MuseTalk output does not visually preserve the source timeline and is encoded at very low bitrate.

Top 3 improvement recommendations:

1. Fix translation adaptation to preserve meaning first, then fit duration. Current duration pressure is deleting or changing claims.
2. Add a timing validation gate before audio mix/lip sync: block or flag segments where TTS duration is far shorter than source duration unless an explicit retiming strategy is applied.
3. Investigate MuseTalk input/output assembly and encoding: verify exact frame order, source path, temp directory reuse, crop restoration, and output bitrate/CRF before tuning lip-sync quality presets.

## Final Verdict

FAIL

The pipeline is technically alive and uses real providers, but the produced video is not user-deliverable. The primary root cause is translation/timing adaptation, followed by CosyVoice/TTS duration and identity drift, with MuseTalk adding a separate severe visual-timeline/encoding problem.
