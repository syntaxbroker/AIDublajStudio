import type {
  ApiErrorResponse,
  Character,
  ProjectDetail,
  ProjectListItem,
  TimelineResponse,
  TokenResponse,
  User,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

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

export function uploadProjectVideo(token: string, projectId: string, file: File): Promise<ProjectDetail> {
  const formData = new FormData();
  formData.append("file", file);
  return request<ProjectDetail>(
    `/projects/${projectId}/upload`,
    {
      method: "POST",
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

export function sortCharacters(characters: Character[]): Character[] {
  return [...characters].sort((left, right) => left.display_name.localeCompare(right.display_name, "tr"));
}
