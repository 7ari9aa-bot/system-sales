import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FC } from 'react'
import { formatEgp } from '@/shared/money'
import type { Platform } from '@/platform'

/**
 * شاشة المخزون في الديسكتوب.
 *
 * كانت بتقرأ من مصفوفة تجريبية ثابتة وتعدّل الرصيد في الحالة المحلية، وزرار «إضافة منتج»
 * و«استيراد» مابيعملوش حاجة. دلوقتي كل حاجة على الباك إند الحقيقي:
 * - القراءة من `pos/stock` (نفس الشاشة اللي الكاشير بيقرا منها، بالبحث من السيرفر)
 * - التسوية بـ`inventory/movements` على المخزن المختار (adjust = الرصيد المطلق)
 * - الإضافة والاستيراد بـ`products/intake` (منتج + تركيبة + باركود + رصيد + تكلفة في طلب واحد)
 */

interface StockRow {
  readonly variant_id?: string
  readonly id?: string
  readonly product_title?: string
  readonly name?: string
  readonly sku?: string | null
  readonly barcode?: string | null
  readonly category?: string | null
  readonly price?: string | null
  readonly on_hand?: number | string | null
  readonly reorder_level?: number | string | null
  readonly avg_cost?: string | null
}

interface StockItem {
  readonly id: string
  readonly name: string
  readonly sku: string
  readonly barcode: string
  readonly category: string
  readonly costPrice: string | null
  readonly sellPrice: string
  readonly stockQuantity: number
  readonly minLimit: number
}

interface WarehouseRow {
  readonly id: string
  readonly name: string
  readonly is_active?: boolean
}

interface ImportLine {
  readonly title: string
  readonly sku: string
  readonly price: string
  readonly barcode: string
  readonly stock: number
  readonly unitCost: string
}

const EMPTY_ADD_FORM = {
  name: '',
  price: '',
  sku: '',
  barcode: '',
  stock: '0',
  unitCost: '',
}

const toInt = (value: unknown): number => {
  const n = Number(value ?? 0)
  return Number.isFinite(n) ? Math.trunc(n) : 0
}

const toMoneyString = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '0.00'
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(2) : '0.00'
}

const slugify = (title: string): string => {
  const base = title
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-|-$/g, '')
  return base || `item-${Date.now()}`
}

/** سطر CSV بسيط: العناوين عربية أو إنجليزية، والفاصلة هي الفاصل. */
function parseCsv(text: string): ImportLine[] {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
  if (lines.length < 2) return []
  const header = lines[0]!.split(',').map((h) => h.trim().toLowerCase())
  const at = (...names: string[]): number => header.findIndex((h) => names.includes(h))
  const titleAt = at('المنتج', 'الاسم', 'title', 'name')
  const skuAt = at('sku', 'الكود', 'كود')
  const priceAt = at('السعر', 'سعر البيع', 'price')
  const barcodeAt = at('الباركود', 'barcode')
  const stockAt = at('الرصيد', 'الكمية', 'stock', 'quantity')
  const costAt = at('التكلفة', 'سعر التكلفة', 'cost', 'unit_cost')
  const rows: ImportLine[] = []
  for (const line of lines.slice(1)) {
    const cells = line.split(',').map((c) => c.trim())
    const title = titleAt >= 0 ? (cells[titleAt] ?? '') : ''
    if (!title) continue
    rows.push({
      title,
      sku: skuAt >= 0 ? (cells[skuAt] ?? '') : '',
      price: priceAt >= 0 ? (cells[priceAt] ?? '') : '',
      barcode: barcodeAt >= 0 ? (cells[barcodeAt] ?? '') : '',
      stock: stockAt >= 0 ? toInt(cells[stockAt]) : 0,
      unitCost: costAt >= 0 ? (cells[costAt] ?? '') : '',
    })
  }
  return rows
}

export const InventoryView: FC<{ platform: Platform }> = ({ platform }) => {
  const [items, setItems] = useState<StockItem[]>([])
  const [warehouses, setWarehouses] = useState<WarehouseRow[]>([])
  const [warehouseId, setWarehouseId] = useState<string>('')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const [selectedItem, setSelectedItem] = useState<StockItem | null>(null)
  const [direction, setDirection] = useState<'in' | 'out' | 'adjust'>('in')
  const [adjustmentQty, setAdjustmentQty] = useState<number>(0)
  const [adjustmentReason, setAdjustmentReason] = useState('جرد دوري')

  const [addOpen, setAddOpen] = useState(false)
  const [addForm, setAddForm] = useState({ ...EMPTY_ADD_FORM })
  const fileRef = useRef<HTMLInputElement | null>(null)

  const loadStock = useCallback(
    async (term: string) => {
      setLoading(true)
      try {
        const query = term.trim() ? `pos/stock?term=${encodeURIComponent(term.trim())}` : 'pos/stock'
        const rows = await platform.http.request<StockRow[]>(query)
        const list = Array.isArray(rows) ? rows : []
        setItems(
          list.map((r) => ({
            id: String(r.variant_id ?? r.id ?? ''),
            name: String(r.product_title ?? r.name ?? ''),
            sku: String(r.sku ?? ''),
            barcode: String(r.barcode ?? ''),
            category: String(r.category ?? 'عام'),
            costPrice: r.avg_cost === null || r.avg_cost === undefined ? null : toMoneyString(r.avg_cost),
            sellPrice: toMoneyString(r.price),
            stockQuantity: toInt(r.on_hand),
            minLimit: toInt(r.reorder_level),
          })),
        )
        setError(null)
      } catch {
        setItems([])
        setError('تعذّر قراءة المخزون من السيرفر. تأكد من الاتصال أو من إعداد العنوان.')
      } finally {
        setLoading(false)
      }
    },
    [platform.http],
  )

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadStock(search)
    }, 200)
    return () => clearTimeout(timer)
  }, [search, loadStock])

  useEffect(() => {
    let mounted = true
    void (async () => {
      try {
        const rows = await platform.http.request<WarehouseRow[]>('warehouses')
        const list = Array.isArray(rows) ? rows.filter((w) => w.is_active !== false) : []
        if (!mounted) return
        setWarehouses(list)
        if (list.length > 0) setWarehouseId((prev) => prev || list[0]!.id)
      } catch {
        if (mounted) setWarehouses([])
      }
    })()
    return () => {
      mounted = false
    }
  }, [platform.http])

  const totals = useMemo(() => {
    const pieces = items.reduce((sum, item) => sum + item.stockQuantity, 0)
    const low = items.filter((item) => item.minLimit > 0 && item.stockQuantity <= item.minLimit).length
    const value = items.reduce((sum, item) => {
      if (item.costPrice === null) return sum
      return sum + Number(item.costPrice) * item.stockQuantity
    }, 0)
    const unknownCost = items.filter((item) => item.costPrice === null).length
    return { pieces, low, value, unknownCost }
  }, [items])

  async function postMovement(target: StockItem, kind: 'in' | 'out' | 'adjust', quantity: number, reason: string): Promise<void> {
    if (!warehouseId) throw new Error('مفيش مخزن نشط. أضف مخزن من الإعدادات الأول.')
    if (kind === 'adjust' && quantity < 0) throw new Error('الرصيد المطلق لا يكون سالبًا.')
    if (kind !== 'adjust' && quantity < 1) throw new Error('الكمية لازم تكون 1 على الأقل.')
    await platform.http.request('inventory/movements', {
      method: 'POST',
      body: {
        variant_id: target.id,
        warehouse_id: warehouseId,
        direction: kind,
        quantity,
        reason,
      },
    })
  }

  async function handleApplyAdjustment(): Promise<void> {
    if (!selectedItem) return
    setSaving(true)
    setError(null)
    try {
      const target = direction === 'adjust' ? adjustmentQty : Math.abs(adjustmentQty)
      await postMovement(selectedItem, direction, target, adjustmentReason)
      const label = direction === 'adjust' ? `الرصيد بقى ${target}` : direction === 'in' ? `دخل ${target}` : `خرج ${target}`
      setNotice(`${selectedItem.name}: ${label} قطعة — محفوظ في المخزن`)
      setSelectedItem(null)
      setAdjustmentQty(0)
      await loadStock(search)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'تعذّر حفظ التسوية')
    } finally {
      setSaving(false)
    }
  }

  async function createOne(line: { title: string; price: string; sku: string; barcode: string; stock: number; unitCost: string }): Promise<void> {
    const price = Number(line.price)
    if (!line.title.trim()) throw new Error('المنتج بلا اسم')
    if (!Number.isFinite(price) || price <= 0) throw new Error('سعر البيع لازم يكون رقم أكبر من صفر')
    const sku = line.sku.trim() || `SKU-${Date.now().toString().slice(-6)}`
    const variant: Record<string, unknown> = {
      sku,
      price: price.toFixed(2),
      option_values: {},
      barcode: line.barcode.trim() || null,
      stock: Math.max(0, toInt(line.stock)),
    }
    const cost = line.unitCost.trim()
    if (cost && Number.isFinite(Number(cost))) variant.unit_cost = Number(cost).toFixed(2)
    await platform.http.request('products/intake', {
      method: 'POST',
      body: {
        title: line.title.trim(),
        slug: slugify(line.title),
        status: 'active',
        ...(warehouseId ? { warehouse_id: warehouseId } : {}),
        variants: [variant],
      },
    })
  }

  async function handleAddProduct(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      await createOne({
        title: addForm.name,
        price: addForm.price,
        sku: addForm.sku,
        barcode: addForm.barcode,
        stock: toInt(addForm.stock),
        unitCost: addForm.unitCost,
      })
      setNotice(`تم إضافة «${addForm.name.trim()}» وظهر في المخزون`)
      setAddForm({ ...EMPTY_ADD_FORM })
      setAddOpen(false)
      await loadStock(search)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'تعذّر إضافة المنتج')
    } finally {
      setSaving(false)
    }
  }

  async function handleImportFile(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0]
    if (!file) return
    setSaving(true)
    setError(null)
    try {
      const rows = parseCsv(await file.text())
      if (rows.length === 0) throw new Error('الملف مفيش فيه صفوف صالحة (لازم سطر عناوين + صف بيانات)')
      const failed: string[] = []
      let done = 0
      for (const row of rows) {
        try {
          await createOne(row)
          done += 1
        } catch (e) {
          failed.push(`${row.title || row.sku}: ${e instanceof Error ? e.message : 'خطأ'}`)
        }
      }
      setNotice(`استيراد: ${done} منتج اتحفظ${failed.length ? ` — ${failed.length} فشل: ${failed.slice(0, 3).join('، ')}` : ''}`)
      await loadStock(search)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'تعذّر استيراد الملف')
    } finally {
      setSaving(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const warehouseName = warehouses.find((w) => w.id === warehouseId)?.name ?? '—'

  return (
    <div className="workstation__content">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <input
          type="text"
          className="pos-search-input"
          placeholder="بحث في المخزون بالاسم، SKU، الباركود..."
          style={{ maxWidth: '400px' }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {warehouses.length > 0 && (
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.9rem' }}>
              <span style={{ color: 'var(--fh-ink-muted)' }}>المخزن</span>
              <select className="pos-search-input" value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)}>
                {warehouses.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <input ref={fileRef} type="file" accept=".csv,text/csv" onChange={(event) => void handleImportFile(event)} style={{ display: 'none' }} data-testid="import-input" />
          <button type="button" className="boot__button" style={{ background: '#0284c7' }} disabled={saving} onClick={() => fileRef.current?.click()}>
            استيراد منتجات (CSV)
          </button>
          <button type="button" className="boot__button" disabled={saving} onClick={() => setAddOpen(true)} data-testid="add-product">
            + إضافة منتج جديد
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', fontSize: '0.9rem', color: 'var(--fh-ink-muted)' }}>
        <span>
          {loading ? 'جاري التحميل…' : `${items.length} صنف · ${totals.pieces} قطعة`}
        </span>
        {totals.low > 0 && <span style={{ color: '#b91c1c' }}>{totals.low} تحت حد التنبيه</span>}
        <span>
          قيمة المخزون: {formatEgp(totals.value.toFixed(2))}
          {totals.unknownCost > 0 ? ` (${totals.unknownCost} صنف بلا تكلفة)` : ''}
        </span>
        <span>مخزن الحركات: {warehouseName}</span>
      </div>

      {error && (
        <div role="alert" style={{ background: '#fef2f2', color: '#b91c1c', padding: '0.6rem 0.9rem', borderRadius: 'var(--fh-radius)' }}>
          {error}
        </div>
      )}
      {notice && (
        <div role="status" style={{ background: '#f0fdf4', color: '#166534', padding: '0.6rem 0.9rem', borderRadius: 'var(--fh-radius)' }}>
          {notice}
        </div>
      )}

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
              <th>حد التنبيه</th>
              <th>الحالة</th>
              <th>إجراءات</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const isLow = item.minLimit > 0 && item.stockQuantity <= item.minLimit
              return (
                <tr key={item.id}>
                  <td style={{ fontWeight: 600 }}>{item.name}</td>
                  <td>{item.category}</td>
                  <td style={{ direction: 'ltr', textAlign: 'right', fontFamily: 'monospace', fontSize: '0.85rem' }}>
                    <div>{item.sku || '—'}</div>
                    <div style={{ color: 'var(--fh-ink-muted)' }}>{item.barcode || '—'}</div>
                  </td>
                  <td>{item.costPrice === null ? <span style={{ color: '#b45309' }}>بلا تكلفة</span> : formatEgp(item.costPrice)}</td>
                  <td style={{ fontWeight: 600, color: 'var(--fh-accent)' }}>{formatEgp(item.sellPrice)}</td>
                  <td style={{ fontWeight: 700, fontSize: '1.05rem' }}>{item.stockQuantity}</td>
                  <td>{item.minLimit || '—'}</td>
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
                        setDirection('in')
                        setAdjustmentQty(0)
                        setAdjustmentReason('جرد دوري')
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
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={9} style={{ textAlign: 'center', color: 'var(--fh-ink-muted)', padding: '1.5rem' }}>
                  مفيش أصناف مطابقة. أضف منتج أو غيّر البحث.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selectedItem && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.1rem' }}>تسوية رصيد: {selectedItem.name}</h3>
              <button type="button" onClick={() => setSelectedItem(null)} style={{ background: 'none', border: 'none', fontSize: '1.25rem', cursor: 'pointer' }}>
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <span style={{ color: 'var(--fh-ink-muted)' }}>الرصيد الحالي: </span>
                <strong>{selectedItem.stockQuantity} قطعة</strong>
                <span style={{ color: 'var(--fh-ink-muted)' }}> — الحركة على مخزن {warehouseName}</span>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.35rem' }}>نوع الحركة</label>
                <select className="pos-search-input" style={{ width: '100%' }} value={direction} onChange={(e) => setDirection(e.target.value as 'in' | 'out' | 'adjust')}>
                  <option value="in">إدخال بضاعة</option>
                  <option value="out">إخراج (تالف/فقد)</option>
                  <option value="adjust">جرد: الرصيد الفعلي</option>
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.35rem' }}>
                  {direction === 'adjust' ? 'الرصيد الفعلي بعد الجرد' : 'الكمية'}
                </label>
                <input
                  type="number"
                  min={0}
                  className="pos-search-input"
                  style={{ width: '100%' }}
                  value={adjustmentQty}
                  onChange={(e) => setAdjustmentQty(parseInt(e.target.value, 10) || 0)}
                />
                <div style={{ fontSize: '0.85rem', color: 'var(--fh-accent)', marginTop: '0.25rem' }}>
                  {direction === 'adjust' ? (
                    <>
                      الرصيد بعد الجرد: <strong>{Math.max(0, adjustmentQty)} قطعة</strong>
                    </>
                  ) : (
                    <>
                      الرصيد بعد الحركة: <strong>{Math.max(0, selectedItem.stockQuantity + (direction === 'in' ? adjustmentQty : -adjustmentQty))} قطعة</strong>
                    </>
                  )}
                </div>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.35rem' }}>سبب الحركة</label>
                <select className="pos-search-input" style={{ width: '100%' }} value={adjustmentReason} onChange={(e) => setAdjustmentReason(e.target.value)}>
                  <option value="جرد دوري">جرد دوري</option>
                  <option value="بضاعة تالفة">بضاعة تالفة</option>
                  <option value="عجز غير مبرر">عجز غير مبرر</option>
                  <option value="استلام غير مسجل">استلام غير مسجل</option>
                </select>
              </div>
            </div>
            <div className="modal-footer">
              <button type="button" className="boot__button" style={{ background: '#64748b' }} onClick={() => setSelectedItem(null)}>
                إلغاء
              </button>
              <button type="button" className="boot__button" disabled={saving} onClick={() => void handleApplyAdjustment()}>
                {saving ? 'جاري الحفظ…' : 'حفظ الحركة'}
              </button>
            </div>
          </div>
        </div>
      )}

      {addOpen && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.1rem' }}>إضافة منتج جديد</h3>
              <button type="button" onClick={() => setAddOpen(false)} style={{ background: 'none', border: 'none', fontSize: '1.25rem', cursor: 'pointer' }}>
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              {[
                { key: 'name', label: 'اسم المنتج', placeholder: 'مثال: تيشيرت قطن أسود' },
                { key: 'price', label: 'سعر البيع', placeholder: '450' },
                { key: 'sku', label: 'SKU (اختياري)', placeholder: 'TEE-BLK-M' },
                { key: 'barcode', label: 'الباركود (اختياري)', placeholder: '6221234567890' },
                { key: 'stock', label: 'الرصيد الافتتاحي', placeholder: '0' },
                { key: 'unitCost', label: 'تكلفة الوحدة (اختياري)', placeholder: '120' },
              ].map((field) => (
                <label key={field.key} style={{ display: 'block' }}>
                  <span style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.3rem' }}>{field.label}</span>
                  <input
                    className="pos-search-input"
                    style={{ width: '100%' }}
                    placeholder={field.placeholder}
                    value={addForm[field.key as keyof typeof addForm]}
                    onChange={(e) => setAddForm((prev) => ({ ...prev, [field.key]: e.target.value }))}
                    name={field.key}
                  />
                </label>
              ))}
              <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--fh-ink-muted)' }}>
                الرصيد الافتتاحي بيتسجل على مخزن {warehouseName} كحركة مخزون حقيقية، والتكلفة بتتحفظ مع الحركة (فاضية = مجهولة).
              </p>
            </div>
            <div className="modal-footer">
              <button type="button" className="boot__button" style={{ background: '#64748b' }} onClick={() => setAddOpen(false)}>
                إلغاء
              </button>
              <button type="button" className="boot__button" disabled={saving} onClick={() => void handleAddProduct()}>
                {saving ? 'جاري الحفظ…' : 'حفظ المنتج'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
