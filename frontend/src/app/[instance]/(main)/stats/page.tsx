import { redirect } from "next/navigation";

export default async function StatsPage({ params }: { params: Promise<{ instance: string }> }) {
  const { instance } = await params;
  redirect(`/${instance}/settings?tab=stats`);
}
