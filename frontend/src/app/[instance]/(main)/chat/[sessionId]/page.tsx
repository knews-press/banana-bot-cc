"use client";

import { useParams } from "next/navigation";
import { ChatView } from "@/components/chat/chat-view";

export default function SessionChatPage() {
  const { instance, sessionId } = useParams<{
    instance: string;
    sessionId: string;
  }>();

  return <ChatView key={sessionId} instance={instance} sessionId={sessionId} />;
}
