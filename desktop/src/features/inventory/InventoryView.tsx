import { useState, type FC } from 'react'
import { formatSar } from '@/shared/money'

export interface InventoryItem {
  readonly id: string
  readonly name: string
  readonly sku: string
  readonly barcode: string
  readonly category: string
  readonly costPrice: string
  readonly sellPrice: string
  stockQuantity: number
  readonly minLimit: number
}

const INITIAL_INVENTORY: InventoryItem[] = [
  { id: 'i1', name: 'قميص أكسفورد كلاسيك أبيض', sku: 'SHIRT-OX-WHT', barcode: '628100100101', category: 'ملابس', costPrice: '90.00', sellPrice: '185.00', stockQuantity: 24, minLimit: 10 },
  { id: 'i2', name: 'بنطال جينز سليم كحلي', sku: 'JEAN-SLM-NVY', barcode: '628100100102', category: 'ملابس', costPrice: '120.00', sellPrice: '240.00', stockQuantity: 8, minLimit: 15 },
  { id: 'i3', name: 'تي شيرت قطن مصري أسود', sku: 'TSH-CTN-BLK', barcode: '628100100103', category: 'ملابس', costPrice: '45.00', sellPrice: '95.00', stockQuantity: 42, minLimit: 12 },
  { id: 'i4', name: 'حذاء كاجوال جلد بني', sku: 'SHOE-CAS-BRN', barcode: '628100100104', category: 'أحذية', costPrice: '170.00', sellPrice: '320.00', stockQuantity: 3, minLimit: 5 },
  { id: 'i5', name: 'عطر فهرس الشرقي 100 مل', sku: 'PRF-FHR-100', barcode: '628100100105', category: 'عطور', costPrice: '130.00', sellPrice: '290.00', stockQuantity: 19, minLimit: 10 },
  { id: 'i6', name: 'حزام جلد طبيعي أسود', sku: 'BELT-LTH-BLK', barcode: '628100100106', category: 'إكسسوارات', costPrice: '35.00', sellPrice: '85.00', stockQuantity: 31, minLimit: 8 },
]

export const InventoryView: FC = () => {
  const [items, setItems] = useState<InventoryItem[]>(INITIAL_INVENTORY)
  const [search, setSearch] = useState('')
  const [selectedItem, setSelectedItem] = useState<InventoryItem | null>(null)
  const [adjustmentQty, setAdjustmentQty] = useState<number>(0)
  const [adjustmentReason, setAdjustmentReason] = useState('جرد دوري (Stocktake)')

  const filtered = items.filter((item) => {
    const q = search.trim().toLowerCase()
    if (!q) return true
    return (
      item.name.toLowerCase().includes(q) ||
      item.barcode.includes(q) ||
      item.sku.toLowerCase().includes(q) ||
      item.category.toLowerCase().includes(q)
    )
  })

  const handleApplyAdjustment = (): void => {
    if (!selectedItem) return
    setItems((prev) =>
      prev.map((it) => {
        if (it.id === selectedItem.id) {
          const nextQty = Math.max(0, it.stockQuantity + adjustmentQty)
          return { ...it, stockQuantity: nextQty }
        }
        return it
      }),
    )
    setSelectedItem(null)
    setAdjustmentQty(0)
  }

  return (
    <div className="workstation__content">
      {/* Top Controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <input
          type="text"
          className="pos-search-input"
          placeholder="بحث في المخزون بالاسم، SKU، الباركود، التصنيف..."
          style={{ maxWidth: '400px' }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button type="button" className="boot__button" style={{ background: '#0284c7' }}>
            + استيراد منتجات (CSV)
          </button>
          <button type="button" className="boot__button">
            + إضافة منتج جديد
          </button>
        </div>
      </div>

      {/* Inventory Table */}
      <div className="data-table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>المنتج</th>
              <th>التصنيف</th>
              <th>SKU / Barcode</th>
              <th>سعر التكلفة</th>
              <th>سعر البيع</th>
              <th>الرصيد الحالي</th>
              <th>الحالة</th>
              <th>إجراءات</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item) => {
              const isLow = item.stockQuantity <= item.minLimit
              return (
                <tr key={item.id}>
                  <td style={{ fontWeight: 600 }}>{item.name}</td>
                  <td>{item.category}</td>
                  <td style={{ direction: 'ltr', textAlign: 'right', fontFamily: 'monospace', fontSize: '0.85rem' }}>
                    <div>{item.sku}</div>
                    <div style={{ color: 'var(--fh-ink-muted)' }}>{item.barcode}</div>
                  </td>
                  <td>{formatSar(item.costPrice)}</td>
                  <td style={{ fontWeight: 600, color: 'var(--fh-accent)' }}>{formatSar(item.sellPrice)}</td>
                  <td style={{ fontWeight: 700, fontSize: '1.05rem' }}>{item.stockQuantity}</td>
                  <td>
                    {isLow ? (
                      <span className="workstation__badge" style={{ background: '#fef2f2', color: '#b91c1c' }}>
                        نقص مخزون
                      </span>
                    ) : (
                      <span className="workstation__badge workstation__badge--online">متوفر</span>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedItem(item)
                        setAdjustmentQty(0)
                      }}
                      style={{
                        padding: '0.35rem 0.65rem',
                        border: '1px solid var(--fh-line)',
                        borderRadius: 'var(--fh-radius)',
                        background: 'var(--fh-surface)',
                        cursor: 'pointer',
                        fontSize: '0.85rem',
                      }}
                    >
                      تسوية رصيد
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Stock Adjustment Modal */}
      {selectedItem && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.1rem' }}>تسوية رصيد مخزون: {selectedItem.name}</h3>
              <button
                type="button"
                onClick={() => setSelectedItem(null)}
                style={{ background: 'none', border: 'none', fontSize: '1.25rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <span style={{ color: 'var(--fh-ink-muted)' }}>الرصيد الحالي بالمخزن: </span>
                <strong>{selectedItem.stockQuantity} قطعة</strong>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.35rem' }}>مقدار التعديل (+ للزيادة، - للعجز)</label>
                <input
                  type="number"
                  className="pos-search-input"
                  style={{ width: '100%' }}
                  value={adjustmentQty}
                  onChange={(e) => setAdjustmentQty(parseInt(e.target.value, 10) || 0)}
                />
                <div style={{ fontSize: '0.85rem', color: 'var(--fh-accent)', marginTop: '0.25rem' }}>
                  الرصيد بعد التسوية: <strong>{Math.max(0, selectedItem.stockQuantity + adjustmentQty)} قطعة</strong>
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.35rem' }}>سبب التسوية</label>
                <select
                  className="pos-search-input"
                  style={{ width: '100%' }}
                  value={adjustmentReason}
                  onChange={(e) => setAdjustmentReason(e.target.value)}
                >
                  <option value="جرد دوري (Stocktake)">جرد دوري (Stocktake)</option>
                  <option value="بضاعة تالفة (Damaged)">بضاعة تالفة (Damaged)</option>
                  <option value="عجز غير مبرر (Variance)">عجز غير مبرر (Variance)</option>
                  <option value="استلام غير مسجل (Unrecorded receipt)">استلام غير مسجل (Unrecorded receipt)</option>
                </select>
              </div>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="boot__button"
                style={{ background: '#64748b' }}
                onClick={() => setSelectedItem(null)}
              >
                إلغاء
              </button>
              <button
                type="button"
                className="boot__button"
                onClick={handleApplyAdjustment}
              >
                حفظ التسوية
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
