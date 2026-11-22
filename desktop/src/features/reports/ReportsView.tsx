import { useState, type FC } from 'react'
import { formatSar } from '@/shared/money'

export type ReportTab = 'sales' | 'inventory' | 'shifts'

interface SalesRecord {
  readonly id: string
  readonly invoiceNumber: string
  readonly timestamp: string
  readonly cashierName: string
  readonly paymentMethod: 'cash' | 'card' | 'split'
  readonly totalSar: string
  readonly itemsCount: number
}

interface InventoryValuationItem {
  readonly id: string
  readonly name: string
  readonly barcode: string
  readonly currentStock: number
  readonly unitCostSar: string
  readonly unitPriceSar: string
  readonly totalValueSar: string
  readonly status: 'fast_moving' | 'normal' | 'low_stock' | 'dead_stock'
}

interface ShiftSummaryRecord {
  readonly id: string
  readonly shiftNumber: string
  readonly cashierName: string
  readonly branchName: string
  readonly openedAt: string
  readonly closedAt: string
  readonly openingBalanceSar: string
  readonly systemTotalSar: string
  readonly actualCashSar: string
  readonly varianceSar: string
}

const SAMPLE_SALES: readonly SalesRecord[] = [
  { id: '1', invoiceNumber: 'INV-2026-0891', timestamp: '2026-11-22 14:30', cashierName: 'أحمد محمود', paymentMethod: 'card', totalSar: '345.00', itemsCount: 4 },
  { id: '2', invoiceNumber: 'INV-2026-0892', timestamp: '2026-11-22 14:45', cashierName: 'أحمد محمود', paymentMethod: 'cash', totalSar: '120.00', itemsCount: 2 },
  { id: '3', invoiceNumber: 'INV-2026-0893', timestamp: '2026-11-22 15:10', cashierName: 'سارة خالد', paymentMethod: 'card', totalSar: '680.50', itemsCount: 7 },
  { id: '4', invoiceNumber: 'INV-2026-0894', timestamp: '2026-11-22 15:35', cashierName: 'أحمد محمود', paymentMethod: 'split', totalSar: '450.00', itemsCount: 3 },
  { id: '5', invoiceNumber: 'INV-2026-0895', timestamp: '2026-11-22 16:00', cashierName: 'سارة خالد', paymentMethod: 'card', totalSar: '920.00', itemsCount: 5 },
]

const SAMPLE_INVENTORY_VALUATION: readonly InventoryValuationItem[] = [
  { id: 'p1', name: 'قميص أكسفورد كلاسيك أبيض', barcode: '6281001001', currentStock: 145, unitCostSar: '90.00', unitPriceSar: '145.00', totalValueSar: '21025.00', status: 'fast_moving' },
  { id: 'p2', name: 'بنطال جينز كلاسيك مريح', barcode: '6281001002', currentStock: 80, unitCostSar: '120.00', unitPriceSar: '185.00', totalValueSar: '14800.00', status: 'normal' },
  { id: 'p3', name: 'تي شيرت قطن مصري أسود', barcode: '6281001003', currentStock: 3, unitCostSar: '45.00', unitPriceSar: '75.00', totalValueSar: '225.00', status: 'low_stock' },
  { id: 'p4', name: 'حذاء كاجوال جلد بني', barcode: '6281001004', currentStock: 42, unitCostSar: '170.00', unitPriceSar: '280.00', totalValueSar: '11760.00', status: 'normal' },
  { id: 'p5', name: 'محفظة جلد طبيعي رجالي', barcode: '6281001005', currentStock: 95, unitCostSar: '65.00', unitPriceSar: '110.00', totalValueSar: '10450.00', status: 'dead_stock' },
]

const SAMPLE_SHIFTS: readonly ShiftSummaryRecord[] = [
  { id: 'sh1', shiftNumber: 'SH-2026-112', cashierName: 'أحمد محمود', branchName: 'الفرع الرئيسي', openedAt: '2026-11-22 08:00', closedAt: '2026-11-22 16:00', openingBalanceSar: '500.00', systemTotalSar: '4620.00', actualCashSar: '4620.00', varianceSar: '0.00' },
  { id: 'sh2', shiftNumber: 'SH-2026-111', cashierName: 'سارة خالد', branchName: 'الفرع الرئيسي', openedAt: '2026-11-21 16:00', closedAt: '2026-11-21 23:30', openingBalanceSar: '500.00', systemTotalSar: '6840.00', actualCashSar: '6850.00', varianceSar: '10.00' },
  { id: 'sh3', shiftNumber: 'SH-2026-110', cashierName: 'أحمد محمود', branchName: 'الفرع الرئيسي', openedAt: '2026-11-21 08:00', closedAt: '2026-11-21 16:00', openingBalanceSar: '500.00', systemTotalSar: '5120.00', actualCashSar: '5110.00', varianceSar: '-10.00' },
]

export const ReportsView: FC = () => {
  const [activeTab, setActiveTab] = useState<ReportTab>('sales')
  const [dateRange, setDateRange] = useState<string>('today')
  const [branch, setBranch] = useState<string>('all')

  const exportCsv = (filename: string, rows: readonly (readonly string[])[]) => {
    // Add UTF-8 BOM so Arabic text opens cleanly in Microsoft Excel
    const csvContent = '\uFEFF' + rows.map((e) => e.map((val) => `"${val.replace(/"/g, '""')}"`).join(',')).join('\n')
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.setAttribute('href', url)
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  const handleExport = () => {
    if (activeTab === 'sales') {
      const rows: string[][] = [
        ['رقم الفاتورة', 'التاريخ والوقت', 'اسم الكاشير', 'طريقة الدفع', 'الإجمالي (ر.س)', 'عدد الأصناف'],
        ...SAMPLE_SALES.map((s) => [s.invoiceNumber, s.timestamp, s.cashierName, s.paymentMethod === 'cash' ? 'نقدي' : s.paymentMethod === 'card' ? 'بطاقة' : 'مقسم', s.totalSar, s.itemsCount.toString()]),
      ]
      exportCsv(`sales_report_${dateRange}.csv`, rows)
    } else if (activeTab === 'inventory') {
      const rows: string[][] = [
        ['اسم المنتج', 'الباركود', 'الكمية المتوفرة', 'سعر التكلفة', 'سعر البيع', 'القيمة الإجمالية (ر.س)', 'الحالة'],
        ...SAMPLE_INVENTORY_VALUATION.map((i) => [i.name, i.barcode, i.currentStock.toString(), i.unitCostSar, i.unitPriceSar, i.totalValueSar, i.status === 'fast_moving' ? 'سريع الحركة' : i.status === 'low_stock' ? 'منخفض' : i.status === 'dead_stock' ? 'راكد' : 'طبيعي']),
      ]
      exportCsv(`inventory_valuation_${dateRange}.csv`, rows)
    } else {
      const rows: string[][] = [
        ['رقم الوردية', 'الكاشير', 'الفرع', 'تاريخ الفتح', 'تاريخ الإغلاق', 'الافتتاحي', 'إجمالي النظام', 'النقدي الفعلي', 'الفارق'],
        ...SAMPLE_SHIFTS.map((sh) => [sh.shiftNumber, sh.cashierName, sh.branchName, sh.openedAt, sh.closedAt, sh.openingBalanceSar, sh.systemTotalSar, sh.actualCashSar, sh.varianceSar]),
      ]
      exportCsv(`shifts_zreport_${dateRange}.csv`, rows)
    }
  }

  const handlePrint = () => {
    window.print()
  }

  return (
    <div className="workstation__content" dir="rtl" style={{ padding: '1.5rem', overflowY: 'auto' }}>
      {/* Header & Export Toolbar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 'bold', margin: 0 }}>📊 التقارير والتحليلات المالية</h2>
          <p style={{ color: '#64748b', fontSize: '0.9rem', margin: '0.25rem 0 0 0' }}>
            تقارير معتمدة لمبيعات المتجر، حركة المخزون وتقييمه، ومطابقة ورديات الكاشير
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <select
            value={dateRange}
            onChange={(e) => setDateRange(e.target.value)}
            style={{ padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.875rem' }}
          >
            <option value="today">اليوم</option>
            <option value="week">آخر 7 أيام</option>
            <option value="month">هذا الشهر</option>
            <option value="all">كل الفترات</option>
          </select>

          <select
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            style={{ padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.875rem' }}
          >
            <option value="all">جميع الفروع</option>
            <option value="main">الفرع الرئيسي</option>
          </select>

          <button
            type="button"
            onClick={handleExport}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              backgroundColor: '#0284c7',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              padding: '0.5rem 1rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            📥 تصدير Excel (CSV)
          </button>

          <button
            type="button"
            onClick={handlePrint}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              backgroundColor: '#475569',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              padding: '0.5rem 1rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            🖨️ طباعة التقرير
          </button>
        </div>
      </div>

      {/* Report Tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '2px solid #e2e8f0', marginBottom: '1.5rem' }}>
        <button
          type="button"
          onClick={() => setActiveTab('sales')}
          style={{
            padding: '0.75rem 1.25rem',
            border: 'none',
            background: 'none',
            borderBottom: activeTab === 'sales' ? '3px solid #0284c7' : '3px solid transparent',
            color: activeTab === 'sales' ? '#0284c7' : '#64748b',
            fontWeight: activeTab === 'sales' ? 'bold' : 'normal',
            cursor: 'pointer',
            fontSize: '1rem',
          }}
        >
          📈 تقرير المبيعات والفواتير
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('inventory')}
          style={{
            padding: '0.75rem 1.25rem',
            border: 'none',
            background: 'none',
            borderBottom: activeTab === 'inventory' ? '3px solid #0284c7' : '3px solid transparent',
            color: activeTab === 'inventory' ? '#0284c7' : '#64748b',
            fontWeight: activeTab === 'inventory' ? 'bold' : 'normal',
            cursor: 'pointer',
            fontSize: '1rem',
          }}
        >
          📦 تقييم وحركة المخزون
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('shifts')}
          style={{
            padding: '0.75rem 1.25rem',
            border: 'none',
            background: 'none',
            borderBottom: activeTab === 'shifts' ? '3px solid #0284c7' : '3px solid transparent',
            color: activeTab === 'shifts' ? '#0284c7' : '#64748b',
            fontWeight: activeTab === 'shifts' ? 'bold' : 'normal',
            cursor: 'pointer',
            fontSize: '1rem',
          }}
        >
          🧾 تقارير الورديات (Z-Report)
        </button>
      </div>

      {/* Tab 1: Sales */}
      {activeTab === 'sales' && (
        <div>
          {/* Summary Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
              <div style={{ color: '#64748b', fontSize: '0.85rem' }}>إجمالي المبيعات</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#0f172a', marginTop: '0.25rem' }}>{formatSar('2515.50')}</div>
            </div>
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
              <div style={{ color: '#64748b', fontSize: '0.85rem' }}>عدد الفواتير</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#0284c7', marginTop: '0.25rem' }}>5 فواتير</div>
            </div>
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
              <div style={{ color: '#64748b', fontSize: '0.85rem' }}>متوسط الفاتورة</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#0f172a', marginTop: '0.25rem' }}>{formatSar('503.10')}</div>
            </div>
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
              <div style={{ color: '#64748b', fontSize: '0.85rem' }}>مبيعات البطاقة / شبكة</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#16a34a', marginTop: '0.25rem' }}>{formatSar('1945.50')}</div>
            </div>
          </div>

          {/* Table */}
          <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'right', fontSize: '0.9rem' }}>
              <thead style={{ background: '#f1f5f9', borderBottom: '1px solid #cbd5e1' }}>
                <tr>
                  <th style={{ padding: '0.75rem 1rem' }}>رقم الفاتورة</th>
                  <th style={{ padding: '0.75rem 1rem' }}>التاريخ والوقت</th>
                  <th style={{ padding: '0.75rem 1rem' }}>الكاشير</th>
                  <th style={{ padding: '0.75rem 1rem' }}>طريقة الدفع</th>
                  <th style={{ padding: '0.75rem 1rem' }}>عدد الأصناف</th>
                  <th style={{ padding: '0.75rem 1rem' }}>الإجمالي</th>
                </tr>
              </thead>
              <tbody>
                {SAMPLE_SALES.map((sale) => (
                  <tr key={sale.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 600 }}>{sale.invoiceNumber}</td>
                    <td style={{ padding: '0.75rem 1rem', color: '#64748b' }}>{sale.timestamp}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>{sale.cashierName}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>
                      <span style={{
                        padding: '0.2rem 0.6rem',
                        borderRadius: '4px',
                        fontSize: '0.8rem',
                        background: sale.paymentMethod === 'card' ? '#dcfce7' : '#fef9c3',
                        color: sale.paymentMethod === 'card' ? '#166534' : '#854d0e',
                      }}>
                        {sale.paymentMethod === 'card' ? 'بطاقة / شبكة' : sale.paymentMethod === 'cash' ? 'نقدي' : 'مقسم'}
                      </span>
                    </td>
                    <td style={{ padding: '0.75rem 1rem' }}>{sale.itemsCount}</td>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 'bold' }}>{formatSar(sale.totalSar)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 2: Inventory */}
      {activeTab === 'inventory' && (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
              <div style={{ color: '#64748b', fontSize: '0.85rem' }}>إجمالي قيمة المخزون (سعر البيع)</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#0f172a', marginTop: '0.25rem' }}>{formatSar('58260.00')}</div>
            </div>
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
              <div style={{ color: '#64748b', fontSize: '0.85rem' }}>تكلفة المخزون الإجمالية</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#0284c7', marginTop: '0.25rem' }}>{formatSar('37240.00')}</div>
            </div>
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
              <div style={{ color: '#64748b', fontSize: '0.85rem' }}>الأرباح المتوقعة</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#16a34a', marginTop: '0.25rem' }}>{formatSar('21020.00')}</div>
            </div>
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
              <div style={{ color: '#64748b', fontSize: '0.85rem' }}>أصناف منخفضة المخزون</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#dc2626', marginTop: '0.25rem' }}>1 صنف</div>
            </div>
          </div>

          <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'right', fontSize: '0.9rem' }}>
              <thead style={{ background: '#f1f5f9', borderBottom: '1px solid #cbd5e1' }}>
                <tr>
                  <th style={{ padding: '0.75rem 1rem' }}>اسم المنتج</th>
                  <th style={{ padding: '0.75rem 1rem' }}>الباركود</th>
                  <th style={{ padding: '0.75rem 1rem' }}>الرصيد الحالي</th>
                  <th style={{ padding: '0.75rem 1rem' }}>سعر التكلفة</th>
                  <th style={{ padding: '0.75rem 1rem' }}>سعر البيع</th>
                  <th style={{ padding: '0.75rem 1rem' }}>إجمالي القيمة</th>
                  <th style={{ padding: '0.75rem 1rem' }}>الحركة</th>
                </tr>
              </thead>
              <tbody>
                {SAMPLE_INVENTORY_VALUATION.map((item) => (
                  <tr key={item.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 600 }}>{item.name}</td>
                    <td style={{ padding: '0.75rem 1rem', color: '#64748b' }}>{item.barcode}</td>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 'bold' }}>{item.currentStock} قطعة</td>
                    <td style={{ padding: '0.75rem 1rem' }}>{formatSar(item.unitCostSar)}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>{formatSar(item.unitPriceSar)}</td>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 'bold' }}>{formatSar(item.totalValueSar)}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>
                      <span style={{
                        padding: '0.2rem 0.6rem',
                        borderRadius: '4px',
                        fontSize: '0.8rem',
                        background: item.status === 'fast_moving' ? '#dbeafe' : item.status === 'low_stock' ? '#fee2e2' : item.status === 'dead_stock' ? '#fef3c7' : '#f1f5f9',
                        color: item.status === 'fast_moving' ? '#1e40af' : item.status === 'low_stock' ? '#991b1b' : item.status === 'dead_stock' ? '#92400e' : '#475569',
                      }}>
                        {item.status === 'fast_moving' ? 'سريع الحركة' : item.status === 'low_stock' ? 'منخفض' : item.status === 'dead_stock' ? 'راكد' : 'طبيعي'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 3: Shifts (Z-Report) */}
      {activeTab === 'shifts' && (
        <div>
          <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'right', fontSize: '0.9rem' }}>
              <thead style={{ background: '#f1f5f9', borderBottom: '1px solid #cbd5e1' }}>
                <tr>
                  <th style={{ padding: '0.75rem 1rem' }}>رقم الوردية</th>
                  <th style={{ padding: '0.75rem 1rem' }}>الكاشير</th>
                  <th style={{ padding: '0.75rem 1rem' }}>الفرع</th>
                  <th style={{ padding: '0.75rem 1rem' }}>فترة العمل</th>
                  <th style={{ padding: '0.75rem 1rem' }}>الافتتاحي</th>
                  <th style={{ padding: '0.75rem 1rem' }}>مبيعات النظام</th>
                  <th style={{ padding: '0.75rem 1rem' }}>النقدي الفعلي</th>
                  <th style={{ padding: '0.75rem 1rem' }}>الفارق (عجز/فائض)</th>
                </tr>
              </thead>
              <tbody>
                {SAMPLE_SHIFTS.map((sh) => (
                  <tr key={sh.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 600 }}>{sh.shiftNumber}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>{sh.cashierName}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>{sh.branchName}</td>
                    <td style={{ padding: '0.75rem 1rem', color: '#64748b', fontSize: '0.8rem' }}>
                      {sh.openedAt} إلى {sh.closedAt}
                    </td>
                    <td style={{ padding: '0.75rem 1rem' }}>{formatSar(sh.openingBalanceSar)}</td>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 'bold' }}>{formatSar(sh.systemTotalSar)}</td>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 'bold' }}>{formatSar(sh.actualCashSar)}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>
                      <span style={{
                        padding: '0.2rem 0.6rem',
                        borderRadius: '4px',
                        fontSize: '0.8rem',
                        fontWeight: 'bold',
                        background: sh.varianceSar === '0.00' ? '#dcfce7' : sh.varianceSar.startsWith('-') ? '#fee2e2' : '#fef9c3',
                        color: sh.varianceSar === '0.00' ? '#166534' : sh.varianceSar.startsWith('-') ? '#991b1b' : '#854d0e',
                      }}>
                        {sh.varianceSar === '0.00' ? 'مطابق' : `${sh.varianceSar} ر.س`}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
