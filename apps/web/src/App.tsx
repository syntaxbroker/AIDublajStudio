import type { FormEvent, ReactElement, ReactNode } from "react";
import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  assignCharacterVoiceProfile,
  bulkClearJobs,
  clearJob,
  createClonedVoiceProfileFromSample,
  createProject,
  extractCharacterVoiceSample,
  fetchArtifactBlob,
  generateCharactersFromSpeakers,
  getApiBaseUrl,
  getArtifactContentUrl,
  getJobLogs,
  getProject,
  getProviderStatus,
  getTimeline,
  listVoiceProfiles,
  listProjects,
  login,
  me,
  renameCharacter,
  retryJob,
  sortCharacters,
  startAudioMix,
  startLipSync,
  startRender,
  startTts,
  updateTimelineClip,
  uploadProjectVideo,
} from "./lib/api";
import { clearStoredToken, getStoredToken, setStoredToken } from "./lib/storage";
import type { Job, JobLogs, ProjectDetail, ProjectListItem, ProviderStatusResponse, TimelineResponse, User, VoiceProfile } from "./types";

type AuthState = {
  token: string | null;
  user: User | null;
};

type TimelineDraft = {
  text: string;
  translation_text: string;
  character_id: string;
  speaker_label: string;
};

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString("tr-TR");
}

function formatMs(value: number): string {
  const totalSeconds = Math.floor(value / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const ms = value % 1000;
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}.${ms.toString().padStart(3, "0")}`;
}

function jobIsActive(state: string): boolean {
  return state === "PENDING" || state === "QUEUED" || state === "PROCESSING";
}

function formatJobDuration(job: Job): string {
  const start = job.started_at || job.queued_at || job.created_at;
  const end = job.completed_at || job.cancelled_at || (job.state === "FAILED" ? job.updated_at : new Date().toISOString());
  if (!start || !end) {
    return "-";
  }
  const durationMs = Math.max(new Date(end).getTime() - new Date(start).getTime(), 0);
  const totalSeconds = Math.floor(durationMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}s ${minutes.toString().padStart(2, "0")}d ${seconds.toString().padStart(2, "0")}sn`
    : `${minutes}d ${seconds.toString().padStart(2, "0")}sn`;
}

function dismissedAlertStorageKey(projectId: string): string {
  return `aidublaj:dismissed-alerts:${projectId}`;
}

function loadDismissedAlertIds(projectId: string): Set<string> {
  try {
    return new Set(JSON.parse(window.localStorage.getItem(dismissedAlertStorageKey(projectId)) || "[]"));
  } catch {
    return new Set();
  }
}

function saveDismissedAlertIds(projectId: string, values: Set<string>) {
  window.localStorage.setItem(dismissedAlertStorageKey(projectId), JSON.stringify([...values]));
}

function getApiRootUrl(): string {
  const base = getApiBaseUrl();
  return base.endsWith("/api/v1") ? base.slice(0, -"/api/v1".length) : base;
}

function getNextStepMessage(detail: ProjectDetail): string {
  const hasSourceVideo = detail.artifacts.some((artifact) => artifact.artifact_type === "SOURCE_VIDEO");
  const hasTimeline = detail.timeline_clips.length > 0;
  const hasDubSegments = detail.dub_segments.length > 0;
  const hasFinalDubAudio = detail.artifacts.some((artifact) => artifact.artifact_type === "FINAL_DUB_AUDIO");
  const hasLipSyncVideo = detail.artifacts.some((artifact) => artifact.artifact_type === "LIPSYNC_VIDEO");
  const hasFinalRender = detail.artifacts.some((artifact) => artifact.artifact_type === "FINAL_RENDER");
  const activeJob = detail.jobs.find((job) => jobIsActive(job.state));

  if (!hasSourceVideo) {
    return "Sıradaki adım: video upload edin.";
  }
  if (activeJob) {
    return `Sistem şu anda ${activeJob.job_type} çalıştırıyor. İş bitene kadar otomatik yenileme aktif.`;
  }
  if (!hasTimeline) {
    return "Sıradaki adım: transcript ve timeline oluşmasını bekleyin.";
  }
  if (!hasDubSegments) {
    return "Sıradaki adım: TTS Başlat ile Türkçe ses segmentlerini üretin.";
  }
  if (!hasFinalDubAudio) {
    return "Sıradaki adım: Audio Mix Başlat ile tek Türkçe dub audio dosyası üretin.";
  }
  if (!hasLipSyncVideo) {
    return "Sıradaki adım: Lip Sync Başlat ile dudak senkronlu video üretin.";
  }
  if (!hasFinalRender) {
    return "Sıradaki adım: Render Başlat ile final MP4 üretin.";
  }
  return "Final render hazır. MP4 dosyasını açabilir veya indirebilirsiniz.";
}

function extractMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Bilinmeyen hata";
}

export function App() {
  const [auth, setAuth] = useState<AuthState>({ token: getStoredToken(), user: null });
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    const token = getStoredToken();
    if (!token) {
      setBooting(false);
      return;
    }

    me(token)
      .then((user) => {
        setAuth({ token, user });
      })
      .catch(() => {
        clearStoredToken();
        setAuth({ token: null, user: null });
      })
      .finally(() => {
        setBooting(false);
      });
  }, []);

  const handleLoggedIn = (token: string, user: User) => {
    setStoredToken(token);
    setAuth({ token, user });
  };

  const handleLogout = () => {
    clearStoredToken();
    setAuth({ token: null, user: null });
  };

  if (booting) {
    return <div className="page-shell"><div className="panel">Oturum kontrol ediliyor...</div></div>;
  }

  return (
    <Routes>
      <Route
        path="/login"
        element={
          auth.token && auth.user ? (
            <Navigate to="/projects" replace />
          ) : (
            <LoginPage onLoggedIn={handleLoggedIn} />
          )
        }
      />
      <Route
        path="/projects"
        element={
          <ProtectedRoute auth={auth}>
            <ProjectsPage auth={auth} onLogout={handleLogout} />
          </ProtectedRoute>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <ProtectedRoute auth={auth}>
            <ProjectDetailPage auth={auth} onLogout={handleLogout} />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to={auth.token ? "/projects" : "/login"} replace />} />
    </Routes>
  );
}

function ProtectedRoute({ auth, children }: { auth: AuthState; children: ReactElement }) {
  if (!auth.token || !auth.user) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function AppHeader({ auth, onLogout }: { auth: AuthState; onLogout: () => void }) {
  const apiRootUrl = getApiRootUrl();
  const [providerStatus, setProviderStatus] = useState<ProviderStatusResponse | null>(null);
  const [openModal, setOpenModal] = useState<"api" | "providers" | null>(null);

  useEffect(() => {
    void getProviderStatus(auth.token).then(setProviderStatus).catch(() => setProviderStatus(null));
  }, [auth.token]);

  return (
    <>
      <header className="app-header">
        <div>
          <p className="eyebrow">AI Dublaj Studio</p>
          <h1>Pipeline Control Room</h1>
          <div className="header-tool-buttons">
            <button className="ghost-button" type="button" onClick={() => setOpenModal("api")}>API Status</button>
            <button
              className={providerStatus?.has_mock_provider ? "ghost-button warning-button" : "ghost-button"}
              type="button"
              onClick={() => setOpenModal("providers")}
            >
              Provider Status
            </button>
          </div>
        </div>
        <div className="header-actions">
          <div className="user-badge">
            <strong>{auth.user?.full_name}</strong>
            <span>{auth.user?.role}</span>
          </div>
          <button className="ghost-button" onClick={onLogout}>Logout</button>
        </div>
      </header>
      {openModal === "api" ? (
        <InfoModal title="API Status" onClose={() => setOpenModal(null)}>
          <p className="muted">API: {getApiBaseUrl()}</p>
          <div className="modal-link-list">
            <a className="inline-link" href={`${apiRootUrl}/api/v1/health`} target="_blank" rel="noreferrer">/health</a>
            <a className="inline-link" href={`${apiRootUrl}/api/v1/health/db`} target="_blank" rel="noreferrer">/health/db</a>
            <a className="inline-link" href={`${apiRootUrl}/api/v1/health/redis`} target="_blank" rel="noreferrer">/health/redis</a>
            <a className="inline-link" href={`${apiRootUrl}/api/v1/runtime/providers`} target="_blank" rel="noreferrer">/runtime/providers</a>
          </div>
        </InfoModal>
      ) : null}
      {openModal === "providers" ? (
        <InfoModal title="Provider Status" onClose={() => setOpenModal(null)}>
          {providerStatus ? (
            <div className={providerStatus.has_mock_provider ? "provider-banner provider-banner-warning" : "provider-banner"}>
              <div>
                <p>{providerStatus.providers.map((item) => `${item.capability}=${item.provider}`).join(" | ")}</p>
              </div>
              {providerStatus.has_mock_provider ? (
                <p>{providerStatus.warning || "Mock provider active. UI processing is blocked unless ALLOW_MOCK_PROVIDERS=true; mock TTS can produce beep audio and fake durations."}</p>
              ) : (
                <p>All visible providers are non-mock.</p>
              )}
            </div>
          ) : (
            <p className="muted">Provider status yÃ¼klenemedi.</p>
          )}
        </InfoModal>
      ) : null}
    </>
  );
}

function InfoModal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="info-modal-title" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2 id="info-modal-title">{title}</h2>
          <button className="ghost-button" type="button" onClick={onClose}>Close</button>
        </div>
        <div className="modal-body">{children}</div>
      </section>
    </div>
  );
}

function LoginPage({ onLoggedIn }: { onLoggedIn: (token: string, user: User) => void }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("editor@example.com");
  const [password, setPassword] = useState("editor123");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const tokenResponse = await login(email, password);
      const user = await me(tokenResponse.access_token);
      onLoggedIn(tokenResponse.access_token, user);
      navigate("/projects");
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-shell">
      <div className="login-panel">
        <p className="eyebrow">Sprint 9</p>
        <h1>Minimal Web Arayüzü</h1>
        <p className="muted">Mevcut backend pipeline’ını tarayıcıdan test etmek için giriş yapın.</p>
        <form className="stack" onSubmit={handleSubmit}>
          <label>
            <span>E-posta</span>
            <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required />
          </label>
          <label>
            <span>Şifre</span>
            <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required />
          </label>
          {error ? <div className="error-box">{error}</div> : null}
          <button className="primary-button" type="submit" disabled={loading}>
            {loading ? "Giriş yapılıyor..." : "Giriş Yap"}
          </button>
        </form>
      </div>
    </div>
  );
}

function ProjectsPage({ auth, onLogout }: { auth: AuthState; onLogout: () => void }) {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    source_language: "auto",
    target_language: "tr",
  });

  const loadProjects = async () => {
    if (!auth.token) return;
    setLoading(true);
    setError(null);
    try {
      const items = await listProjects(auth.token);
      setProjects(items);
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadProjects();
  }, [auth.token]);

  const handleCreateProject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!auth.token) return;
    setCreating(true);
    setError(null);
    try {
      const project = await createProject(auth.token, {
        name: form.name,
        description: form.description || undefined,
        source_language: form.source_language || undefined,
        target_language: form.target_language,
      });
      setForm({
        name: "",
        description: "",
        source_language: "auto",
        target_language: "tr",
      });
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="page-shell">
      <AppHeader auth={auth} onLogout={onLogout} />
      <div className="toolbar">
        <div>
          <h2>Projeler</h2>
          <p className="muted">Upload ve pipeline testleri için proje oluşturun veya mevcut projeye girin.</p>
        </div>
        <button className="ghost-button" onClick={() => void loadProjects()} disabled={loading}>
          {loading ? "Yükleniyor..." : "Refresh"}
        </button>
      </div>

      <div className="grid two-columns">
        <section className="panel">
          <h3>Yeni Proje</h3>
          <form className="stack" onSubmit={handleCreateProject}>
            <label>
              <span>Proje adı</span>
              <input
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                minLength={2}
                required
              />
            </label>
            <label>
              <span>Açıklama</span>
              <textarea
                rows={3}
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <div className="inline-fields">
              <label>
                <span>Kaynak dil</span>
                <select
                  value={form.source_language}
                  onChange={(event) => setForm((current) => ({ ...current, source_language: event.target.value }))}
                >
                  <option value="en">en</option>
                  <option value="sr">sr</option>
                  <option value="auto">auto</option>
                </select>
              </label>
              <label>
                <span>Hedef dil</span>
                <select
                  value={form.target_language}
                  onChange={(event) => setForm((current) => ({ ...current, target_language: event.target.value }))}
                >
                  <option value="tr">tr</option>
                </select>
              </label>
            </div>
            <button className="primary-button" type="submit" disabled={creating}>
              {creating ? "Oluşturuluyor..." : "Proje Oluştur"}
            </button>
          </form>
          {error ? <div className="error-box">{error}</div> : null}
        </section>

        <section className="panel">
          <h3>Proje Listesi</h3>
          {loading ? <p className="muted">Projeler yükleniyor...</p> : null}
          {!loading && projects.length === 0 ? <p className="muted">Henüz proje yok.</p> : null}
          <div className="list project-list-scroll">
            {projects.map((project) => (
              <button
                key={project.id}
                className="list-item"
                onClick={() => navigate(`/projects/${project.id}`)}
                type="button"
              >
                <div>
                  <strong>{project.name}</strong>
                  <p>{project.description || "Açıklama yok"}</p>
                </div>
                <div className="list-meta">
                  <span>{project.source_language || "auto"} → {project.target_language}</span>
                  <span>{project.status}</span>
                </div>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function ProjectDetailPage({ auth, onLogout }: { auth: AuthState; onLogout: () => void }) {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [characterActionLoading, setCharacterActionLoading] = useState(false);
  const [pipelineAction, setPipelineAction] = useState<"tts" | "audio-mix" | "lip-sync" | "render" | null>(null);
  const [jobActionId, setJobActionId] = useState<string | null>(null);
  const [jobLogsModal, setJobLogsModal] = useState<{ job: Job; payload: JobLogs | null; loading: boolean; error: string | null } | null>(null);
  const [timelineSavingId, setTimelineSavingId] = useState<string | null>(null);
  const [finalRenderPreviewUrl, setFinalRenderPreviewUrl] = useState<string | null>(null);
  const [artifactActionError, setArtifactActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dismissedFailedJobIds, setDismissedFailedJobIds] = useState<Set<string>>(() => new Set());
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);
  const [voiceProfiles, setVoiceProfiles] = useState<VoiceProfile[]>([]);
  const [renameDrafts, setRenameDrafts] = useState<Record<string, { display_name: string; description: string }>>({});
  const [voiceProfileDrafts, setVoiceProfileDrafts] = useState<Record<string, string>>({});
  const [timelineDrafts, setTimelineDrafts] = useState<Record<string, TimelineDraft>>({});

  const token = auth.token;

  const syncDrafts = (project: ProjectDetail, timelinePayload: TimelineResponse) => {
    setRenameDrafts(
      Object.fromEntries(
        project.characters.map((character) => [
          character.id,
          {
            display_name: character.display_name,
            description: character.description ?? "",
          },
        ]),
      ),
    );

    setVoiceProfileDrafts(
      Object.fromEntries(
        project.characters.map((character) => [character.id, character.assigned_voice_profile_id ?? ""]),
      ),
    );

    setTimelineDrafts(
      Object.fromEntries(
        timelinePayload.clips.map((clip) => [
          clip.id,
          {
            text: clip.text ?? "",
            translation_text: clip.translation_text ?? "",
            character_id: clip.character_id ?? "",
            speaker_label: clip.speaker_label ?? "",
          },
        ]),
      ),
    );
  };

  const refreshDetail = async (mode: "initial" | "refresh" = "refresh") => {
    if (!token || !projectId) {
      return;
    }

    if (mode === "initial") {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError(null);

    try {
      const [project, timelinePayload, availableVoiceProfiles] = await Promise.all([
        getProject(token, projectId),
        getTimeline(token, projectId),
        listVoiceProfiles(token),
      ]);
      setDetail(project);
      setTimeline(timelinePayload);
      setVoiceProfiles(availableVoiceProfiles);
      syncDrafts(project, timelinePayload);
      setLastRefreshedAt(new Date().toISOString());
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    void refreshDetail("initial");
  }, [projectId, token]);

  useEffect(() => {
    if (!projectId) {
      setDismissedFailedJobIds(new Set());
      return;
    }
    setDismissedFailedJobIds(loadDismissedAlertIds(projectId));
  }, [projectId]);

  useEffect(() => {
    if (!detail || !token || !projectId) {
      return;
    }
    const hasActiveJobs = detail.jobs.some((job) => jobIsActive(job.state));
    if (!hasActiveJobs) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void refreshDetail();
    }, 4000);
    return () => window.clearInterval(intervalId);
  }, [detail, token, projectId]);

  useEffect(() => {
    if (!token || !jobLogsModal || !jobIsActive(jobLogsModal.job.state)) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadJobLogs(jobLogsModal.job);
    }, 5000);
    return () => window.clearInterval(intervalId);
  }, [token, jobLogsModal?.job.id, jobLogsModal?.job.state]);

  useEffect(() => {
    return () => {
      if (finalRenderPreviewUrl) {
        URL.revokeObjectURL(finalRenderPreviewUrl);
      }
    };
  }, [finalRenderPreviewUrl]);

  const dismissFailedJobAlert = (jobId: string) => {
    if (!projectId) {
      return;
    }
    setDismissedFailedJobIds((current) => {
      const next = new Set(current);
      next.add(jobId);
      saveDismissedAlertIds(projectId, next);
      return next;
    });
  };

  const loadJobLogs = async (job: Job) => {
    if (!token) return;
    setJobLogsModal((current) => current && current.job.id === job.id ? { ...current, loading: true, error: null } : current);
    try {
      const payload = await getJobLogs(token, job.id);
      setJobLogsModal({ job, payload, loading: false, error: null });
    } catch (err) {
      setJobLogsModal({ job, payload: null, loading: false, error: extractMessage(err) });
    }
  };

  const openJobLogs = (job: Job) => {
    setJobLogsModal({ job, payload: null, loading: true, error: null });
    void loadJobLogs(job);
  };

  const retryPipelineJob = async (job: Job) => {
    if (!token) return;
    setJobActionId(job.id);
    setError(null);
    try {
      await retryJob(token, job.id);
      setNotice(`${job.job_type} retry kuyruğa alındı.`);
      await refreshDetail();
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setJobActionId(null);
    }
  };

  const clearPipelineJob = async (job: Job) => {
    if (!token) return;
    setJobActionId(job.id);
    setError(null);
    try {
      await clearJob(token, job.id);
      setNotice(`${job.job_type} listeden temizlendi.`);
      await refreshDetail();
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setJobActionId(null);
    }
  };

  const clearPipelineJobsByState = async (state: "COMPLETED" | "FAILED") => {
    if (!token || !projectId) return;
    setJobActionId(`bulk-${state}`);
    setError(null);
    try {
      const payload = await bulkClearJobs(token, projectId, state);
      setNotice(`${payload.archived_count} ${state} job listeden temizlendi.`);
      await refreshDetail();
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setJobActionId(null);
    }
  };

  const handleUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || !projectId) return;
    const input = event.currentTarget.elements.namedItem("video") as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) {
      setError("Yüklenecek bir video seçin.");
      return;
    }
    setUploading(true);
    setError(null);
    setArtifactActionError(null);
    setNotice(null);
    try {
      const project = await uploadProjectVideo(token, projectId, file);
      setDetail(project);
      setNotice("Upload tamamlandı. Sistem şimdi ingest, transcript ve translation adımlarını otomatik çalıştırıyor.");
      await refreshDetail();
      event.currentTarget.reset();
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setUploading(false);
    }
  };

  const handleGenerateCharacters = async () => {
    if (!token || !projectId) return;
    setCharacterActionLoading(true);
    setError(null);
    setArtifactActionError(null);
    setNotice(null);
    try {
      const project = await generateCharactersFromSpeakers(token, projectId);
      setDetail(project);
      await refreshDetail();
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setCharacterActionLoading(false);
    }
  };

  const saveCharacterDraftIfChanged = async (characterId: string): Promise<ProjectDetail | null> => {
    if (!token || !projectId || !detail) {
      return null;
    }
    const character = detail.characters.find((item) => item.id === characterId);
    const draft = renameDrafts[characterId];
    if (!character || !draft) {
      return null;
    }
    const nextName = draft.display_name.trim();
    const nextDescription = draft.description || null;
    const currentDescription = character.description || null;
    if (!nextName) {
      throw new Error("Karakter adı boş olamaz.");
    }
    if (nextName === character.display_name && nextDescription === currentDescription) {
      return null;
    }
    return renameCharacter(token, projectId, characterId, {
      display_name: nextName,
      description: nextDescription,
    });
  };

  const handleRenameCharacter = async (characterId: string) => {
    if (!token || !projectId) return;
    const draft = renameDrafts[characterId];
    if (!draft) return;
    setCharacterActionLoading(true);
    setError(null);
    setArtifactActionError(null);
    setNotice(null);
    try {
      const project = await saveCharacterDraftIfChanged(characterId);
      if (project) {
        setDetail(project);
      }
      await refreshDetail();
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setCharacterActionLoading(false);
    }
  };

  const handleAssignVoiceProfile = async (characterId: string) => {
    if (!token || !projectId) return;
    const voiceProfileId = voiceProfileDrafts[characterId];
    if (!voiceProfileId) {
      setError("Bir voice profile seçin.");
      return;
    }
    setCharacterActionLoading(true);
    setError(null);
    setArtifactActionError(null);
    setNotice(null);
    try {
      const project = await assignCharacterVoiceProfile(token, projectId, characterId, voiceProfileId);
      setDetail(project);
      setNotice("Voice profile atandı. TTS yeniden çalıştırıldığında bu seçim kullanılacak.");
      await refreshDetail();
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setCharacterActionLoading(false);
    }
  };

  const handleExtractVoiceSample = async (characterId: string) => {
    if (!token || !projectId) return;
    setCharacterActionLoading(true);
    setError(null);
    setArtifactActionError(null);
    setNotice(null);
    try {
      const savedProject = await saveCharacterDraftIfChanged(characterId);
      if (savedProject) {
        setDetail(savedProject);
      }
      const project = await extractCharacterVoiceSample(token, projectId, characterId);
      setDetail(project);
      setNotice("Ses örneği çıkarma işi kuyruğa alındı. Media worker tamamlayınca sample artifact görünecek.");
      await refreshDetail();
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setCharacterActionLoading(false);
    }
  };

  const handleCreateClonedProfile = async (characterId: string) => {
    if (!token || !projectId) return;
    setCharacterActionLoading(true);
    setError(null);
    setArtifactActionError(null);
    setNotice(null);
    try {
      const savedProject = await saveCharacterDraftIfChanged(characterId);
      if (savedProject) {
        setDetail(savedProject);
      }
      const project = await createClonedVoiceProfileFromSample(token, projectId, characterId);
      setDetail(project);
      setNotice("Klon ses profili oluşturuldu ve karaktere atandı.");
      await refreshDetail();
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setCharacterActionLoading(false);
    }
  };

  const handleSaveClip = async (clipId: string) => {
    if (!token || !projectId) return;
    const draft = timelineDrafts[clipId];
    if (!draft) return;
    setTimelineSavingId(clipId);
    setError(null);
    setArtifactActionError(null);
    setNotice(null);
    try {
      const timelinePayload = await updateTimelineClip(token, projectId, clipId, {
        text: draft.text,
        translation_text: draft.translation_text,
        character_id: draft.character_id || null,
        speaker_label: draft.speaker_label || null,
      });
      setTimeline(timelinePayload);
      setTimelineDrafts((current) => {
        const next = { ...current };
        for (const clip of timelinePayload.clips) {
          next[clip.id] = {
            text: clip.text ?? "",
            translation_text: clip.translation_text ?? "",
            character_id: clip.character_id ?? "",
            speaker_label: clip.speaker_label ?? "",
          };
        }
        return next;
      });
      const project = await getProject(token, projectId);
      setDetail(project);
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setTimelineSavingId(null);
    }
  };

  const runPipelineAction = async (action: "tts" | "audio-mix" | "lip-sync" | "render") => {
    if (!token || !projectId) return;
    if (action === "render" && !detail.artifacts.some((artifact) => artifact.artifact_type === "LIPSYNC_VIDEO")) {
      setError("Render için önce Lip Sync çalıştırın. LIPSYNC_VIDEO yoksa render Source Video fallback kullanır.");
      return;
    }
    setPipelineAction(action);
    setError(null);
    setArtifactActionError(null);
    setNotice(null);
    try {
      let project: ProjectDetail;
      if (action === "tts") {
        project = await startTts(token, projectId);
      } else if (action === "audio-mix") {
        project = await startAudioMix(token, projectId);
      } else if (action === "lip-sync") {
        project = await startLipSync(token, projectId);
      } else {
        project = await startRender(token, projectId);
      }
      setDetail(project);
      if (action === "tts") {
        setNotice("TTS başlatıldı. Segment sesleri üretiliyor.");
      } else if (action === "audio-mix") {
        setNotice("Audio mix başlatıldı. Tek Türkçe dub audio hazırlanıyor.");
      } else if (action === "lip-sync") {
        setNotice("Lip Sync başlatıldı. Dudak senkronlu video hazırlanıyor.");
      } else {
        setNotice("Render başlatıldı. Final MP4 hazırlanıyor.");
      }
      await refreshDetail();
    } catch (err) {
      setError(extractMessage(err));
    } finally {
      setPipelineAction(null);
    }
  };

  const handleOpenArtifact = async (artifactId: string) => {
    if (!token || !projectId) return;
    setArtifactActionError(null);
    try {
      const blob = await fetchArtifactBlob(token, projectId, artifactId);
      if (finalRenderPreviewUrl) {
        URL.revokeObjectURL(finalRenderPreviewUrl);
      }
      const url = URL.createObjectURL(blob);
      setFinalRenderPreviewUrl(url);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setArtifactActionError(extractMessage(err));
    }
  };

  const handleDownloadArtifact = async (artifactId: string, fileName: string) => {
    if (!token || !projectId) return;
    setArtifactActionError(null);
    try {
      const blob = await fetchArtifactBlob(token, projectId, artifactId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = fileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setArtifactActionError(extractMessage(err));
    }
  };

  if (!projectId) {
    return <Navigate to="/projects" replace />;
  }

  if (loading) {
    return (
      <div className="page-shell">
        <AppHeader auth={auth} onLogout={onLogout} />
        <div className="panel">Proje yükleniyor...</div>
      </div>
    );
  }

  if (!detail || !timeline) {
    return (
      <div className="page-shell">
        <AppHeader auth={auth} onLogout={onLogout} />
        <div className="panel stack">
          <p className="error-box">{error || "Proje yüklenemedi."}</p>
          <button className="ghost-button" onClick={() => navigate("/projects")}>Projelere Dön</button>
        </div>
      </div>
    );
  }

  const characters = sortCharacters(detail.characters);
  const turkishVoiceProfiles = voiceProfiles.filter((profile) => profile.language === "tr");
  const getPreferredVoiceArtifactForCharacter = (characterId: string, artifactType: string) => {
    const matches = detail.artifacts.filter(
      (artifact) =>
        artifact.artifact_type === artifactType &&
        String(artifact.metadata_json?.character_id ?? "") === characterId,
    );
    matches.sort((left, right) => {
      const leftHasDisplayName = left.metadata_json?.voice_sample_name || left.metadata_json?.voice_reference_name || left.metadata_json?.character_display_name;
      const rightHasDisplayName = right.metadata_json?.voice_sample_name || right.metadata_json?.voice_reference_name || right.metadata_json?.character_display_name;
      if (Boolean(leftHasDisplayName) !== Boolean(rightHasDisplayName)) {
        return leftHasDisplayName ? -1 : 1;
      }
      return right.created_at.localeCompare(left.created_at);
    });
    return matches[0];
  };
  const getLatestSampleArtifactForCharacter = (characterId: string) =>
    getPreferredVoiceArtifactForCharacter(characterId, "VOICE_SAMPLE_AUDIO");
  const getLatestReferenceArtifactForCharacter = (characterId: string) =>
    getPreferredVoiceArtifactForCharacter(characterId, "VOICE_REFERENCE_AUDIO");
  const finalDubAudioArtifacts = detail.artifacts.filter((artifact) => artifact.artifact_type === "FINAL_DUB_AUDIO");
  const lipSyncVideoArtifacts = detail.artifacts.filter((artifact) => artifact.artifact_type === "LIPSYNC_VIDEO");
  const finalRenderArtifacts = detail.artifacts.filter((artifact) => artifact.artifact_type === "FINAL_RENDER");
  const getRenderSourceLabel = (artifact: { metadata_json?: Record<string, unknown> }) => {
    const label = String(artifact.metadata_json?.source_video_label ?? "");
    if (label) {
      return label;
    }
    const artifactType = String(artifact.metadata_json?.source_video_artifact_type ?? "");
    if (artifactType === "LIPSYNC_VIDEO") {
      return "Lip Sync Video";
    }
    if (artifactType === "SOURCE_VIDEO") {
      return "Source Video";
    }
    if (artifactType === "PROXY_VIDEO") {
      return "Proxy Video";
    }
    return "Not recorded";
  };
  const getRenderSourceArtifactId = (artifact: { metadata_json?: Record<string, unknown> }) =>
    String(artifact.metadata_json?.source_video_artifact_id ?? "");
  const getVoiceArtifactDisplayName = (
    artifact: { artifact_type?: string; file_name: string; metadata_json?: Record<string, unknown> } | undefined,
    fallback: string,
  ) => {
    if (!artifact) {
      return fallback;
    }
    const metadata = artifact.metadata_json || {};
    if (artifact.artifact_type === "VOICE_REFERENCE_AUDIO") {
      return String(metadata.voice_reference_name ?? metadata.character_display_name ?? artifact.file_name);
    }
    return String(
      metadata.voice_sample_name
        ?? metadata.voice_reference_name
        ?? metadata.character_display_name
        ?? artifact.file_name,
    );
  };
  const getLatestVoiceSampleJobForCharacter = (characterId: string) =>
    detail.jobs
      .filter(
        (job) =>
          job.job_type === "VOICE_SAMPLE_EXTRACT" &&
          String(job.input_json?.character_id ?? job.output_json?.character_id ?? "") === characterId,
      )
      .sort((left, right) => right.created_at.localeCompare(left.created_at))[0];
  const getVoiceSampleStatus = (
    job: ProjectDetail["jobs"][number] | undefined,
    sampleArtifact: { file_name: string; metadata_json?: Record<string, unknown> } | undefined,
  ) => {
    if (!job && sampleArtifact) {
      return { label: "Completed", className: "status-completed", isActive: false, error: null };
    }
    if (!job) {
      return { label: "Not started", className: "status-pending", isActive: false, error: null };
    }
    if (job.state === "PENDING" || job.state === "QUEUED") {
      return { label: "Queued", className: "status-queued", isActive: true, error: null };
    }
    if (job.state === "PROCESSING") {
      return { label: "Generating voice sample...", className: "status-processing", isActive: true, error: null };
    }
    if (job.state === "COMPLETED") {
      return { label: "Completed", className: "status-completed", isActive: false, error: null };
    }
    if (job.state === "FAILED") {
      return {
        label: "Failed",
        className: "status-failed",
        isActive: false,
        error: String(job.error_json?.message ?? "Voice sample generation failed."),
      };
    }
    return { label: job.state, className: "status-pending", isActive: false, error: null };
  };
  const activeJob = detail.jobs.find((job) => jobIsActive(job.state));
  const failedJobs = detail.jobs.filter((job) => job.state === "FAILED" && !dismissedFailedJobIds.has(job.id));
  const nextStepMessage = getNextStepMessage(detail);
  const latestLipSyncJob = detail.jobs
    .filter((job) => job.job_type === "LIP_SYNC")
    .sort((left, right) => right.created_at.localeCompare(left.created_at))[0];
  const lipSyncStatus = lipSyncVideoArtifacts.length
    ? "LIPSYNC_VIDEO hazır"
    : latestLipSyncJob
      ? `${latestLipSyncJob.state}`
      : "Henüz çalıştırılmadı";

  return (
    <div className="page-shell">
      <AppHeader auth={auth} onLogout={onLogout} />
      <div className="toolbar">
        <div>
          <Link className="inline-link" to="/projects">← Projelere dön</Link>
          <h2>{detail.name}</h2>
          <p className="muted">{detail.source_language || "auto"} → {detail.target_language} · {detail.status}</p>
        </div>
        <div className="toolbar-actions">
          <button className="ghost-button" onClick={() => void refreshDetail()} disabled={refreshing}>
            {refreshing ? "Yenileniyor..." : "Refresh"}
          </button>
        </div>
      </div>

      {error ? <DismissibleAlert className="error-box" onDismiss={() => setError(null)}>{error}</DismissibleAlert> : null}
      {artifactActionError ? (
        <DismissibleAlert className="error-box" onDismiss={() => setArtifactActionError(null)}>
          {artifactActionError}
        </DismissibleAlert>
      ) : null}
      {notice ? <DismissibleAlert className="info-box" onDismiss={() => setNotice(null)}>{notice}</DismissibleAlert> : null}

      <div className="grid summary-grid">
        <StatCard label="Artifacts" value={detail.artifacts.length} />
        <StatCard label="Jobs" value={detail.jobs.length} />
        <StatCard label="Transcript" value={detail.transcript_segments.length} />
        <StatCard label="Translation" value={detail.translation_segments.length} />
        <StatCard label="Dub Segments" value={detail.dub_segments.length} />
        <StatCard label="Speakers" value={detail.speaker_segments.length} />
        <StatCard label="Timeline Clips" value={timeline.clips.length} />
      </div>

      <section className="panel">
        <h3>Video Upload</h3>
        <form className="stack" onSubmit={handleUpload}>
          <input name="video" type="file" accept="video/mp4,video/*" />
          <button className="primary-button" type="submit" disabled={uploading}>
            {uploading ? "Upload ediliyor..." : "Video Upload"}
          </button>
        </form>
      </section>

      <section className="panel">
        <h3>Pipeline Actions</h3>
        <div className="action-grid">
          <button className="primary-button" onClick={() => void handleGenerateCharacters()} disabled={characterActionLoading}>
            {characterActionLoading ? "Çalışıyor..." : "Generate Characters"}
          </button>
          <button
            className="primary-button"
            onClick={() => void runPipelineAction("tts")}
            disabled={pipelineAction !== null}
          >
            {pipelineAction === "tts" ? "TTS Çalışıyor..." : "TTS Başlat"}
          </button>
          <button
            className="primary-button"
            onClick={() => void runPipelineAction("audio-mix")}
            disabled={pipelineAction !== null}
          >
            {pipelineAction === "audio-mix" ? "Audio Mix Çalışıyor..." : "Audio Mix Başlat"}
          </button>
          <button
            className="primary-button"
            onClick={() => void runPipelineAction("lip-sync")}
            disabled={pipelineAction !== null}
          >
            {pipelineAction === "lip-sync" ? "Lip Sync Çalışıyor..." : "Lip Sync Başlat"}
          </button>
          <button
            className="primary-button"
            onClick={() => void runPipelineAction("render")}
            disabled={pipelineAction !== null}
          >
            {pipelineAction === "render" ? "Render Çalışıyor..." : "Render Başlat"}
          </button>
        </div>
        <div className="stack status-stack">
          <p className="muted">
            Polling: {activeJob ? "aktif, her 4 saniyede bir yenileniyor" : "beklemede"} ·
            {" "}Son yenileme: {lastRefreshedAt ? formatDate(lastRefreshedAt) : "-"}
          </p>
          <p className="muted">Aktif job: {activeJob ? `${activeJob.job_type} · ${activeJob.state}` : "Yok"}</p>
          <p className="muted">Lip Sync Status: {lipSyncStatus}</p>
          <div className="next-step-box">
            <strong>Sıradaki adım</strong>
            <p>{nextStepMessage}</p>
          </div>
          {failedJobs.map((job) => (
            <DismissibleAlert
              className="error-box"
              key={job.id}
              onDismiss={() => dismissFailedJobAlert(job.id)}
            >
              {job.job_type} hata: {String(job.error_json?.message ?? "Bilinmeyen hata")}
            </DismissibleAlert>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-heading-row">
          <h3>Pipeline / Job Status</h3>
          <div className="action-row compact-actions">
            <button
              className="ghost-button"
              type="button"
              onClick={() => void clearPipelineJobsByState("COMPLETED")}
              disabled={jobActionId !== null}
            >
              Clear Completed
            </button>
            <button
              className="ghost-button danger-button"
              type="button"
              onClick={() => void clearPipelineJobsByState("FAILED")}
              disabled={jobActionId !== null}
            >
              Clear Failed
            </button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>State</th>
                <th>Queue</th>
                <th>Worker</th>
                <th>Started</th>
                <th>Finished</th>
                <th>Duration</th>
                <th>Failure Reason</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {detail.jobs.map((job) => (
                <tr key={job.id}>
                  <td>{job.job_type}</td>
                  <td><span className={`status-pill status-${job.state.toLowerCase()}`}>{job.state}</span></td>
                  <td>{job.queue_name}</td>
                  <td>{job.worker_name || "-"}</td>
                  <td>{formatDate(job.started_at || job.queued_at)}</td>
                  <td>{formatDate(job.completed_at || job.cancelled_at || (job.state === "FAILED" ? job.updated_at : null))}</td>
                  <td>{formatJobDuration(job)}</td>
                  <td className="mono-cell">{job.state === "FAILED" ? String(job.error_json?.message ?? "Bilinmeyen hata") : "-"}</td>
                  <td>
                    <div className="job-actions">
                      <button className="icon-action-button" type="button" onClick={() => openJobLogs(job)}>
                        Logs
                      </button>
                      {(job.state === "FAILED" || job.state === "CANCELLED") ? (
                        <button
                          className="icon-action-button"
                          type="button"
                          onClick={() => void retryPipelineJob(job)}
                          disabled={jobActionId !== null}
                        >
                          Retry
                        </button>
                      ) : null}
                      {(job.state === "FAILED" || job.state === "COMPLETED" || job.state === "CANCELLED") ? (
                        <button
                          className="icon-action-button danger-button"
                          type="button"
                          onClick={() => void clearPipelineJob(job)}
                          disabled={jobActionId !== null}
                        >
                          Clear
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {jobLogsModal ? (
        <InfoModal title={`Job Logs · ${jobLogsModal.job.job_type}`} onClose={() => setJobLogsModal(null)}>
          <div className="job-log-meta">
            <span>State: <strong>{jobLogsModal.payload?.state ?? jobLogsModal.job.state}</strong></span>
            <span>Worker: <strong>{jobLogsModal.payload?.worker ?? jobLogsModal.job.worker_name ?? "-"}</strong></span>
            <span>Queue: <strong>{jobLogsModal.job.queue_name}</strong></span>
            <span>Duration: <strong>{formatJobDuration(jobLogsModal.job)}</strong></span>
          </div>
          {jobLogsModal.error ? <div className="error-box">{jobLogsModal.error}</div> : null}
          <pre className="job-log-viewer">
            {jobLogsModal.loading && !jobLogsModal.payload
              ? "Loglar yükleniyor..."
              : (jobLogsModal.payload?.logs.length ? jobLogsModal.payload.logs.join("\n") : "Log kaydı yok.")}
          </pre>
          {jobIsActive(jobLogsModal.job.state) ? <p className="muted">Canlı takip açık: 5 saniyede bir yenilenir.</p> : null}
        </InfoModal>
      ) : null}

      <section className="panel">
        <h3>Artifacts</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>File</th>
                <th>Path</th>
                <th>Parents</th>
              </tr>
            </thead>
            <tbody>
              {detail.artifacts.map((artifact) => (
                <tr key={artifact.id}>
                  <td>{artifact.artifact_type}</td>
                  <td>{artifact.file_name}</td>
                  <td className="mono-cell">{artifact.storage_path}</td>
                  <td className="mono-cell">{artifact.parent_artifact_ids.join(", ") || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid two-columns">
        <section className="panel">
          <h3>Lip Sync Video</h3>
          {!lipSyncVideoArtifacts.length ? <p className="muted">Henüz LIPSYNC_VIDEO yok.</p> : null}
          <div className="stack stack-scroll-four">
            {lipSyncVideoArtifacts.map((artifact) => (
              <div className="subpanel" key={artifact.id}>
                <strong>{artifact.file_name}</strong>
                <p className="muted mono-cell">{artifact.storage_path}</p>
                <p className="muted">
                  {String(artifact.metadata_json?.provider ?? "-")} · {String(artifact.metadata_json?.quality_preset ?? "-")} · {String(artifact.metadata_json?.resolution ?? "-")} · {String(artifact.metadata_json?.fps ?? "-")} fps
                </p>
                <p className="muted mono-cell">
                  source={String(artifact.metadata_json?.source_video_artifact_id ?? "-")} audio={String(artifact.metadata_json?.audio_artifact_id ?? "-")}
                </p>
                <div className="row-actions">
                  <span className="muted">
                    processing={String(artifact.metadata_json?.processing_time_ms ?? "-")} ms · mock={String(artifact.metadata_json?.mock ?? "-")}
                  </span>
                  <div className="row-button-group">
                    <button className="ghost-button" onClick={() => void handleOpenArtifact(artifact.id)}>Play / Open</button>
                    <button className="ghost-button" onClick={() => void handleDownloadArtifact(artifact.id, artifact.file_name)}>Download</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <h3>Final Dub Audio</h3>
          {!finalDubAudioArtifacts.length ? <p className="muted">Henüz FINAL_DUB_AUDIO yok.</p> : null}
          <div className="stack stack-scroll-four">
            {finalDubAudioArtifacts.map((artifact) => (
              <div className="subpanel" key={artifact.id}>
                <strong>{artifact.file_name}</strong>
                <p className="muted mono-cell">{artifact.storage_path}</p>
                <p className="muted">
                  Source: {getRenderSourceLabel(artifact)}
                  {getRenderSourceArtifactId(artifact) ? ` · ${getRenderSourceArtifactId(artifact)}` : ""}
                </p>
                <div className="row-actions">
                  <span className="muted">Parents: {artifact.parent_artifact_ids.length}</span>
                  <div className="row-button-group">
                    <button className="ghost-button" onClick={() => void handleOpenArtifact(artifact.id)}>Open</button>
                    <button className="ghost-button" onClick={() => void handleDownloadArtifact(artifact.id, artifact.file_name)}>Download</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <h3>Final Render</h3>
          {!finalRenderArtifacts.length ? <p className="muted">Henüz FINAL_RENDER yok.</p> : null}
          <div className="stack stack-scroll-four">
            {finalRenderArtifacts.map((artifact) => (
              <div className="subpanel" key={artifact.id}>
                <strong>{artifact.file_name}</strong>
                <p className="muted mono-cell">{artifact.storage_path}</p>
                <div className="row-actions">
                  <span className="muted">
                    {String(artifact.metadata_json?.format?.format_name ?? "mp4")} · {String(artifact.metadata_json?.streams?.length ?? 0)} stream
                  </span>
                  <div className="row-button-group">
                    <button className="ghost-button" onClick={() => void handleOpenArtifact(artifact.id)}>Play / Open</button>
                    <button className="ghost-button" onClick={() => void handleDownloadArtifact(artifact.id, artifact.file_name)}>Download</button>
                  </div>
                </div>
                <p className="muted">
                  Source: {getRenderSourceLabel(artifact)}
                  {getRenderSourceArtifactId(artifact) ? ` · ${getRenderSourceArtifactId(artifact)}` : ""}
                </p>
                {finalRenderPreviewUrl ? (
                  <video className="preview-video" controls src={finalRenderPreviewUrl} />
                ) : null}
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="grid two-columns">
        <SegmentPanel
          title="Transcript Segments"
          rows={detail.transcript_segments.map((segment) => ({
            id: segment.id,
            primary: `${formatMs(segment.start_ms)} - ${formatMs(segment.end_ms)}`,
            secondary: segment.text,
            meta: `${segment.language_code || "auto"} · ${segment.speaker_label || "-"}`,
          }))}
        />
        <SegmentPanel
          title="Translation Segments"
          rows={detail.translation_segments.map((segment) => ({
            id: segment.id,
            primary: `${segment.source_language || "auto"} → ${segment.target_language}`,
            secondary: `Faithful: ${segment.faithful_text || segment.translated_text} | Adapted: ${segment.adapted_text || segment.translated_text} | Semantic: ${segment.semantic_similarity_score ?? "-"}`,
            meta: `${segment.provider || "-"} · transcript ${segment.transcript_segment_id}`,
          }))}
        />
      </div>

      <div className="grid two-columns">
        <SegmentPanel
          title="Speaker Segments"
          rows={detail.speaker_segments.map((segment) => ({
            id: segment.id,
            primary: `${segment.speaker_label} · ${formatMs(segment.start_ms)} - ${formatMs(segment.end_ms)}`,
            secondary: segment.provider || "-",
            meta: segment.confidence !== null ? `confidence ${segment.confidence}` : "confidence -",
          }))}
        />
        <section className="panel">
          <h3>Voice Profiles</h3>
          {!turkishVoiceProfiles.length ? <p className="muted">Henüz voice profile yok.</p> : null}
          <div className="stack voice-profile-scroll">
            {turkishVoiceProfiles.map((profile) => (
              <div className="subpanel" key={profile.id}>
                <strong>{profile.display_name}</strong>
                <p>{profile.description || "Açıklama yok"}</p>
                <span className="muted">
                  {profile.provider} · {profile.voice_id} · {profile.profile_type} · {profile.status}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="grid two-columns">
        <section className="panel">
          <h3>Characters</h3>
          {!characters.length ? <p className="muted">Henüz character yok. Generate Characters ile oluşturun.</p> : null}
          <div className="stack stack-scroll-four">
            {characters.map((character) => (
              <div className="subpanel" key={character.id}>
                {(() => {
                  const sampleArtifact = getLatestSampleArtifactForCharacter(character.id);
                  const referenceArtifact = getLatestReferenceArtifactForCharacter(character.id);
                  const voiceSampleJob = getLatestVoiceSampleJobForCharacter(character.id);
                  const voiceSampleStatus = getVoiceSampleStatus(voiceSampleJob, sampleArtifact);
                  return (
                    <>
                <div className="inline-fields">
                  <label>
                    <span>Ad</span>
                    <input
                      value={renameDrafts[character.id]?.display_name ?? character.display_name}
                      onChange={(event) =>
                        setRenameDrafts((current) => ({
                          ...current,
                          [character.id]: {
                            display_name: event.target.value,
                            description: current[character.id]?.description ?? character.description ?? "",
                          },
                        }))
                      }
                    />
                  </label>
                  <label className="wide-field">
                    <span>Açıklama</span>
                    <input
                      value={renameDrafts[character.id]?.description ?? character.description ?? ""}
                      onChange={(event) =>
                        setRenameDrafts((current) => ({
                          ...current,
                          [character.id]: {
                            display_name: current[character.id]?.display_name ?? character.display_name,
                            description: event.target.value,
                          },
                        }))
                      }
                    />
                  </label>
                </div>
                <div className="inline-fields">
                  <label>
                    <span>Voice Profile</span>
                    <select
                      value={voiceProfileDrafts[character.id] ?? character.assigned_voice_profile_id ?? ""}
                      onChange={(event) =>
                        setVoiceProfileDrafts((current) => ({
                          ...current,
                          [character.id]: event.target.value,
                        }))
                      }
                    >
                      <option value="">Fallback default</option>
                      {turkishVoiceProfiles.map((profile) => (
                        <option key={profile.id} value={profile.id}>
                          {profile.display_name} · {profile.voice_id}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                  <div className="stack compact-stack">
                    <span className="muted">
                      Voice Sample Status: <span className={`status-pill ${voiceSampleStatus.className}`}>{voiceSampleStatus.label}</span>
                    </span>
                    {voiceSampleStatus.error ? <span className="error-text">{voiceSampleStatus.error}</span> : null}
                    <span className="muted">
                      Sample: {getVoiceArtifactDisplayName(sampleArtifact, "Henüz yok")}
                    </span>
                    <span className="muted">
                      Reference: {getVoiceArtifactDisplayName(referenceArtifact, "Henüz yok")}
                    </span>
                    {sampleArtifact || referenceArtifact ? (
                      <div className="row-button-group">
                        {sampleArtifact ? (
                          <button className="ghost-button" type="button" onClick={() => void handleOpenArtifact(sampleArtifact.id)}>
                            Play Sample
                          </button>
                        ) : null}
                        {referenceArtifact ? (
                          <button className="ghost-button" type="button" onClick={() => void handleOpenArtifact(referenceArtifact.id)}>
                            Play Reference
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                <div className="row-actions">
                  <div className="stack compact-stack">
                    <span className="muted">{character.source_type}</span>
                    <span className="muted">
                      Assigned: {character.assigned_voice_profile?.display_name ?? "Default fallback"}
                    </span>
                    <span className="muted">
                      Profile Type: {character.assigned_voice_profile?.profile_type ?? "default"}
                    </span>
                    <span className="muted">
                      Clone Status: {character.assigned_voice_profile?.status ?? "not assigned"}
                    </span>
                    <span className="muted">
                      Clone Provider: {character.assigned_voice_profile?.provider ?? "-"}
                    </span>
                    <span className="muted">
                      Reference Audio Duration: {character.assigned_voice_profile?.sample_duration_ms ? formatMs(character.assigned_voice_profile.sample_duration_ms) : "-"}
                    </span>
                    <span className="muted">
                      Clone Quality Score: {character.assigned_voice_profile?.quality_score ?? character.assigned_voice_profile?.average_similarity_score ?? "-"}
                    </span>
                  </div>
                  <div className="row-button-group">
                    <button
                      className="ghost-button"
                      onClick={() => void handleExtractVoiceSample(character.id)}
                      disabled={characterActionLoading || voiceSampleStatus.isActive}
                    >
                      {voiceSampleStatus.isActive ? "Generating..." : voiceSampleStatus.label === "Failed" ? "Retry Voice Sample" : "Generate Voice Sample"}
                    </button>
                    <button
                      className="ghost-button"
                      onClick={() => void handleCreateClonedProfile(character.id)}
                      disabled={characterActionLoading || !referenceArtifact}
                    >
                      Klon Ses Profili Olustur
                    </button>
                    <button
                      className="ghost-button"
                      onClick={() => void handleRenameCharacter(character.id)}
                      disabled={characterActionLoading}
                    >
                      Rename
                    </button>
                    <button
                      className="ghost-button"
                      onClick={() => void handleAssignVoiceProfile(character.id)}
                      disabled={characterActionLoading || !(voiceProfileDrafts[character.id] ?? "")}
                    >
                      Save Voice
                    </button>
                  </div>
                </div>
                    </>
                  );
                })()}
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <h3>Dub Segments</h3>
        {!detail.dub_segments.length ? <p className="muted">Henüz dub segment yok.</p> : null}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Timeline Clip</th>
                <th>Voice</th>
                <th>Profile Type</th>
                <th>Provider</th>
                <th>Duration</th>
                <th>Artifact</th>
              </tr>
            </thead>
            <tbody>
              {detail.dub_segments.map((segment) => (
                <tr key={segment.id}>
                  <td className="mono-cell">{segment.timeline_clip_id ?? "-"}</td>
                  <td>{String(segment.metadata_json?.voice_name ?? segment.metadata_json?.voice_profile_display_name ?? "-")}</td>
                  <td>{String(segment.metadata_json?.voice_profile_type ?? "-")}</td>
                  <td>{segment.provider ?? "-"}</td>
                  <td>{segment.duration_ms ?? "-"} ms</td>
                  <td className="mono-cell">{segment.audio_artifact_id ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h3>Timeline Clips</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Range</th>
                <th>Text</th>
                <th>Translation</th>
                <th>Speaker</th>
                <th>Character</th>
                <th>Edit</th>
              </tr>
            </thead>
            <tbody>
              {timeline.clips.map((clip) => (
                <tr key={clip.id}>
                  <td className="mono-cell">{formatMs(clip.start_ms)} - {formatMs(clip.end_ms)}</td>
                  <td>
                    <textarea
                      rows={2}
                      value={timelineDrafts[clip.id]?.text ?? clip.text ?? ""}
                      onChange={(event) =>
                        setTimelineDrafts((current) => ({
                          ...current,
                          [clip.id]: {
                            text: event.target.value,
                            translation_text: current[clip.id]?.translation_text ?? clip.translation_text ?? "",
                            character_id: current[clip.id]?.character_id ?? clip.character_id ?? "",
                            speaker_label: current[clip.id]?.speaker_label ?? clip.speaker_label ?? "",
                          },
                        }))
                      }
                    />
                  </td>
                  <td>
                    <textarea
                      rows={2}
                      value={timelineDrafts[clip.id]?.translation_text ?? clip.translation_text ?? ""}
                      onChange={(event) =>
                        setTimelineDrafts((current) => ({
                          ...current,
                          [clip.id]: {
                            text: current[clip.id]?.text ?? clip.text ?? "",
                            translation_text: event.target.value,
                            character_id: current[clip.id]?.character_id ?? clip.character_id ?? "",
                            speaker_label: current[clip.id]?.speaker_label ?? clip.speaker_label ?? "",
                          },
                        }))
                      }
                    />
                  </td>
                  <td>
                    <input
                      value={timelineDrafts[clip.id]?.speaker_label ?? clip.speaker_label ?? ""}
                      onChange={(event) =>
                        setTimelineDrafts((current) => ({
                          ...current,
                          [clip.id]: {
                            text: current[clip.id]?.text ?? clip.text ?? "",
                            translation_text: current[clip.id]?.translation_text ?? clip.translation_text ?? "",
                            character_id: current[clip.id]?.character_id ?? clip.character_id ?? "",
                            speaker_label: event.target.value,
                          },
                        }))
                      }
                    />
                  </td>
                  <td>
                    <select
                      value={timelineDrafts[clip.id]?.character_id ?? clip.character_id ?? ""}
                      onChange={(event) =>
                        setTimelineDrafts((current) => ({
                          ...current,
                          [clip.id]: {
                            text: current[clip.id]?.text ?? clip.text ?? "",
                            translation_text: current[clip.id]?.translation_text ?? clip.translation_text ?? "",
                            character_id: event.target.value,
                            speaker_label: current[clip.id]?.speaker_label ?? clip.speaker_label ?? "",
                          },
                        }))
                      }
                    >
                      <option value="">Unassigned</option>
                      {characters.map((character) => (
                        <option key={character.id} value={character.id}>
                          {character.display_name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button
                      className="ghost-button"
                      onClick={() => void handleSaveClip(clip.id)}
                      disabled={timelineSavingId === clip.id}
                    >
                      {timelineSavingId === clip.id ? "Saving..." : "Save"}
                    </button>
                    <div className="tiny-meta">
                      <span>v{clip.edit_version}</span>
                      <span>{clip.edited_at ? formatDate(clip.edited_at) : "-"}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h3>Recent Audit Events</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Event</th>
                <th>Entity</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {detail.events.slice(0, 15).map((event) => (
                <tr key={event.id}>
                  <td>{event.event_type}</td>
                  <td>{event.entity_type}</td>
                  <td>{formatDate(event.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DismissibleAlert({ className, children, onDismiss }: { className: string; children: ReactNode; onDismiss: () => void }) {
  return (
    <div className={`dismissible-alert ${className}`}>
      <span>{children}</span>
      <button className="alert-close-button" type="button" aria-label="Bildirimi kapat" onClick={onDismiss}>
        x
      </button>
    </div>
  );
}

function SegmentPanel({ title, rows }: { title: string; rows: Array<{ id: string; primary: string; secondary: string; meta: string }> }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      {!rows.length ? <p className="muted">Henüz veri yok.</p> : null}
      <div className="stack stack-scroll-four">
        {rows.map((row) => (
          <div className="subpanel" key={row.id}>
            <strong>{row.primary}</strong>
            <p>{row.secondary}</p>
            <span className="muted">{row.meta}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
