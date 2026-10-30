"use client";

import { Download } from "lucide-react";
import { Button, type ButtonProps } from "@/components/ui/button";

/** Saves text as a file in the visitor's browser. Nothing is uploaded anywhere. */
export function DownloadButton({
  text, filename, mime = "text/plain", label, disabled, variant = "primary", size = "sm",
}: {
  text: string;
  filename: string;
  mime?: string;
  label: string;
  disabled?: boolean;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
}) {
  return (
    <Button
      variant={variant}
      size={size}
      disabled={disabled}
      onClick={() => {
        const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }}
    >
      <Download className="h-3.5 w-3.5" aria-hidden /> {label}
    </Button>
  );
}
