import { StatusPage } from "@/app/_components/StatusPage";

export default function NotFound() {
  return (
    <StatusPage code="Error 404" title="Page not found" actions={[{ href: "/explore", label: "Back to arcade" }]}>
      <p>The page you are looking for does not exist or may have been moved.</p>
    </StatusPage>
  );
}
