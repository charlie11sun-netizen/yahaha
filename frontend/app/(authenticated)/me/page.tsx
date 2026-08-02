"use client";

import { Suspense } from "react";

import { StudioDashboard } from "@/app/me/_components/StudioDashboard";
import { useStudioController } from "@/app/me/_lib/use-studio-controller";

export default function ProfilePage() {
  return (
    <Suspense fallback={null}>
      <StudioPage />
    </Suspense>
  );
}

function StudioPage() {
  const studio = useStudioController();
  if (!studio.ready) return null;
  return <StudioDashboard studio={studio} />;
}
