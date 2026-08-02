import { AuthenticatedBoundary } from "./_components/AuthenticatedBoundary";

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return <AuthenticatedBoundary>{children}</AuthenticatedBoundary>;
}
