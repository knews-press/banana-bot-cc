"use client";

import { TerminalError } from "@/components/terminal-error";

export default function ErrorPage() {
  return (
    <TerminalError
      command="exec --run process"
      errorText="error: 500 — internal server error"
      showRetry
    />
  );
}
