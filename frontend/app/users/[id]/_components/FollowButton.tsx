"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { PublicUserProfile } from "@/lib/types";

export function FollowButton({ initialProfile }: { initialProfile: PublicUserProfile }) {
  const { user } = useAuth();
  const router = useRouter();
  const flash = useToast();
  const profileQuery = useQuery({
    queryKey: ["user", initialProfile.id, user?.id],
    queryFn: () => api.userProfile(initialProfile.id),
    enabled: !!user,
    initialData: initialProfile,
    initialDataUpdatedAt: 0,
  });
  const profile = profileQuery.data;

  if (user?.id === initialProfile.id || profile.is_self) return null;

  const toggleFollow = async () => {
    if (!user) {
      flash("Sign in to follow creators");
      router.push(`/login?next=${encodeURIComponent(`/users/${initialProfile.id}`)}`);
      return;
    }
    try {
      if (profile.is_following) await api.unfollowUser(initialProfile.id);
      else await api.followUser(initialProfile.id);
      await profileQuery.refetch();
    } catch {
      flash("Could not update follow");
    }
  };

  return (
    <Button className="rounded-lg" disabled={profileQuery.isFetching} onClick={toggleFollow} type="button" variant={profile.is_following ? "secondary" : "default"}>
      <Sparkles size={16} />{profile.is_following ? "Following" : "Follow"}
    </Button>
  );
}
