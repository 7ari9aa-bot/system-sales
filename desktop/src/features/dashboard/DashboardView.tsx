import type { FC } from 'react'
import { formatSar } from '@/shared/money'

export const DashboardView: FC = () => {
  return (
    <div className="workstation__content">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
        <div style={{ padding: '1.25rem', border: '1px solid var(--fh-line)', borderRadius: 'var(--fh-radius)', background: 'var(--fh-surface)' }}>
          <div style={{ color: 'var(--fh-ink-muted)', fontSize: '0.875rem' }}>مبيعات اليوم</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--fh-accent)', marginTop: '0.5rem' }}>
            {formatSar('4850.00')}
          </div>
          <div style={{ fontSize: '0.8rem', color: '#137333', marginTop: '0.25rem' }}>+12% عن الأمس</div>
        </div>

        <div style={{ padding: '1.25rem', border: '1px solid var(--fh-line)', borderRadius: 'var(--fh-radius)', background: 'var(--fh-surface)' }}>
          <div style={{ color: 'var(--fh-ink-muted)', fontSize: '0.875rem' }}>عدد الفواتير</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, marginTop: '0.5rem' }}>38 فاتورة</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--fh-ink-muted)', marginTop: '0.25rem' }}>متوسط السلة: {formatSar('127.63')}</div>
        </div>

        <div style={{ padding: '1.25rem', border: '1px solid var(--fh-line)', borderRadius: 'var(--fh-radius)', background: 'var(--fh-surface)' }}>
          <div style={{ color: 'var(--fh-ink-muted)', fontSize: '0.875rem' }}>تنبيهات المخزون</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#dc2626', marginTop: '0.5rem' }}>4 منتجات</div>
          <div style={{ fontSize: '0.8rem', color: '#dc2626', marginTop: '0.25rem' }}>تحت حد إعادة الطلب</div>
        </div>

        <div style={{ padding: '1.25rem', border: '1px solid var(--fh-line)', borderRadius: 'var(--fh-radius)', background: 'var(--fh-surface)' }}>
          <div style={{ color: 'var(--fh-ink-muted)', fontSize: '0.875rem' }}>الوردية الحالية</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#0284c7', marginTop: '0.5rem' }}>مفتوحة</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--fh-ink-muted)', marginTop: '0.25rem' }}>الكاشير: أحمد سالم (درج رقم 1)</div>
        </div>
      </div>

      <div style={{ marginTop: '1rem', border: '1px solid var(--fh-line)', borderRadius: 'var(--fh-radius)', padding: '1.25rem', background: 'var(--fh-surface)' }}>
        <h3 style={{ margin: '0 0 1rem 0', fontSize: '1.1rem' }}>أحدث فواتير الكاشير اليوم</h3>
        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>رقم الفاتورة</th>
                <th>الوقت</th>
                <th>العميل</th>
                <th>طريقة الدفع</th>
                <th>الإجمالي</th>
                <th>الحالة</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ direction: 'ltr', textAlign: 'right' }}>#POS-2026-0042</td>
                <td>14:32</td>
                <td>عميل نقدي</td>
                <td>مدى / شبكة</td>
                <td style={{ fontWeight: 600 }}>{formatSar('145.00')}</td>
                <td><span className="workstation__badge workstation__badge--online">مكتملة</span></td>
              </tr>
              <tr>
                <td style={{ direction: 'ltr', textAlign: 'right' }}>#POS-2026-0041</td>
                <td>14:15</td>
                <td>سارة الشمري</td>
                <td>نقدي</td>
                <td style={{ fontWeight: 600 }}>{formatSar('280.50')}</td>
                <td><span className="workstation__badge workstation__badge--online">مكتملة</span></td>
              </tr>
              <tr>
                <td style={{ direction: 'ltr', textAlign: 'right' }}>#POS-2026-0040</td>
                <td>13:50</td>
                <td>عميل نقدي</td>
                <td>Apple Pay</td>
                <td style={{ fontWeight: 600 }}>{formatSar('89.00')}</td>
                <td><span className="workstation__badge workstation__badge--online">مكتملة</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
