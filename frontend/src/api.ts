import type { AgentEvent, AgentRunRequest, CitationClickResponse, LoadPaperResponse, SessionState, UploadPaperResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createSession(): Promise<{ session_id: string; created_at: string }> {
  return request("/api/sessions", { method: "POST" });
}

export async function loadPaper(sessionId: string, sourceType: "arxiv_url" | "pdf_text" | "demo", source: string): Promise<LoadPaperResponse> {
  return request(`/api/sessions/${sessionId}/papers/load`, {
    method: "POST",
    body: JSON.stringify({ source_type: sourceType, source })
  });
}

export async function uploadPaper(sessionId: string, file: File): Promise<UploadPaperResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/papers/upload`, {
    method: "POST",
    body: form
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Upload failed with ${response.status}`);
  }
  return response.json() as Promise<UploadPaperResponse>;
}

export async function getSession(sessionId: string): Promise<SessionState> {
  return request(`/api/sessions/${sessionId}`);
}

export async function getEvents(sessionId: string): Promise<AgentEvent[]> {
  return request(`/api/sessions/${sessionId}/events`);
}

export async function clickCitation(sessionId: string, citationId: string, paperId?: string): Promise<CitationClickResponse> {
  const query = paperId ? `?paper_id=${encodeURIComponent(paperId)}` : "";
  return request(`/api/sessions/${sessionId}/citations/${citationId}/click${query}`, { method: "POST" });
}

export async function runAgent(sessionId: string, agentName: string, payload: AgentRunRequest) {
  return request(`/api/sessions/${sessionId}/agents/${agentName}/run`, {
    method: "POST",
    body: JSON.stringify({ mode: "manual", ...payload })
  });
}

export function subscribeEvents(sessionId: string, onEvent: (event: AgentEvent) => void, onError: () => void) {
  const source = new EventSource(`${API_BASE}/api/sessions/${sessionId}/events/stream`);
  source.onmessage = (message) => onEvent(JSON.parse(message.data) as AgentEvent);
  source.onerror = () => {
    source.close();
    onError();
  };
  return () => source.close();
}

export function apiBase() {
  return API_BASE;
}
