"use client";
import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

const Tabs = TabsPrimitive.Root;

function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List
    className={cn("inline-flex h-8 items-center justify-center rounded-md bg-secondary p-0.5", className)} {...props} />;
}
function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return <TabsPrimitive.Trigger
    className={cn("inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1 ta-caption-1 transition-colors duration-150 data-[state=active]:bg-card data-[state=active]:text-foreground text-muted-foreground disabled:opacity-40", className)} {...props} />;
}
function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn("outline-none", className)} {...props} />;
}
export { Tabs, TabsList, TabsTrigger, TabsContent };
