"use client";

import { useEffect } from "react";

import { StatusPage } from "@/app/_components/StatusPage";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <StatusPage
      code="Something went wrong"
      isError
      title="Unexpected error"
      actions={[
        { label: "Try again", onClick: reset },
        { href: "/", label: "Back to home", variant: "outline" },
      ]}
    >
      <p>{error?.message || "An unexpected error occurred while rendering this page."}</p>
    </StatusPage>
  );
}
