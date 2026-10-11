import { getActorId } from "./persona";
import type { ErrorEnvelope } from "./types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api"
).replace(/\/+$/, "");

const ACTOR_HEADER = "X-Actor-Id";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    details?: unknown;
    requestId?: string | null;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.details = init.details ?? null;
    this.requestId = init.requestId ?? null;
  }
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError({
    status: 0,
    code: "client_error",
    message: error instanceof Error ? error.message : String(error),
  });
}

export interface ApiFetchInit extends RequestInit {
  /** Skip the X-Actor-Id header (routes that need no actor, e.g. GET /principals). */
  anonymous?: boolean;
}

export async function apiFetch<T>(
  path: string,
  init: ApiFetchInit = {},
): Promise<T> {
  const { anonymous, ...requestInit } = init;
  const headers = new Headers(requestInit.headers);
  headers.set("Accept", "application/json");
  if (!anonymous) headers.set(ACTOR_HEADER, getActorId());
  const body = requestInit.body;
  if (
    body != null &&
    !(body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...requestInit,
      headers,
      cache: "no-store",
    });
  } catch {
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: `Could not reach the API at ${API_BASE_URL}`,
    });
  }

  const text = await response.text();
  const parsed = text ? parseJson(text) : undefined;
  if (!response.ok) throw envelopeToError(response, parsed);
  return parsed as T;
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value))
    return false;
  const inner = (value as { error: unknown }).error;
  return (
    typeof inner === "object" &&
    inner !== null &&
    "code" in inner &&
    "message" in inner
  );
}

function envelopeToError(response: Response, body: unknown): ApiError {
  const envelope = isErrorEnvelope(body) ? body.error : null;
  const requestId =
    envelope?.request_id ?? response.headers.get("X-Request-Id");
  return new ApiError({
    status: response.status,
    code: envelope?.code ?? `http_${response.status}`,
    message:
      response.status === 401
        ? "Pick a persona first"
        : (envelope?.message ?? (response.statusText || "Request failed")),
    details: envelope?.details ?? null,
    requestId,
  });
}
