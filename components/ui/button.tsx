import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap ta-label-1 transition-colors duration-150 disabled:pointer-events-none disabled:opacity-40 outline-none focus-visible:ring-2 focus-visible:ring-ring/50 [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary-strong",
        secondary: "bg-secondary text-foreground hover:bg-secondary/80",
        outline: "border border-border bg-transparent hover:bg-accent",
        ghost: "hover:bg-accent",
        destructive: "bg-destructive text-white hover:brightness-95",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 rounded-md px-4",
        sm: "h-8 rounded-sm px-3",
        lg: "h-12 rounded-lg px-6",
        icon: "size-9 rounded-md",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

function Button({ className, variant, size, asChild = false, ...props }:
  React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
export { Button, buttonVariants };
