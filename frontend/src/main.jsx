import React from 'react'
import ReactDOM from 'react-dom/client'
import App from '@/App.jsx'
import GuardianErrorBoundary from '@/components/GuardianErrorBoundary'
import Guardian from '@/components/Guardian'
import { guardianReport } from '@/lib/guardian'
import '@/index.css'

// الحارس: أي خطأ جافاسكريبت أو promise مرفوض بيتصطاد ويظهر في الشارة
// بدل ما يضيع صامت في الكونسول.
window.addEventListener('error', (e) => {
  guardianReport({ kind: 'window', source: e.filename ? e.filename.split('/').pop() : 'window', message: e.message });
});
window.addEventListener('unhandledrejection', (e) => {
  const reason = e.reason;
  guardianReport({
    kind: 'promise',
    source: 'unhandledrejection',
    message: reason?.message || String(reason ?? 'rejected promise'),
  });
});

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <GuardianErrorBoundary>
      <App />
      {import.meta.env.DEV && <Guardian />}
    </GuardianErrorBoundary>
  </React.StrictMode>
)
