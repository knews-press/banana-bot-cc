"use client";

import { TerminalError } from "@/components/terminal-error";

export default function GlobalError() {
  return (
    <html>
      <body>
        <TerminalError
          command="boot --recover system"
          errorText="fatal: system error — restart required"
          showRetry
        />
      </body>
    </html>
  );
}
