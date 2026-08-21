import * as React from "react";
import { cn } from "@/lib/utils";
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return <textarea data-slot="textarea"
    className={cn("flex min-h-24 w-full rounded-lg border border-input bg-transparent px-3 py-2 ta-label-1 transition-colors duration-150 placeholder:text-[--label-assistive] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-40", className)} {...props} />;
}
export { Textarea };
