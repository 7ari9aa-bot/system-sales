import { useEffect, useState } from "react";

// عدد الصفوف اللازم لملء المساحة المتاحة للجداول (يُطبَّق عند عرض الجدولين جنبًا إلى جنب على الشاشات الكبيرة).
export default function useFillRowCount({ areaRef, bottomRef, rowHeight = 28, reservedHeight = 170, minRows = 3 }) {
  const [rowCount, setRowCount] = useState(minRows);

  useEffect(() => {
    function measure() {
      const area = areaRef.current;
      if (!area) {
        setRowCount(minRows);
        return;
      }
      // The work surface is a fixed-height box, so the room left for the tables is whatever the
      // page has below the area's top edge minus the action bar under it. Side by side (2xl) the
      // two tables share that room; stacked, each gets half of it.
      const sideBySide = window.matchMedia("(min-width: 1536px)").matches;
      const belowHeight = bottomRef.current?.getBoundingClientRect().height ?? 0;
      const available = window.innerHeight - area.getBoundingClientRect().top - belowHeight - 24;
      const room = sideBySide ? available : available / 2;
      setRowCount(Math.max(minRows, Math.floor((room - reservedHeight / (sideBySide ? 1 : 2)) / rowHeight)));
    }

    measure();
    window.addEventListener("resize", measure);
    const mq = window.matchMedia("(min-width: 1536px)");
    mq.addEventListener("change", measure);
    return () => {
      window.removeEventListener("resize", measure);
      mq.removeEventListener("change", measure);
    };
  }, [areaRef, bottomRef, rowHeight, reservedHeight, minRows]);

  return rowCount;
}
