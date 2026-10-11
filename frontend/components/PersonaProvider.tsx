"use client";

import {
  createContext,
  Fragment,
  useContext,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { me } from "@/lib/api";
import type { ApiError } from "@/lib/apiClient";
import {
  DEFAULT_ACTOR_ID,
  getActorId,
  setActorId,
  subscribe,
} from "@/lib/persona";
import type { Principal } from "@/lib/types";
import { useApiQuery } from "@/lib/useApi";

interface PersonaContextValue {
  actorId: string;
  setActor: (actorId: string) => void;
  /** The resolved principal for `actorId` (GET /me), or null while loading / on error. */
  me: Principal | null;
  meError: ApiError | null;
  meLoading: boolean;
}

const PersonaContext = createContext<PersonaContextValue | null>(null);

export function PersonaProvider({ children }: { children: ReactNode }) {
  const actorId = useSyncExternalStore(
    subscribe,
    getActorId,
    () => DEFAULT_ACTOR_ID,
  );
  const meQuery = useApiQuery(`me:${actorId}`, me);

  return (
    <PersonaContext.Provider
      value={{
        actorId,
        setActor: setActorId,
        me: meQuery.data ?? null,
        meError: meQuery.error,
        meLoading: meQuery.loading,
      }}
    >
      {children}
    </PersonaContext.Provider>
  );
}

export function usePersona(): PersonaContextValue {
  const value = useContext(PersonaContext);
  if (!value)
    throw new Error("usePersona must be used inside <PersonaProvider>");
  return value;
}

/** Remounts its children when the persona changes so no page keeps another persona's data. */
export function PersonaBoundary({ children }: { children: ReactNode }) {
  const { actorId } = usePersona();
  return <Fragment key={actorId}>{children}</Fragment>;
}
