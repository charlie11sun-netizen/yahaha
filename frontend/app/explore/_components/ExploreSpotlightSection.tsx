import { cn } from "@/lib/utils";
import { FeaturedSpotlight } from "./ExplorePanels";
import { SHELL, type HomeGame } from "../_lib/explore-data";

export function ExploreSpotlightSection({
  featured,
}: {
  featured?: HomeGame;
}) {
  if (!featured) return null;

  return (
    <section className={cn(SHELL, "pb-4")}>
      <FeaturedSpotlight game={featured} />
    </section>
  );
}
