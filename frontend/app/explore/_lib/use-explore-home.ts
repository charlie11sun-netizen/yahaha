"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { scrollToId, toHomeGame, type HomeGame } from "./explore-data";

export function useExploreHome() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState("All");
  const [limit, setLimit] = useState(12);
  const [sort, setSort] = useState<"newest" | "popular">("newest");

  const backendTag = activeFilter === "AI Generated" ? "All" : activeFilter;
  const gamesQ = useQuery({
    queryKey: ["games", query, backendTag, sort, limit],
    queryFn: () => api.games(query, backendTag, { sort, limit }),
  });

  useEffect(() => {
    setLimit(12);
  }, [query, activeFilter, sort]);

  const allGamesQ = useQuery({
    queryKey: ["games", "", "All"],
    queryFn: () => api.games("", "All"),
  });
  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: api.tags });

  // 加载中/失败一律不用假数据顶替：骨架屏 + 明确错误态（假卡会侵蚀用户信任）
  const allGames = useMemo(() => {
    const live = allGamesQ.data?.items;
    return live ? live.map(toHomeGame) : [];
  }, [allGamesQ.data?.items]);

  const visibleGames = useMemo(() => {
    const live = gamesQ.data?.items;
    const mapped = live ? live.map(toHomeGame) : [];
    // 搜索/标签已在服务端过滤；客户端只保留服务端没有的 "AI Generated" 维度
    return activeFilter === "AI Generated" ? mapped.filter((game) => game.ai) : mapped;
  }, [activeFilter, gamesQ.data?.items]);

  const rankedGames = useMemo(() => [...allGames].sort((a, b) => b.playsNumber - a.playsNumber), [allGames]);
  const featured: HomeGame | undefined = rankedGames[0];
  const trending = rankedGames.slice(0, 4);

  const filterTabs = useMemo(() => {
    const liveTags = tagsQ.data?.tags ?? [];
    const merged = ["All", "AI Generated", ...liveTags, "Arcade", "Puzzle", "RPG", "Adventure"];
    return Array.from(new Set(merged)).slice(0, 6);
  }, [tagsQ.data?.tags]);

  const goCreate = () => router.push("/create");
  const goDetail = (id?: string) => (id ? router.push(`/games/${id}`) : scrollToId("explore"));
  const goPlay = (id?: string) => (id ? router.push(`/play/${id}`) : scrollToId("explore"));
  const goFooter = (label: string) => {
    const map: Record<string, string> = {
      Explore: "/explore", Create: "/create", "My Games": "/me", "How It Works": "/explore#how",
      About: "/about", Contact: "/about", Blog: "/about", Careers: "/about", Documentation: "/about",
    };
    router.push(map[label] || "/");
  };

  return {
    router,
    query,
    setQuery,
    activeFilter,
    setActiveFilter,
    limit,
    setLimit,
    sort,
    setSort,
    gamesQ,
    allGamesQ,
    tagsQ,
    allGames,
    visibleGames,
    featured,
    trending,
    filterTabs,
    goCreate,
    goDetail,
    goPlay,
    goFooter,
  };
}

export type ExploreHomeState = ReturnType<typeof useExploreHome>;
