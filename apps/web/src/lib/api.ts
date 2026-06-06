import type {
  ApiErrorResponse,
  Character,
  DubSegment,
  JobBulkClearResponse,
  JobClearResponse,
  JobLogs,
  JobRetryResponse,
  ProjectDurationReport,
  ProjectDetail,
  ProjectListItem,
  ProviderStatusResponse,
  TimelineResponse,
  TokenResponse,
  User,
  VoiceProfile,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const UI_PROCESSING_HEADERS = { "X-AIDublaj-Client": "web" };

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}, token?: string | null): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (!(init.body instanceof FormData) && !headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let errorMessage = `Request failed with status ${response.status}`;
    let errorCode = "HTTP_ERROR";
    try {
      const payload = (await response.json()) as ApiErrorResponse;
      if (payload.error) {
        errorMessage = payload.error.message;
        errorCode = payload.error.code;
      }
    } catch {
      errorMessage = await response.text();
    }
    throw new ApiError(errorMessage, errorCode, response.status);
  }

  return (await response.json()) as T;
}

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

export function login(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function me(token: string): Promise<User> {
  return request<User>("/auth/me", {}, token);
}

export function listProjects(token: string): Promise<ProjectListItem[]> {
  return request<ProjectListItem[]>("/projects", {}, token);
}

export function createProject(
  token: string,
  payload: { name: string; description?: string; source_language?: string; target_language: string },
): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    "/projects",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export function getProject(token: string, projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/projects/${projectId}`, {}, token);
}

export function getTimeline(token: string, projectId: string): Promise<TimelineResponse> {
  return request<TimelineResponse>(`/projects/${projectId}/timeline`, {}, token);
}

export function getProviderStatus(token?: string | null): Promise<ProviderStatusResponse> {
  return request<ProviderStatusResponse>("/runtime/providers", {}, token);
}

export function getProjectDurationReport(token: string, projectId: string): Promise<ProjectDurationReport> {
  return request<ProjectDurationReport>(`/projects/${projectId}/diagnostics/durations`, {}, token);
}

export function uploadProjectVideo(token: string, projectId: string, file: File): Promise<ProjectDetail> {
  const formData = new FormData();
  formData.append("file", file);
  return request<ProjectDetail>(
    `/projects/${projectId}/upload`,
    {
      method: "POST",
      headers: UI_PROCESSING_HEADERS,
      body: formData,
    },
    token,
  );
}

export function generateCharactersFromSpeakers(token: string, projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/projects/${projectId}/characters/from-speakers`,
    {
      method: "POST",
    },
    token,
  );
}

export function renameCharacter(
  token: string,
  projectId: string,
  characterId: string,
  payload: { display_name: string; description: string | null },
): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/projects/${projectId}/characters/${characterId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export function listVoiceProfiles(token: string): Promise<VoiceProfile[]> {
  return request<VoiceProfile[]>("/voice-profiles", {}, token);
}

export function assignCharacterVoiceProfile(
  token: string,
  projectId: string,
  characterId: string,
  voiceProfileId: string,
): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/projects/${projectId}/characters/${characterId}/voice-profile`,
    {
      method: "POST",
      body: JSON.stringify({ voice_profile_id: voiceProfileId }),
    },
    token,
  );
}

export function extractCharacterVoiceSample(
  token: string,
  projectId: string,
  characterId: string,
): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/projects/${projectId}/characters/${characterId}/voice-sample`,
    {
      method: "POST",
      headers: UI_PROCESSING_HEADERS,
    },
    token,
  );
}

export function createClonedVoiceProfileFromSample(
  token: string,
  projectId: string,
  characterId: string,
): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/projects/${projectId}/characters/${characterId}/voice-profile/from-sample`,
    {
      method: "POST",
      headers: UI_PROCESSING_HEADERS,
    },
    token,
  );
}

export function updateTimelineClip(
  token: string,
  projectId: string,
  clipId: string,
  payload: {
    start_ms?: number;
    end_ms?: number;
    text?: string | null;
    translation_text?: string | null;
    character_id?: string | null;
    speaker_label?: string | null;
  },
): Promise<TimelineResponse> {
  return request<TimelineResponse>(
    `/projects/${projectId}/timeline/clips/${clipId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
    token,
  );
}

export function startTts(token: string, projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/projects/${projectId}/tts`,
    {
      method: "POST",
      headers: UI_PROCESSING_HEADERS,
    },
    token,
  );
}

export function startAudioMix(token: string, projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/projects/${projectId}/audio-mix`,
    {
      method: "POST",
      headers: UI_PROCESSING_HEADERS,
    },
    token,
  );
}

export function startLipSync(token: string, projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/projects/${projectId}/lip-sync`,
    {
      method: "POST",
      headers: UI_PROCESSING_HEADERS,
    },
    token,
  );
}

export function startRender(token: string, projectId: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/projects/${projectId}/render`,
    {
      method: "POST",
      headers: UI_PROCESSING_HEADERS,
    },
    token,
  );
}

export function getJobLogs(token: string, jobId: string): Promise<JobLogs> {
  return request<JobLogs>(`/jobs/${jobId}/logs`, {}, token);
}

export function retryJob(token: string, jobId: string): Promise<JobRetryResponse> {
  return request<JobRetryResponse>(`/jobs/${jobId}/retry`, { method: "POST" }, token);
}

export function clearJob(token: string, jobId: string): Promise<JobClearResponse> {
  return request<JobClearResponse>(`/jobs/${jobId}/clear`, { method: "POST" }, token);
}

export function bulkClearJobs(token: string, projectId: string, state: string): Promise<JobBulkClearResponse> {
  return request<JobBulkClearResponse>(
    "/jobs/clear",
    {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, state }),
    },
    token,
  );
}

export function getArtifactContentUrl(projectId: string, artifactId: string): string {
  return `${API_BASE_URL}/projects/${projectId}/artifacts/${artifactId}/content`;
}

export async function fetchArtifactBlob(token: string, projectId: string, artifactId: string): Promise<Blob> {
  const response = await fetch(getArtifactContentUrl(projectId, artifactId), {
    headers: {
      Accept: "*/*",
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    let errorMessage = `Request failed with status ${response.status}`;
    let errorCode = "HTTP_ERROR";
    try {
      const payload = (await response.json()) as ApiErrorResponse;
      if (payload.error) {
        errorMessage = payload.error.message;
        errorCode = payload.error.code;
      }
    } catch {
      errorMessage = await response.text();
    }
    throw new ApiError(errorMessage, errorCode, response.status);
  }

  return response.blob();
}

export function sortCharacters(characters: Character[]): Character[] {
  return [...characters].sort((left, right) => left.display_name.localeCompare(right.display_name, "tr"));
}
