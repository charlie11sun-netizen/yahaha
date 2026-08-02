import {
  Brain,
  FileText,
  Gamepad2,
  House,
  Settings,
  Sparkles,
  Star,
} from "lucide-react";
import type { ElementType } from "react";

import type { Section } from "./studio-state";

export const STUDIO_SECTIONS: { id: Section; label: string; icon: ElementType }[] = [
  { id: "overview", label: "Overview", icon: House },
  { id: "games", label: "My Games", icon: Gamepad2 },
  { id: "tasks", label: "Generation Tasks", icon: Sparkles },
  { id: "drafts", label: "Drafts", icon: FileText },
  { id: "favorites", label: "Favorites", icon: Star },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "settings", label: "Account Settings", icon: Settings },
];
