"use client";

import { ExploreHome } from "./_components/ExploreHome";
import { useExploreHome } from "./_lib/use-explore-home";

export default function HomePage() {
  const state = useExploreHome();
  return <ExploreHome state={state} />;
}
