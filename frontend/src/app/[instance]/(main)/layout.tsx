import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { getPageTitle } from "@/lib/branding";
import { isValidInstance } from "@/lib/instances";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ instance: string }>;
}): Promise<Metadata> {
  const { instance } = await params;
  return { title: getPageTitle(instance) };
}

export default async function MainLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ instance: string }>;
}) {
  const { instance } = await params;
  if (!isValidInstance(instance)) notFound();
  return <AppShell instance={instance}>{children}</AppShell>;
}
