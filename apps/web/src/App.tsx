import type { FormEvent, ReactElement } from "react";
import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  createProject,
  generateCharactersFromSpeakers,
  getApiBaseUrl,
  getProject,
  getTimeline,
  listProjects,
  login,
  me,
  renameCharacter,
  sortCharacters,
  updateTimelineClip,
  uploadProjectVideo,
} from "./lib/api";
import { clearStoredToken, getStoredToken, setStoredToken } from "./lib/storage";
import type { ProjectDetail, ProjectListItem, TimelineResponse, User } from "./types";

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
  return (
    <header className="app-header">
      <div>
        <p className="eyebrow">AI Dublaj Studio</p>
        <h1>Pipeline Control Room</h1>
        <p className="muted">API: {getApiBaseUrl()}</p>
      </div>
      <div className="header-actions">
        <div className="user-badge">
          <strong>{auth.user?.full_name}</strong>
          <span>{auth.user?.role}</span>
        </div>
        <button className="ghost-button" onClick={onLogout}>Çıkış</button>
      </div>
    </header>
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
    source_language: "en",
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
        source_language: "en",
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
          <div className="list">
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
  const [timelineSavingId, setTimelineSavingId] = useState<string | null>(null);
  const [renameDrafts, setRenameDrafts] = useState<Record<string, { display_name: string; description: string }>>({});
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
      const [project, timelinePayload] = await Promise.all([
        getProject(token, projectId),
        getTimeline(token, projectId),
      ]);
      setDetail(project);
      setTimeline(timelinePayload);
      syncDrafts(project, timelinePayload);
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
    try {
      const project = await uploadProjectVideo(token, projectId, file);
      setDetail(project);
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

  const handleRenameCharacter = async (characterId: string) => {
    if (!token || !projectId) return;
    const draft = renameDrafts[characterId];
    if (!draft) return;
    setCharacterActionLoading(true);
    setError(null);
    try {
      const project = await renameCharacter(token, projectId, characterId, {
        display_name: draft.display_name,
        description: draft.description || null,
      });
      setDetail(project);
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
          <button className="primary-button" onClick={() => void handleGenerateCharacters()} disabled={characterActionLoading}>
            {characterActionLoading ? "Çalışıyor..." : "Generate Characters"}
          </button>
        </div>
      </div>

      {error ? <div className="error-box">{error}</div> : null}

      <div className="grid summary-grid">
        <StatCard label="Artifacts" value={detail.artifacts.length} />
        <StatCard label="Jobs" value={detail.jobs.length} />
        <StatCard label="Transcript" value={detail.transcript_segments.length} />
        <StatCard label="Translation" value={detail.translation_segments.length} />
        <StatCard label="Speakers" value={detail.speaker_segments.length} />
        <StatCard label="Timeline Clips" value={timeline.clips.length} />
      </div>

      <div className="grid two-columns">
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
          <h3>Pipeline / Job Status</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Job</th>
                  <th>State</th>
                  <th>Queue</th>
                  <th>Worker</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {detail.jobs.map((job) => (
                  <tr key={job.id}>
                    <td>{job.job_type}</td>
                    <td><span className={`status-pill status-${job.state.toLowerCase()}`}>{job.state}</span></td>
                    <td>{job.queue_name}</td>
                    <td>{job.worker_name || "-"}</td>
                    <td>{formatDate(job.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

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
            secondary: segment.translated_text,
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
          <h3>Characters</h3>
          {!characters.length ? <p className="muted">Henüz character yok. Generate Characters ile oluşturun.</p> : null}
          <div className="stack">
            {characters.map((character) => (
              <div className="subpanel" key={character.id}>
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
                <div className="row-actions">
                  <span className="muted">{character.source_type}</span>
                  <button
                    className="ghost-button"
                    onClick={() => void handleRenameCharacter(character.id)}
                    disabled={characterActionLoading}
                  >
                    Rename
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

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

function SegmentPanel({ title, rows }: { title: string; rows: Array<{ id: string; primary: string; secondary: string; meta: string }> }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      {!rows.length ? <p className="muted">Henüz veri yok.</p> : null}
      <div className="stack">
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
