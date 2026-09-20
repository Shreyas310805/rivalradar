/**
 * Typed client for the RivalRadar API.
 *
 * Requests go to same-origin `/api/...`, which Next rewrites to the FastAPI
 * backend (see next.config.ts), so there is no hardcoded host in the UI.
 */

import type {
  Analytics,
  Change,
  Competitor,
  CompetitorCreatePayload,
  DashboardStats,
  Digest,
  Evaluation,
  IntelligenceItem,
  ScanResponse,
} from "./types";

/**
 * Base URL for API calls. Every request in the app goes through this module,
 * so the backend host is configured in exactly one place.
 *
 * Empty (the local default) means same-origin `/api/...`, which the Next dev
 * server rewrites to the backend — no CORS, no host in the bundle.
 *
 * `NEXT_PUBLIC_API_URL` points the browser straight at the backend instead.
 * That is required for the GitHub Pages build, which is static and has no
 * proxy; the backend must then list the Pages origin in CORS_ORIGINS.
 *
 * Only the backend URL is ever public. No key, token or credential is read
 * from a NEXT_PUBLIC_* variable — the OpenRouter key lives solely in the
 * backend environment and the browser never sees it.
 *
 * A trailing `/api` is tolerated and stripped: paths below already include
 * it, and `https://host/api` + `/api/stats` is a confusing 404 to debug.
 */
const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "")
  .trim()
  .replace(/\/+$/, "")
  .replace(/\/api$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string = "error",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      "Cannot reach the RivalRadar API. Is the backend running on port 8000?",
      0,
      "network_error",
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  const body = text ? safeJson(text) : null;

  if (!response.ok) {
    const detail =
      (body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : null) ?? `Request failed with status ${response.status}`;
    const code =
      body && typeof body === "object" && "code" in body
        ? String((body as { code: unknown }).code)
        : "error";
    throw new ApiError(detail, response.status, code);
  }

  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const serialised = search.toString();
  return serialised ? `?${serialised}` : "";
}

export const api = {
  // --- Competitors ---
  listCompetitors: () => request<Competitor[]>("/api/competitors"),

  getCompetitor: (id: number) => request<Competitor>(`/api/competitors/${id}`),

  createCompetitor: (payload: CompetitorCreatePayload) =>
    request<Competitor>("/api/competitors", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateCompetitor: (id: number, payload: Partial<CompetitorCreatePayload>) =>
    request<Competitor>(`/api/competitors/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteCompetitor: (id: number) =>
    request<void>(`/api/competitors/${id}`, { method: "DELETE" }),

  toggleCompetitor: (id: number, active: boolean) =>
    request<Competitor>(`/api/competitors/${id}/toggle${query({ active })}`, {
      method: "POST",
    }),

  addTrackedUrl: (competitorId: number, url: string, label?: string) =>
    request<unknown>(`/api/competitors/${competitorId}/urls`, {
      method: "POST",
      body: JSON.stringify({ url, label }),
    }),

  deleteTrackedUrl: (urlId: number) =>
    request<void>(`/api/competitors/urls/${urlId}`, { method: "DELETE" }),

  scanCompetitor: (id: number) =>
    request<ScanResponse>(`/api/competitors/${id}/scan`, { method: "POST" }),

  // --- Changes and intelligence ---
  listChanges: (params: {
    competitor_id?: number;
    category?: string;
    severity?: string;
    include_noise?: boolean;
    min_score?: number;
    limit?: number;
  } = {}) => request<Change[]>(`/api/changes${query(params)}`),

  getChange: (id: number) => request<Change>(`/api/changes/${id}`),

  listIntelligence: (params: { competitor_id?: number; limit?: number; min_score?: number } = {}) =>
    request<IntelligenceItem[]>(`/api/intelligence${query(params)}`),

  // --- Dashboard ---
  getStats: () => request<DashboardStats>("/api/stats"),

  getAnalytics: (days = 30) => request<Analytics>(`/api/analytics${query({ days })}`),

  // --- Digest ---
  getLatestDigest: () => request<Digest>("/api/digest/latest"),

  generateDigest: (days = 7) =>
    request<Digest>("/api/digest/generate", {
      method: "POST",
      body: JSON.stringify({ days }),
    }),

  // --- Evaluation ---
  listEvaluations: () => request<Evaluation[]>("/api/evaluation/wayback"),

  runEvaluation: (url: string, from_date?: string, to_date?: string) =>
    request<Evaluation>("/api/evaluation/wayback", {
      method: "POST",
      body: JSON.stringify({ url, from_date: from_date || null, to_date: to_date || null }),
    }),
};
