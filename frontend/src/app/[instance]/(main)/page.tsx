import { redirect } from "next/navigation";

export default async function InstanceIndexPage({
  params,
}: {
  params: Promise<{ instance: string }>;
}) {
  const { instance } = await params;
  redirect(`/${instance}/chat`);
}
