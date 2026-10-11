// Demo identity: the selected persona id lives in localStorage and is sent as X-Actor-Id.
// There is no auth (see docs/SECURITY_REVIEW.md); the backend resolves the header to a Principal.

const STORAGE_KEY = "actorId";

export const DEFAULT_ACTOR_ID =
  process.env.NEXT_PUBLIC_DEFAULT_ACTOR_ID || "alex.tan";

const listeners = new Set<() => void>();
// Fallback when localStorage is unavailable (private mode, blocked storage).
let memoryActorId: string | null = null;

export function getActorId(): string {
  if (typeof window === "undefined") return DEFAULT_ACTOR_ID;
  try {
    return (
      window.localStorage.getItem(STORAGE_KEY) ||
      memoryActorId ||
      DEFAULT_ACTOR_ID
    );
  } catch {
    return memoryActorId || DEFAULT_ACTOR_ID;
  }
}

export function setActorId(actorId: string): void {
  memoryActorId = actorId;
  try {
    window.localStorage.setItem(STORAGE_KEY, actorId);
  } catch {
    // Storage blocked: the in-memory value still applies for this tab.
  }
  listeners.forEach((listener) => listener());
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}
