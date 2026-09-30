import React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { guardianReport } from "@/lib/guardian";

/** حاجز الرندر — لو أي مكون وقع بـexception، الشاشة البيضاء ممنوعة:
 *  بيظهر شاشة وقوف شيك برسالة الخطأ وزر إعادة، والوقعة تتسجل في الحارس. */
export default class GuardianErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    guardianReport({
      kind: "render",
      source: info?.componentStack ? info.componentStack.trim().split("\n")[0] : "render",
      message: error?.message || String(error),
    });
  }

  render() {
    if (this.state.error) {
      return (
        <div
          dir="auto"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 100,
            display: "grid",
            placeItems: "center",
            background: "#08090A",
            color: "#EDEDED",
            fontFamily: "inherit",
            padding: 24,
          }}
        >
          <div style={{ maxWidth: 520, textAlign: "center" }}>
            <div
              style={{
                width: 56,
                height: 56,
                margin: "0 auto 20px",
                display: "grid",
                placeItems: "center",
                borderRadius: 16,
                background: "rgba(239,68,68,.12)",
                color: "#EF4444",
              }}
            >
              <AlertTriangle size={26} />
            </div>
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: "0 0 10px" }}>
              حصل خطأ والنظام وقف عند النقطة دي
            </h1>
            <p style={{ fontSize: 13.5, lineHeight: 1.8, color: "#A1A1AA", margin: "0 0 6px" }}>
              الحارس مسجّل المشكلة — مش فشل صامت. جرّب إعادة التحميل، ولو تكررت
              اتصل بالدعم برسالة الخطأ دي:
            </p>
            <code
              style={{
                display: "block",
                fontSize: 11.5,
                color: "#FCA5A5",
                background: "rgba(239,68,68,.08)",
                border: "1px solid rgba(239,68,68,.25)",
                borderRadius: 8,
                padding: "10px 12px",
                marginTop: 12,
                wordBreak: "break-word",
                direction: "ltr",
                textAlign: "left",
              }}
            >
              {this.state.error?.message || String(this.state.error)}
            </code>
            <button
              onClick={() => window.location.reload()}
              style={{
                marginTop: 20,
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                background: "#3B82F6",
                color: "#fff",
                border: 0,
                borderRadius: 10,
                padding: "11px 20px",
                fontSize: 13.5,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              <RotateCcw size={15} />
              إعادة تحميل
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
