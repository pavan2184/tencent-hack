import { Badge } from "@/components/ui/badge";
import { familyOf } from "./rules";

export function RuleBadge({ rule }: { rule: string }) {
  const family = familyOf(rule);
  return (
    <Badge
      tone={
        family === "grant"
          ? "success"
          : family === "source"
            ? "neutral"
            : "info"
      }
      className="font-mono"
    >
      {rule}
    </Badge>
  );
}
