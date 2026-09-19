import Link from "next/link";
import "@/styles/fihrist.css";

/** صفحة 404 بالهوية — بتشتغل بالتوكنز (فاتح/داكن) بدون JS. */
export default function NotFound() {
  return (
    <div className="fh-root" style={{ minHeight: "70vh", display: "grid", placeItems: "center", padding: "2rem" }}>
      <div className="fh-404">
        <p className="fh-404-chip">خطأ 404</p>
        <h1>الصفحة دي مش موجودة.</h1>
        <p className="fh-404-sub">
          الرابط اللي فتحته قديم أو فيه غلطة كتابة — جرب من البداية.
          <br />
          <span dir="ltr" style={{ fontSize: 13.5 }}>This page doesn&apos;t exist.</span>
        </p>
        <div className="fh-404-actions">
          <Link href="/" className="fh-btn">الصفحة الرئيسية</Link>
          <Link href="/pricing" className="fh-btn fh-btn-secondary">الأسعار</Link>
        </div>
      </div>
    </div>
  );
}
