import { useEffect, useState, type FC } from 'react'
import type { Platform } from '@/platform'
import { formatSar } from '@/shared/money'

export interface PosProduct {
  readonly id: string
  readonly name: string
  readonly sku: string
  readonly barcode: string
  readonly price: string
  readonly category: string
}

export interface PosCartLine {
  readonly product: PosProduct
  readonly quantity: number
}

const DEMO_PRODUCTS: PosProduct[] = [
  { id: 'p1', name: 'قميص أكسفورد كلاسيك أبيض', sku: 'SHIRT-OX-WHT', barcode: '628100100101', price: '185.00', category: 'ملابس' },
  { id: 'p2', name: 'بنطال جينز سليم كحلي', sku: 'JEAN-SLM-NVY', barcode: '628100100102', price: '240.00', category: 'ملابس' },
  { id: 'p3', name: 'تي شيرت قطن مصري أسود', sku: 'TSH-CTN-BLK', barcode: '628100100103', price: '95.00', category: 'ملابس' },
  { id: 'p4', name: 'حذاء كاجوال جلد بني', sku: 'SHOE-CAS-BRN', barcode: '628100100104', price: '320.00', category: 'أحذية' },
  { id: 'p5', name: 'عطر فهرس الشرقي 100 مل', sku: 'PRF-FHR-100', barcode: '628100100105', price: '290.00', category: 'عطور' },
  { id: 'p6', name: 'حزام جلد طبيعي أسود', sku: 'BELT-LTH-BLK', barcode: '628100100106', price: '85.00', category: 'إكسسوارات' },
]

export const CashierView: FC<{ readonly platform: Platform }> = ({ platform }) => {
  const [search, setSearch] = useState('')
  const [cart, setCart] = useState<PosCartLine[]>([])
  const [isPaymentOpen, setIsPaymentOpen] = useState(false)
  const [paymentSuccess, setPaymentSuccess] = useState<string | null>(null)

  const addToCart = (product: PosProduct): void => {
    setCart((prev) => {
      const idx = prev.findIndex((item) => item.product.id === product.id)
      const existing = prev[idx]
      if (idx >= 0 && existing) {
        const next = [...prev]
        next[idx] = { product, quantity: existing.quantity + 1 }
        return next
      }
      return [...prev, { product, quantity: 1 }]
    })
  }

  // Listen to hardware barcode scanner bridge
  useEffect(() => {
    const handleScan = (e: Event): void => {
      const customEvent = e as CustomEvent<{ code: string }>
      const barcode = customEvent.detail?.code?.trim()
      if (!barcode) return

      const found = DEMO_PRODUCTS.find((p) => p.barcode === barcode || p.sku.toLowerCase() === barcode.toLowerCase())
      if (found) {
        addToCart(found)
      }
    }

    window.addEventListener('fihrist:scan', handleScan)
    return () => {
      window.removeEventListener('fihrist:scan', handleScan)
    }
  }, [])

  const updateQuantity = (productId: string, delta: number): void => {
    setCart((prev) => {
      return prev
        .map((item) => {
          if (item.product.id === productId) {
            const nextQty = item.quantity + delta
            return nextQty > 0 ? { ...item, quantity: nextQty } : null
          }
          return item
        })
        .filter((item): item is PosCartLine => item !== null)
    })
  }

  const filteredProducts = DEMO_PRODUCTS.filter((p) => {
    const q = search.trim().toLowerCase()
    if (!q) return true
    return p.name.toLowerCase().includes(q) || p.barcode.includes(q) || p.sku.toLowerCase().includes(q)
  })

  // Calculate totals (BigInt cents to avoid IEEE floats)
  const totalCents = cart.reduce((acc, line) => {
    const [intPart = '0', fracPart = '00'] = line.product.price.split('.')
    const priceCents = BigInt(intPart) * 100n + BigInt((fracPart + '00').slice(0, 2))
    return acc + priceCents * BigInt(line.quantity)
  }, 0n)

  const vatCents = (totalCents * 15n) / 115n // 15% VAT inclusive
  const subtotalCents = totalCents - vatCents

  const formatCents = (cents: bigint): string => {
    const sign = cents < 0n ? '-' : ''
    const abs = cents < 0n ? -cents : cents
    const intPart = (abs / 100n).toString()
    const fracPart = (abs % 100n).toString().padStart(2, '0')
    return `${sign}${formatSar(`${intPart}.${fracPart}`)}`
  }

  const handleCheckout = async (method: string): Promise<void> => {
    try {
      // 1. Kick physical cash drawer via native Tauri port
      await platform.printer.openCashDrawer()

      // 2. Build ESC/POS receipt payload
      const receiptText = `\x1B\x40\x1B\x61\x01FIHRIST SALES OS\n` +
        `Simplified Tax Invoice\n` +
        `--------------------------------\n` +
        `Method: ${method}\n` +
        `Total: ${formatCents(totalCents)} SAR\n` +
        `VAT (15%): ${formatCents(vatCents)} SAR\n` +
        `--------------------------------\n` +
        `Thank you for shopping!\n\x1D\x56\x00`
      const encoder = new TextEncoder()
      await platform.printer.printRaw(encoder.encode(receiptText))

      setPaymentSuccess(`تمت معالجة الفاتورة بنجاح ودفع ${formatCents(totalCents)} ر.س عبر ${method}`)
      setCart([])
      setIsPaymentOpen(false)
    } catch {
      setPaymentSuccess('تم إتمام البيع بنجاح (في وضع عدم الاتصال بالطابعة)')
      setCart([])
      setIsPaymentOpen(false)
    }
  }

  return (
    <div className="pos-layout">
      {/* Product Catalog Area */}
      <div className="pos-catalog">
        <div className="pos-search-bar">
          <input
            type="text"
            className="pos-search-input"
            placeholder="امسح الباركود أو ابحث بالاسم، الكود، SKU..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
          {search && (
            <button
              type="button"
              className="boot__button"
              onClick={() => setSearch('')}
              style={{ background: '#64748b' }}
            >
              مسح
            </button>
          )}
        </div>

        {paymentSuccess && (
          <div style={{ padding: '0.75rem 1rem', background: '#dcfce7', color: '#166534', borderRadius: 'var(--fh-radius)', fontWeight: 600 }}>
            {paymentSuccess}
          </div>
        )}

        <div className="pos-grid">
          {filteredProducts.map((p) => (
            <div
              key={p.id}
              className="pos-product-card"
              onClick={() => addToCart(p)}
              role="button"
              tabIndex={0}
            >
              <div>
                <div style={{ fontSize: '0.75rem', color: 'var(--fh-ink-muted)' }}>{p.category}</div>
                <div className="pos-product-card__title">{p.name}</div>
                <div style={{ fontSize: '0.75rem', direction: 'ltr', textAlign: 'right', color: 'var(--fh-ink-muted)' }}>{p.barcode}</div>
              </div>
              <div className="pos-product-card__price">
                {formatSar(p.price)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Cart & Checkout Area */}
      <div className="pos-cart">
        <div className="pos-cart__header">
          <span>سلة المبيعات ({cart.reduce((s, i) => s + i.quantity, 0)})</span>
          {cart.length > 0 && (
            <button
              type="button"
              onClick={() => setCart([])}
              style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', font: 'inherit', fontSize: '0.85rem' }}
            >
              تفريغ
            </button>
          )}
        </div>

        <div className="pos-cart__items">
          {cart.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'var(--fh-ink-muted)', margin: 'auto', padding: '2rem 1rem' }}>
              السلة فارغة. امسح باركود المنتج أو اختر من القائمة لبدء البيع.
            </div>
          ) : (
            cart.map((line) => (
              <div key={line.product.id} className="pos-cart__item">
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: '0.9rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {line.product.name}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--fh-ink-muted)' }}>
                    {formatSar(line.product.price)} × {line.quantity}
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <button
                    type="button"
                    onClick={() => updateQuantity(line.product.id, -1)}
                    style={{ width: '28px', height: '28px', borderRadius: '4px', border: '1px solid var(--fh-line)', background: 'var(--fh-surface)', cursor: 'pointer' }}
                  >
                    -
                  </button>
                  <span style={{ fontWeight: 600, minWidth: '20px', textAlign: 'center' }}>{line.quantity}</span>
                  <button
                    type="button"
                    onClick={() => updateQuantity(line.product.id, 1)}
                    style={{ width: '28px', height: '28px', borderRadius: '4px', border: '1px solid var(--fh-line)', background: 'var(--fh-surface)', cursor: 'pointer' }}
                  >
                    +
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="pos-cart__totals">
          <div className="pos-cart__row">
            <span>المجموع الفرعي (غير شامل الضريبة)</span>
            <span>{formatCents(subtotalCents)} ر.س</span>
          </div>
          <div className="pos-cart__row">
            <span>ضريبة القيمة المضافة (15%)</span>
            <span>{formatCents(vatCents)} ر.س</span>
          </div>
          <div className="pos-cart__row pos-cart__row--total">
            <span>الإجمالي النهائي</span>
            <span>{formatCents(totalCents)} ر.س</span>
          </div>

          <button
            type="button"
            className="pos-btn-checkout"
            disabled={cart.length === 0}
            style={{ opacity: cart.length === 0 ? 0.5 : 1 }}
            onClick={() => setIsPaymentOpen(true)}
          >
            دفع ({formatCents(totalCents)} ر.س)
          </button>
        </div>
      </div>

      {/* Payment Modal */}
      {isPaymentOpen && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.15rem' }}>إتمام الدفع - الفاتورة</h3>
              <button
                type="button"
                onClick={() => setIsPaymentOpen(false)}
                style={{ background: 'none', border: 'none', fontSize: '1.25rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div className="modal-body">
              <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
                <div style={{ fontSize: '0.9rem', color: 'var(--fh-ink-muted)' }}>المبلغ المستحق</div>
                <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--fh-accent)' }}>
                  {formatCents(totalCents)} ر.س
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.75rem' }}>
                <button
                  type="button"
                  className="boot__button"
                  style={{ width: '100%', height: '60px', fontSize: '1.05rem', justifyContent: 'center' }}
                  onClick={() => void handleCheckout('نقدي (Cash)')}
                >
                  💵 نقدي
                </button>
                <button
                  type="button"
                  className="boot__button"
                  style={{ width: '100%', height: '60px', fontSize: '1.05rem', justifyContent: 'center', background: '#0284c7' }}
                  onClick={() => void handleCheckout('مدى / شبكة (Mada/Card)')}
                >
                  💳 مدى / بطاقة
                </button>
                <button
                  type="button"
                  className="boot__button"
                  style={{ width: '100%', height: '60px', fontSize: '1.05rem', justifyContent: 'center', background: '#000000' }}
                  onClick={() => void handleCheckout('Apple Pay')}
                >
                   Apple Pay
                </button>
                <button
                  type="button"
                  className="boot__button"
                  style={{ width: '100%', height: '60px', fontSize: '1.05rem', justifyContent: 'center', background: '#7c3aed' }}
                  onClick={() => void handleCheckout('تقسيم دفع (Split)')}
                >
                  ➗ دفع مجزأ
                </button>
              </div>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="boot__button"
                style={{ background: '#64748b' }}
                onClick={() => setIsPaymentOpen(false)}
              >
                إلغاء
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
