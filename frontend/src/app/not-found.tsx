import { TerminalError } from "@/components/terminal-error";

export default function NotFound() {
  return (
    <TerminalError
      command='find / -name "page" -type f'
      errorText="error: 404 — not found"
    />
  );
}
