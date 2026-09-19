"use client";

/** حدود خطأ عامة (§108): أي crash في التصيير يعرض حالة خطأ حقيقية بدل صفحة بيضاء. */

import * as React from "react";
import { ErrorState } from "@/components/ui/states";

type Props = { children: React.ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // نُبقي الأثر في الكونسول للتحقيق — العرض نفسه لا يعتمد عليه
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-[60dvh] items-center justify-center p-6">
          <ErrorState message={this.state.error.message} onRetry={this.reset} className="w-full max-w-md" />
        </div>
      );
    }
    return this.props.children;
  }
}
