import type { Principal } from "./types";

// UI gating only; the backend enforces every role check (require_roles → 403).
export function hasRole(
  principal: Principal | null | undefined,
  ...roles: string[]
): boolean {
  if (!principal) return false;
  return roles.some((role) => principal.roles.includes(role));
}

export function canManage(principal: Principal | null | undefined): boolean {
  return hasRole(principal, "manager", "admin");
}

export function canAudit(principal: Principal | null | undefined): boolean {
  return hasRole(principal, "auditor", "admin");
}
