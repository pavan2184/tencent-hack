"use client";

import * as Select from "@radix-ui/react-select";
import { Check, ChevronDown, CircleAlert, UserRound } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { listPrincipals } from "@/lib/api";
import { useApiQuery } from "@/lib/useApi";
import { usePersona } from "./PersonaProvider";

export function PersonaSwitcher() {
  const { actorId, setActor, me, meError } = usePersona();
  const principals = useApiQuery("principals", listPrincipals);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="hidden flex-wrap items-center gap-1 md:flex">
        {me?.roles.map((role) => (
          <Badge key={`role:${role}`} tone="info">
            {role}
          </Badge>
        ))}
        {me?.groups.map((group) => (
          <Badge key={`group:${group}`}>{group}</Badge>
        ))}
      </div>

      {(principals.error || meError) && (
        <span
          className="flex items-center gap-1 text-xs text-red-600"
          title={(principals.error ?? meError)?.message}
        >
          <CircleAlert className="size-3.5" aria-hidden />
          {principals.error ? "API unreachable" : "Unknown persona"}
        </span>
      )}

      <Select.Root
        value={actorId}
        onValueChange={setActor}
        disabled={!principals.data}
      >
        <Select.Trigger
          aria-label="Persona"
          className="inline-flex h-9 min-w-44 items-center justify-between gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-900 hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:outline-none disabled:opacity-60"
        >
          <span className="flex items-center gap-2">
            <UserRound className="size-4 text-slate-500" aria-hidden />
            <Select.Value placeholder={actorId} />
          </span>
          <Select.Icon>
            <ChevronDown className="size-4 text-slate-500" aria-hidden />
          </Select.Icon>
        </Select.Trigger>

        <Select.Portal>
          <Select.Content
            position="popper"
            sideOffset={6}
            align="end"
            className="z-50 max-h-96 min-w-72 overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg"
          >
            <Select.Viewport className="p-1">
              {principals.data?.map((principal) => (
                <Select.Item
                  key={principal.id}
                  value={principal.id}
                  className="relative flex cursor-default flex-col rounded px-3 py-2 pr-8 text-sm outline-none select-none data-[highlighted]:bg-slate-100"
                >
                  <Select.ItemText>{principal.display_name}</Select.ItemText>
                  <span className="text-xs text-slate-500">
                    {principal.id} · {principal.roles.join(", ") || "no roles"}
                    {principal.groups.length > 0 &&
                      ` · ${principal.groups.join(", ")}`}
                  </span>
                  <Select.ItemIndicator className="absolute top-2.5 right-2">
                    <Check className="size-4" aria-hidden />
                  </Select.ItemIndicator>
                </Select.Item>
              ))}
            </Select.Viewport>
          </Select.Content>
        </Select.Portal>
      </Select.Root>
    </div>
  );
}
