"use client";

import { useParams } from "next/navigation";
import { ChatView } from "@/components/chat/chat-view";

export default function NewChatPage() {
  const { instance } = useParams<{ instance: string }>();

  return <ChatView key="new" instance={instance} />;
}
