import * as React from "react";
import { cn } from "@/lib/utils";

/** Outlined by default — a TecAce card never carries both border and shadow. */
function Card({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card"
    className={cn("bg-card text-card-foreground rounded-xl border shadow-none", className)} {...props} />;
}
function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-header" className={cn("flex flex-col gap-1 px-5 pt-5", className)} {...props} />;
}
function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-title" className={cn("ta-headline-2", className)} {...props} />;
}
function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-description" className={cn("ta-caption-1 text-muted-foreground", className)} {...props} />;
}
function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-content" className={cn("px-5 py-4", className)} {...props} />;
}
function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-footer" className={cn("flex items-center px-5 pb-5", className)} {...props} />;
}
export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent };
