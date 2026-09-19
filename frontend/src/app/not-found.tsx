import Link from "next/link";

/** صفحة 404 بالهوية — بدل صفحة Next الافتراضية. */
export default function NotFound() {
  return (
    <div style={{
      minHeight: "70vh", display: "grid", placeItems: "center",
      background: "#f3f5f1", color: "#1e2521",
      fontFamily: '"IBM Plex Sans Arabic", system-ui, sans-serif', padding: "2rem",
    }}>
      <div style={{ textAlign: "center", maxWidth: 480 }}>
        <p style={{
          display: "inline-block", fontSize: 13.5, fontWeight: 600, color: "#4f6b5e",
          border: "1px solid #dde3dc", borderRadius: 3, padding: ".3rem .9rem", marginBottom: "1.2rem",
        }}>
          خطأ 404
        </p>
        <h1 style={{ fontSize: "clamp(1.6rem, 4vw, 2.4rem)", margin: "0 0 .7rem" }}>
          الصفحة دي مش موجودة.
        </h1>
        <p style={{ color: "#57615a", fontSize: 15.5, margin: "0 0 1.8rem" }}>
          الرابط اللي فتحته قديم أو فيه غلطة كتابة — جرب من البداية.
        </p>
        <div style={{ display: "flex", gap: ".8rem", justifyContent: "center", flexWrap: "wrap" }}>
          <Link href="/" style={{
            background: "#4f6b5e", color: "#f3f5f1", padding: "13px 26px",
            borderRadius: 3, fontSize: 15, fontWeight: 500, textDecoration: "none",
          }}>
            الصفحة الرئيسية
          </Link>
          <Link href="/pricing" style={{
            background: "transparent", color: "#1e2521", border: "1px solid #dde3dc",
            padding: "13px 26px", borderRadius: 3, fontSize: 15, fontWeight: 500, textDecoration: "none",
          }}>
            الأسعار
          </Link>
        </div>
      </div>
    </div>
  );
}
