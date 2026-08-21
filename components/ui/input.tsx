import * as React from "react";
import { cn } from "@/lib/utils";
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return <input type={type} data-slot="input"
    className={cn("flex h-10 w-full rounded-lg border border-input bg-transparent px-3 py-2 ta-label-1 transition-colors duration-150 placeholder:text-[--label-assistive] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-40", className)} {...props} />;
}
export { Input };
