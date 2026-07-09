"use client";

import { Suspense } from "react";

import { StudioDashboard } from "./_components/StudioDashboard";
import { useStudioController } from "./_lib/use-studio-controller";

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
