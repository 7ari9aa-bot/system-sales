import { Shell } from "@/components/shell";
import { ErrorBoundary } from "@/components/error-boundary";

export default function DashLayout({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Shell>{children}</Shell>
    </ErrorBoundary>
  );
}
