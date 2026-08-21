import * as React from "react";
import { cn } from "@/lib/utils";

function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div className="relative w-full overflow-x-auto">
      <table className={cn("w-full caption-bottom border-collapse", className)} {...props} />
    </div>
  );
}
function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return <thead className={cn("[&_tr]:border-b", className)} {...props} />;
}
function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return <tbody className={cn("[&_tr:last-child]:border-0", className)} {...props} />;
}
function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return <tr className={cn("h-11 border-b transition-colors duration-150 hover:bg-accent", className)} {...props} />;
}
function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return <th className={cn("px-3 text-left align-middle ta-caption-1 text-muted-foreground whitespace-nowrap", className)} {...props} />;
}
function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return <td className={cn("px-3 align-middle ta-label-1", className)} {...props} />;
}
export { Table, TableHeader, TableBody, TableRow, TableHead, TableCell };
