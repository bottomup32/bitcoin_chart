import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border-none px-2 py-0.5 ta-caption-1 whitespace-nowrap transition-colors duration-150",
  {
    variants: {
      variant: {
        default: "bg-primary/10 text-primary",
        positive: "bg-success/10 text-success",
        caution: "bg-warning/10 text-warning",
        negative: "bg-destructive/10 text-destructive",
        neutral: "bg-secondary text-muted-foreground",
        outline: "border border-border bg-transparent text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

function Badge({ className, variant, ...props }:
  React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />;
}
export { Badge, badgeVariants };
