import { useEffect, useState } from "react";

// عدد الصفوف اللازم لملء المساحة المتاحة للجداول (يُطبَّق عند عرض الجدولين جنبًا إلى جنب على الشاشات الكبيرة).
export default function useFillRowCount({ areaRef, bottomRef, rowHeight = 28, reservedHeight = 170, minRows = 10 }) {
  const [rowCount, setRowCount] = useState(minRows);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1536px)");

    function measure() {
      const area = areaRef.current;
      if (!mq.matches || !area) {
        setRowCount(minRows);
        return;
      }
      const belowHeight = bottomRef.current?.getBoundingClientRect().height ?? 0;
      const available = window.innerHeight - area.getBoundingClientRect().top - belowHeight - 30;
      setRowCount(Math.max(minRows, Math.floor((available - reservedHeight) / rowHeight)));
    }

    measure();
    window.addEventListener("resize", measure);
    mq.addEventListener("change", measure);
    return () => {
      window.removeEventListener("resize", measure);
      mq.removeEventListener("change", measure);
    };
  }, [areaRef, bottomRef, rowHeight, reservedHeight, minRows]);

  return rowCount;
}