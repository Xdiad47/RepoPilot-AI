import { CheckCircle2, CircleSlash, HelpCircle, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Validation } from "@/types/api";

export function validationLabel(v: Validation): string {
  switch (v.status) {
    case "passed":
      if (v.scope === "targeted") return "Passed (targeted)";
      return v.bug_reproduced === false ? "Passed (bug not reproduced)" : "Passed";
    case "failed":
      return "Failed";
    case "inconclusive":
      return "Inconclusive";
    default:
      return "Not run";
  }
}

export function ValidationBadge({ validation }: { validation: Validation }) {
  const label = validationLabel(validation);
  switch (validation.status) {
    case "passed":
      return (
        <Badge tone={validation.bug_reproduced === true ? "success" : "warning"}>
          <CheckCircle2 className="h-3 w-3" aria-hidden /> {label}
        </Badge>
      );
    case "failed":
      return (
        <Badge tone="danger">
          <XCircle className="h-3 w-3" aria-hidden /> {label}
        </Badge>
      );
    case "inconclusive":
      return (
        <Badge tone="warning">
          <HelpCircle className="h-3 w-3" aria-hidden /> {label}
        </Badge>
      );
    default:
      return (
        <Badge>
          <CircleSlash className="h-3 w-3" aria-hidden /> {label}
        </Badge>
      );
  }
}
