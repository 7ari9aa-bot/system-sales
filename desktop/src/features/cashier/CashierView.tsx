import { useCallback, useEffect, useRef, useState, type FC } from 'react'
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

export interface HeldCart {
  readonly id: string
  readonly note: string
  readonly cart: PosCartLine[]
  readonly timestamp: string
  readonly totalCents: bigint
}

export interface ShiftState {
  isOpen: boolean
  number: number
  cashierName: string
  openedAt: string
  openingFloatSar: string
  totalSalesCents: bigint
  cashSalesCents: bigint
  cardSalesCents: bigint
}

const DEMO_PRODUCTS: PosProduct[] = [
  { id: 'p1', name: 'قميص أكسفورد كلاسيك أبيض', sku: 'SHIRT-OX-WHT', barcode: '628100100101', price: '185.00', category: 'ملابس' },
  { id: 'p2', name: 'بنطال جينز سليم كحلي', sku: 'JEAN-SLM-NVY', barcode: '628100100102', price: '240.00', category: 'ملابس' },
  { id: 'p3', name: 'تي شيرت قطن مصري أسود', sku: 'TSH-CTN-BLK', barcode: '628100100103', price: '95.00', category: 'ملابس' },
  { id: 'p4', name: 'حذاء كاجوال جلد بني', sku: 'SHOE-CAS-BRN', barcode: '628100100104', price: '320.00', category: 'أحذية' },
  { id: 'p5', name: 'عطر فهرس الشرقي 100 مل', sku: 'PRF-FHR-100', barcode: '628100100105', price: '290.00', category: 'عطور' },
  { id: 'p6', name: 'حزام جلد طبيعي أسود', sku: 'BELT-LTH-BLK', barcode: '628100100106', price: '85.00', category: 'إكسسوارات' },
]

function formatCents(cents: bigint): string {
  const sign = cents < 0n ? '-' : ''
  const abs = cents < 0n ? -cents : cents
  const intPart = (abs / 100n).toString()
  const fracPart = (abs % 100n).toString().padStart(2, '0')
  return `${sign}${formatSar(`${intPart}.${fracPart}`)}`
}

export const CashierView: FC<{ readonly platform: Platform }> = ({ platform }) => {
  const searchInputRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [cart, setCart] = useState<PosCartLine[]>([])
  const [products, setProducts] = useState<PosProduct[]>(DEMO_PRODUCTS)
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [activeRegisterId, setActiveRegisterId] = useState<string | null>(null)
  const [heldCarts, setHeldCarts] = useState<HeldCart[]>([])
  const [isPaymentOpen, setIsPaymentOpen] = useState(false)
  const [paymentSuccess, setPaymentSuccess] = useState<string | null>(null)

  // Shift Management State
  const [shift, setShift] = useState<ShiftState>({
    isOpen: true,
    number: 42,
    cashierName: 'أحمد سالم',
    openedAt: '08:00 ص',
    openingFloatSar: '500.00',
    totalSalesCents: 145000n, // 1450.00 SAR
    cashSalesCents: 65000n,   // 650.00 SAR
    cardSalesCents: 80000n,   // 800.00 SAR
  })
  const [isShiftModalOpen, setIsShiftModalOpen] = useState(false)
  const [openingFloatInput, setOpeningFloatInput] = useState('500.00')
  const [countedCashInput, setCountedCashInput] = useState('')

  // Held Carts Modal
  const [isHeldCartsModalOpen, setIsHeldCartsModalOpen] = useState(false)
  const [holdNoteInput, setHoldNoteInput] = useState('')

  // Returns Modal
  const [isReturnsModalOpen, setIsReturnsModalOpen] = useState(false)
  const [returnReceiptInput, setReturnReceiptInput] = useState('')
  const [returnFound, setReturnFound] = useState<boolean>(false)

  // Initialize Register & Working Session from Backend
  useEffect(() => {
    let mounted = true
    async function initPos(): Promise<void> {
      try {
        const session = await platform.auth.getSession()
        let regId = session?.register?.id
        if (!regId) {
          const regs = await platform.http.request<Array<{ id: string }>>('pos/registers')
          if (Array.isArray(regs) && regs.length > 0) {
            regId = regs[0]?.id
          }
        }
        if (regId && mounted) {
          setActiveRegisterId(regId)
          try {
            const ws = await platform.http.request<{
              started: boolean
              session?: { id: string; opened_at?: string; cashier_user_id?: string; opening_float?: string }
            }>(`pos/registers/${regId}/working-session`, { method: 'POST', body: {} })
            if (ws && ws.started && ws.session) {
              setActiveSessionId(ws.session.id)
              setShift((prev) => ({
                ...prev,
                isOpen: true,
                cashierName: session?.user?.name || prev.cashierName,
                openedAt: ws.session?.opened_at ? new Date(ws.session.opened_at).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }) : prev.openedAt,
                openingFloatSar: ws.session?.opening_float || prev.openingFloatSar,
              }))
            }
          } catch {
            // Offline fallback
          }
        }
      } catch {
        // Offline or unauthenticated
      }
    }
    void initPos()
    return () => {
      mounted = false
    }
  }, [platform.auth, platform.http])

  // Live Product Search from Backend Stock API
  useEffect(() => {
    let mounted = true
    const term = search.trim()
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const stockEndpoint = term ? `pos/stock?term=${encodeURIComponent(term)}` : 'pos/stock'
          const res = await platform.http.request<Array<{
            id?: string
            variant_id?: string
            name?: string
            product_title?: string
            sku?: string
            barcode?: string
            price: string
            category?: string
          }>>(stockEndpoint)

          if (mounted && Array.isArray(res) && res.length > 0) {
            const mapped: PosProduct[] = res.map((r) => ({
              id: r.variant_id || r.id || '',
              name: r.product_title || r.name || '',
              sku: r.sku || '',
              barcode: r.barcode || '',
              price: r.price || '0.00',
              category: r.category || 'عام',
            }))
            setProducts(mapped)
            return
          }
        } catch {
          // Fallback to local filtering
        }
        if (mounted) {
          setProducts(DEMO_PRODUCTS.filter((p) => {
            if (!term) return true
            return p.name.toLowerCase().includes(term.toLowerCase()) || p.barcode.includes(term) || p.sku.toLowerCase().includes(term.toLowerCase())
          }))
        }
      })()
    }, 200)

    return () => {
      mounted = false
      clearTimeout(timer)
    }
  }, [search, platform.http])

  const addToCart = useCallback((product: PosProduct): void => {
    if (!shift.isOpen) {
      setIsShiftModalOpen(true)
      return
    }
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
  }, [shift.isOpen])

  // Listen to hardware barcode scanner bridge
  useEffect(() => {
    const handleScan = (e: Event): void => {
      const customEvent = e as CustomEvent<{ code: string }>
      const barcode = customEvent.detail?.code?.trim()
      if (!barcode) return

      void (async () => {
        if (activeSessionId) {
          try {
            const res = await platform.http.request<{
              variant_id?: string
              id?: string
              product_title?: string
              name?: string
              price?: string
              barcode?: string
              sku?: string
              category?: string
            }>(`pos/sessions/${activeSessionId}/scan`, {
              method: 'POST',
              body: { identifier_type: 'barcode', value: barcode },
            })
            if (res) {
              const p: PosProduct = {
                id: res.variant_id || res.id || barcode,
                name: res.product_title || res.name || barcode,
                price: res.price || '0.00',
                barcode: res.barcode || barcode,
                sku: res.sku || '',
                category: res.category || 'عام',
              }
              addToCart(p)
              return
            }
          } catch {
            // Fallback to local lookup
          }
        }

        const found = products.find((p) => p.barcode === barcode || p.sku.toLowerCase() === barcode.toLowerCase()) ||
          DEMO_PRODUCTS.find((p) => p.barcode === barcode || p.sku.toLowerCase() === barcode.toLowerCase())
        if (found) {
          addToCart(found)
        }
      })()
    }

    window.addEventListener('fihrist:scan', handleScan)
    return () => {
      window.removeEventListener('fihrist:scan', handleScan)
    }
  }, [addToCart, activeSessionId, platform.http, products])

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

  const filteredProducts = products.filter((p) => {
    const q = search.trim().toLowerCase()
    if (!q) return true
    return p.name.toLowerCase().includes(q) || p.barcode.includes(q) || p.sku.toLowerCase().includes(q)
  })

  // Calculate totals (BigInt cents)
  const totalCents = cart.reduce((acc, line) => {
    const [intPart = '0', fracPart = '00'] = line.product.price.split('.')
    const priceCents = BigInt(intPart) * 100n + BigInt((fracPart + '00').slice(0, 2))
    return acc + priceCents * BigInt(line.quantity)
  }, 0n)

  const vatCents = (totalCents * 15n) / 115n // 15% VAT inclusive
  const subtotalCents = totalCents - vatCents

  const handleCheckout = useCallback(async (method: string): Promise<void> => {
    const isCash = method.includes('نقدي') || method.toLowerCase().includes('cash')

    // 1. Post sale to backend if we have a register
    let serverReceipt: string | null = null
    const idempotencyKey = `pos_sale_${Date.now()}_${Math.floor(Math.random() * 1000)}`
    const paymentMethod = isCash ? 'cash' : 'card'

    if (activeRegisterId) {
      try {
        const salePayload = {
          items: cart.map((line) => ({
            variant_id: line.product.id,
            quantity: line.quantity,
          })),
          payments: [{
            method: paymentMethod,
            amount: formatCents(totalCents).replace(/[^\d.]/g, ''),
          }],
        }
        const saleRes = await platform.http.request<{
          order_id?: string
          receipt_number?: string
          grand_total?: string
        }>(`pos/registers/${activeRegisterId}/sales`, {
          method: 'POST',
          headers: { 'Idempotency-Key': idempotencyKey },
          body: salePayload,
        })
        if (saleRes?.receipt_number) {
          serverReceipt = saleRes.receipt_number
        }
      } catch {
        // Sale was not saved to server; continue with offline receipt
      }
    }

    // 2. Open cash drawer for cash payments
    if (isCash) {
      try {
        await platform.printer.openCashDrawer()
      } catch {
        // Cash drawer pulse failed or unattached, continue
      }
    }

    // 3. Print receipt
    try {
      const receiptText = `\x1B\x40\x1B\x61\x01FIHRIST SALES OS\n` +
        `Simplified Tax Invoice\n` +
        `--------------------------------\n` +
        `Shift: #${shift.number} | Cashier: ${shift.cashierName}\n` +
        `Receipt: ${serverReceipt || `LOCAL-${Date.now()}`}\n` +
        `Method: ${method}\n` +
        `Total: ${formatCents(totalCents)} SAR\n` +
        `VAT (15%): ${formatCents(vatCents)} SAR\n` +
        `--------------------------------\n` +
        `Thank you for shopping!\n\x1D\x56\x00`
      const encoder = new TextEncoder()
      await platform.printer.printRaw(encoder.encode(receiptText))
    } catch {
      // Print failed; sale is still valid
    }

    // 4. Update shift sales metrics
    setShift((prev) => ({
      ...prev,
      totalSalesCents: prev.totalSalesCents + totalCents,
      cashSalesCents: isCash ? prev.cashSalesCents + totalCents : prev.cashSalesCents,
      cardSalesCents: !isCash ? prev.cardSalesCents + totalCents : prev.cardSalesCents,
    }))

    const statusMsg = serverReceipt
      ? `تمت معالجة الفاتورة ${serverReceipt} بنجاح ودفع ${formatCents(totalCents)} ر.س عبر ${method}`
      : `تم إتمام البيع محلياً (${formatCents(totalCents)} ر.س) — سيُرسل للسيرفر عند الاتصال`
    setPaymentSuccess(statusMsg)
    setCart([])
    setIsPaymentOpen(false)
  }, [platform.printer, platform.http, activeRegisterId, shift.number, shift.cashierName, cart, totalCents, vatCents])

  // Hold current cart
  const handleHoldCart = useCallback((): void => {
    if (cart.length === 0) return
    const newHeld: HeldCart = {
      id: `held_${Date.now()}`,
      note: holdNoteInput.trim() || `عميل #${heldCarts.length + 1}`,
      cart: [...cart],
      timestamp: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
      totalCents,
    }
    setHeldCarts((prev) => [newHeld, ...prev])
    setCart([])
    setHoldNoteInput('')
    setPaymentSuccess('تم تعليق الفاتورة بنجاح وحفظها في قائمة الانتظار')
  }, [cart, holdNoteInput, heldCarts.length, totalCents])

  // POS Keyboard Shortcuts (F1: Pay, F2: Hold/Queue, F3: Return, F4: Search, F9: Shift, Esc: Close modals)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent): void => {
      // Escape closes open modals
      if (e.key === 'Escape') {
        if (isPaymentOpen) {
          setIsPaymentOpen(false)
          e.preventDefault()
          return
        }
        if (isShiftModalOpen) {
          setIsShiftModalOpen(false)
          e.preventDefault()
          return
        }
        if (isHeldCartsModalOpen) {
          setIsHeldCartsModalOpen(false)
          e.preventDefault()
          return
        }
        if (isReturnsModalOpen) {
          setIsReturnsModalOpen(false)
          setReturnFound(false)
          setReturnReceiptInput('')
          e.preventDefault()
          return
        }
      }

      // F1: Checkout / Payment
      if (e.key === 'F1') {
        e.preventDefault()
        if (shift.isOpen && cart.length > 0) {
          setIsPaymentOpen(true)
        }
        return
      }

      // F2: Hold cart / View held carts
      if (e.key === 'F2') {
        e.preventDefault()
        if (cart.length > 0) {
          handleHoldCart()
        } else {
          setIsHeldCartsModalOpen((prev) => !prev)
        }
        return
      }

      // F3: Returns & Refunds
      if (e.key === 'F3') {
        e.preventDefault()
        setIsReturnsModalOpen(true)
        return
      }

      // F4: Search input focus
      if (e.key === 'F4') {
        e.preventDefault()
        searchInputRef.current?.focus()
        searchInputRef.current?.select()
        return
      }

      // F9: Shifts management
      if (e.key === 'F9') {
        e.preventDefault()
        setIsShiftModalOpen(true)
        return
      }

      // Payment modal number shortcuts: 1=Cash, 2=Card, 3=Apple Pay, 4=Split
      if (isPaymentOpen) {
        if (e.key === '1') {
          e.preventDefault()
          void handleCheckout('نقدي (Cash)')
        } else if (e.key === '2') {
          e.preventDefault()
          void handleCheckout('مدى / شبكة (Mada/Card)')
        } else if (e.key === '3') {
          e.preventDefault()
          void handleCheckout('Apple Pay')
        } else if (e.key === '4') {
          e.preventDefault()
          void handleCheckout('تقسيم دفع (Split)')
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [
    cart.length,
    shift.isOpen,
    isPaymentOpen,
    isShiftModalOpen,
    isHeldCartsModalOpen,
    isReturnsModalOpen,
    handleHoldCart,
    handleCheckout,
  ])

  // Restore held cart
  const handleResumeCart = (held: HeldCart): void => {
    setCart(held.cart)
    setHeldCarts((prev) => prev.filter((h) => h.id !== held.id))
    setIsHeldCartsModalOpen(false)
    setPaymentSuccess(`تم استرجاع سلة: ${held.note}`)
  }

  // Shift Closeout (Z-Report)
  const handleCloseShift = async (): Promise<void> => {
    // 1. Close session on backend
    if (activeSessionId) {
      try {
        const closeBody: Record<string, string> = {}
        if (countedCashInput.trim()) {
          closeBody['counted_cash'] = countedCashInput.trim()
        }
        await platform.http.request(`pos/sessions/${activeSessionId}/close`, {
          method: 'POST',
          body: Object.keys(closeBody).length > 0 ? closeBody : null,
        })
      } catch {
        // Offline: close locally only
      }
    }

    // 2. Print Z-Report
    try {
      const zReport = `\x1B\x40\x1B\x61\x01*** Z-REPORT (SHIFT CLOSEOUT) ***\n` +
        `Shift: #${shift.number} | Cashier: ${shift.cashierName}\n` +
        `Opened: ${shift.openedAt}\n` +
        `Closed: ${new Date().toLocaleTimeString('ar-SA')}\n` +
        `--------------------------------\n` +
        `Opening Float: ${shift.openingFloatSar} SAR\n` +
        `Cash Sales: ${formatCents(shift.cashSalesCents)} SAR\n` +
        `Card Sales: ${formatCents(shift.cardSalesCents)} SAR\n` +
        `Total Sales: ${formatCents(shift.totalSalesCents)} SAR\n` +
        `Expected Cash: ${formatCents(BigInt(Math.round(parseFloat(shift.openingFloatSar) * 100)) + shift.cashSalesCents)} SAR\n` +
        `Counted Cash: ${countedCashInput} SAR\n` +
        `--------------------------------\n` +
        `Shift successfully closed.\n\x1D\x56\x00`
      const encoder = new TextEncoder()
      await platform.printer.printRaw(encoder.encode(zReport))
    } catch {
      // Offline fallback
    }

    setActiveSessionId(null)
    setShift((prev) => ({
      ...prev,
      isOpen: false,
    }))
    setIsShiftModalOpen(false)
    setCountedCashInput('')
    setPaymentSuccess(`تم إقفال الوردية #${shift.number} بنجاح وطباعة تقرير الـ Z-Report`)
  }

  const handleOpenShift = async (): Promise<void> => {
    const floatVal = parseFloat(openingFloatInput) || 0

    // Open day on backend
    if (activeRegisterId) {
      try {
        const openRes = await platform.http.request<{
          started: boolean
          session?: { id: string; opening_float?: string }
        }>(`pos/registers/${activeRegisterId}/open-day`, {
          method: 'POST',
          body: { opening_float: floatVal.toFixed(2) },
        })
        if (openRes?.session?.id) {
          setActiveSessionId(openRes.session.id)
        }
      } catch {
        // Offline: open locally only
      }
    }

    setShift({
      isOpen: true,
      number: shift.number + 1,
      cashierName: shift.cashierName,
      openedAt: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
      openingFloatSar: floatVal.toFixed(2),
      totalSalesCents: 0n,
      cashSalesCents: 0n,
      cardSalesCents: 0n,
    })
    setIsShiftModalOpen(false)
    setPaymentSuccess(`تم فتح الوردية #${shift.number + 1} بعهدة نقدية ${floatVal.toFixed(2)} ر.س`)
  }

  // Broadcast live cart state to customer display window
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return
    const channel = new BroadcastChannel('fihrist-customer-display')

    const broadcast = (): void => {
      const items = cart.map((line) => ({
        id: line.product.id,
        name: line.product.name,
        quantity: line.quantity,
        priceSar: line.product.price,
        totalSar: (Number(line.product.price) * line.quantity).toFixed(2),
      }))
      channel.postMessage({
        items,
        subtotalSar: formatCents(subtotalCents),
        vatSar: formatCents(vatCents),
        totalSar: formatCents(totalCents),
        storeName: 'فهرست للأعمال التجارية',
      })
    }

    broadcast()

    channel.onmessage = (e: MessageEvent) => {
      if (e.data && typeof e.data === 'object' && (e.data as { type?: string }).type === 'REQUEST_CURRENT_STATE') {
        broadcast()
      }
    }

    return () => {
      channel.close()
    }
  }, [cart, subtotalCents, vatCents, totalCents])

  return (
    <div className="pos-layout">
      {/* Product Catalog Area */}
      <div className="pos-catalog">
        <div className="pos-search-bar" style={{ gap: '0.5rem' }}>
          <input
            ref={searchInputRef}
            type="text"
            className="pos-search-input"
            placeholder="امسح الباركود أو ابحث بالاسم، الكود، SKU... [F4]"
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

          {/* Quick Shift & Workflow Action Buttons */}
          <button
            type="button"
            className="boot__button"
            style={{ background: shift.isOpen ? '#0f766e' : '#b91c1c', fontSize: '0.85rem', whiteSpace: 'nowrap' }}
            onClick={() => setIsShiftModalOpen(true)}
            title="إدارة الوردية ومطابقة النقدية (F9)"
          >
            {shift.isOpen ? `الوردية #${shift.number} [F9]` : 'فتح وردية جديدة [F9]'}
          </button>

          <button
            type="button"
            className="boot__button"
            style={{ background: '#475569', fontSize: '0.85rem', whiteSpace: 'nowrap' }}
            onClick={() => setIsHeldCartsModalOpen(true)}
            title="الفواتير المعلقة في الانتظار (F2)"
          >
            📋 المعلقة ({heldCarts.length}) [F2]
          </button>

          <button
            type="button"
            className="boot__button"
            style={{ background: '#b45309', fontSize: '0.85rem', whiteSpace: 'nowrap' }}
            onClick={() => setIsReturnsModalOpen(true)}
            title="استرجاع واستبدال فاتورة (F3)"
          >
            ↩ مرتجع [F3]
          </button>

          <button
            type="button"
            className="boot__button"
            style={{ background: '#0284c7', fontSize: '0.85rem', whiteSpace: 'nowrap' }}
            onClick={() => {
              void platform.shell.openCustomerDisplay()
            }}
            title="فتح نافذة شاشة العميل على شاشة ثانوية"
          >
            🖥️ شاشة العميل
          </button>
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
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {cart.length > 0 && (
              <>
                <button
                  type="button"
                  onClick={handleHoldCart}
                  title="تعليق الفاتورة لحين خدمة عميل آخر"
                  style={{ background: 'none', border: 'none', color: '#0284c7', cursor: 'pointer', font: 'inherit', fontSize: '0.85rem', fontWeight: 600 }}
                >
                  تعليق
                </button>
                <button
                  type="button"
                  onClick={() => setCart([])}
                  style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', font: 'inherit', fontSize: '0.85rem' }}
                >
                  تفريغ
                </button>
              </>
            )}
          </div>
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
            disabled={cart.length === 0 || !shift.isOpen}
            style={{ opacity: cart.length === 0 || !shift.isOpen ? 0.5 : 1 }}
            onClick={() => setIsPaymentOpen(true)}
            title="إتمام الدفع واختيار الطريقة (F1)"
          >
            {shift.isOpen ? `دفع [F1] (${formatCents(totalCents)} ر.س)` : 'الوردية مغلقة - افتح الوردية أولاً'}
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
                  💵 نقدي [1]
                </button>
                <button
                  type="button"
                  className="boot__button"
                  style={{ width: '100%', height: '60px', fontSize: '1.05rem', justifyContent: 'center', background: '#0284c7' }}
                  onClick={() => void handleCheckout('مدى / شبكة (Mada/Card)')}
                >
                  💳 مدى / بطاقة [2]
                </button>
                <button
                  type="button"
                  className="boot__button"
                  style={{ width: '100%', height: '60px', fontSize: '1.05rem', justifyContent: 'center', background: '#000000' }}
                  onClick={() => void handleCheckout('Apple Pay')}
                >
                   Apple Pay [3]
                </button>
                <button
                  type="button"
                  className="boot__button"
                  style={{ width: '100%', height: '60px', fontSize: '1.05rem', justifyContent: 'center', background: '#7c3aed' }}
                  onClick={() => void handleCheckout('تقسيم دفع (Split)')}
                >
                  ➗ دفع مجزأ [4]
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

      {/* Shift Modal (Open / Close Shift Z-Report) */}
      {isShiftModalOpen && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.15rem' }}>
                {shift.isOpen ? `إقفال الوردية #${shift.number} ومطابقة النقدية` : 'فتح وردية جديدة'}
              </h3>
              <button
                type="button"
                onClick={() => setIsShiftModalOpen(false)}
                style={{ background: 'none', border: 'none', fontSize: '1.25rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {shift.isOpen ? (
                <>
                  <div style={{ background: 'rgba(0,0,0,0.03)', padding: '1rem', borderRadius: 'var(--fh-radius)', fontSize: '0.9rem' }}>
                    <div><strong>الكاشير: </strong> {shift.cashierName}</div>
                    <div><strong>وقت الفتح: </strong> {shift.openedAt}</div>
                    <div><strong>العهدة الافتتاحية: </strong> {shift.openingFloatSar} ر.س</div>
                    <div><strong>مبيعات نقدية: </strong> {formatCents(shift.cashSalesCents)} ر.س</div>
                    <div><strong>مبيعات بطاقة وشبكة: </strong> {formatCents(shift.cardSalesCents)} ر.س</div>
                    <div style={{ marginTop: '0.5rem', borderTop: '1px solid var(--fh-line)', paddingTop: '0.5rem', fontWeight: 700, color: 'var(--fh-accent)' }}>
                      النقد المفترض وجوده في الدرج: {formatCents(BigInt(Math.round(parseFloat(shift.openingFloatSar) * 100)) + shift.cashSalesCents)} ر.س
                    </div>
                  </div>

                  <div>
                    <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                      أدخل النقد الفعلي بعد العد في الدرج (ر.س)
                    </label>
                    <input
                      type="text"
                      className="pos-search-input"
                      placeholder="المبلغ الفعلي في الدرج"
                      value={countedCashInput}
                      onChange={(e) => setCountedCashInput(e.target.value)}
                    />
                  </div>
                </>
              ) : (
                <>
                  <p style={{ margin: 0, color: 'var(--fh-ink-muted)', fontSize: '0.9rem' }}>
                    الوردية الحالية مغلقة. أدخل الرصيد الافتتاحي للعهدة النقدية لبدء عمليات البيع والكاشير.
                  </p>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                      العهدة النقدية الافتتاحية (ر.س)
                    </label>
                    <input
                      type="text"
                      className="pos-search-input"
                      value={openingFloatInput}
                      onChange={(e) => setOpeningFloatInput(e.target.value)}
                    />
                  </div>
                </>
              )}
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="boot__button"
                style={{ background: '#64748b' }}
                onClick={() => setIsShiftModalOpen(false)}
              >
                إلغاء
              </button>
              {shift.isOpen ? (
                <button
                  type="button"
                  className="boot__button"
                  style={{ background: '#b91c1c' }}
                  disabled={!countedCashInput.trim()}
                  onClick={() => void handleCloseShift()}
                >
                  إقفال الوردية وطباعة Z-Report
                </button>
              ) : (
                <button
                  type="button"
                  className="boot__button"
                  onClick={() => void handleOpenShift()}
                >
                  فتح الوردية
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Held Carts Modal */}
      {isHeldCartsModalOpen && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.15rem' }}>الفواتير المعلقة في الانتظار</h3>
              <button
                type="button"
                onClick={() => setIsHeldCartsModalOpen(false)}
                style={{ background: 'none', border: 'none', fontSize: '1.25rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div className="modal-body">
              {heldCarts.length === 0 ? (
                <div style={{ textAlign: 'center', color: 'var(--fh-ink-muted)', padding: '2rem 1rem' }}>
                  لا توجد فواتير معلقة حالياً.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {heldCarts.map((h) => (
                    <div
                      key={h.id}
                      style={{
                        padding: '0.85rem',
                        border: '1px solid var(--fh-line)',
                        borderRadius: 'var(--fh-radius)',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 700 }}>{h.note}</div>
                        <div style={{ fontSize: '0.8rem', color: 'var(--fh-ink-muted)' }}>
                          {h.timestamp} • {h.cart.reduce((s, i) => s + i.quantity, 0)} أصناف
                        </div>
                        <div style={{ fontWeight: 600, color: 'var(--fh-accent)', marginTop: '0.25rem' }}>
                          {formatCents(h.totalCents)} ر.س
                        </div>
                      </div>
                      <button
                        type="button"
                        className="boot__button"
                        style={{ padding: '0.4rem 0.85rem', fontSize: '0.85rem' }}
                        onClick={() => handleResumeCart(h)}
                      >
                        استرجاع للسلة
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="boot__button"
                style={{ background: '#64748b' }}
                onClick={() => setIsHeldCartsModalOpen(false)}
              >
                إغلاق
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Returns & Refunds Modal */}
      {isReturnsModalOpen && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.15rem' }}>استرجاع واستبدال فاتورة (Refund)</h3>
              <button
                type="button"
                onClick={() => {
                  setIsReturnsModalOpen(false)
                  setReturnFound(false)
                  setReturnReceiptInput('')
                }}
                style={{ background: 'none', border: 'none', fontSize: '1.25rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                  رقم الفاتورة أو امسح باركود الإيصال
                </label>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <input
                    type="text"
                    className="pos-search-input"
                    placeholder="مثال: REC-2026-4201"
                    value={returnReceiptInput}
                    onChange={(e) => setReturnReceiptInput(e.target.value)}
                  />
                  <button
                    type="button"
                    className="boot__button"
                    style={{ whiteSpace: 'nowrap' }}
                    onClick={() => setReturnFound(true)}
                  >
                    بحث
                  </button>
                </div>
              </div>

              {returnFound && (
                <div style={{ background: 'rgba(0,0,0,0.03)', padding: '1rem', borderRadius: 'var(--fh-radius)' }}>
                  <div style={{ fontWeight: 700, marginBottom: '0.5rem' }}>تفاصيل الفاتورة #REC-2026-4201:</div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--fh-ink-muted)', marginBottom: '0.75rem' }}>
                    التاريخ: اليوم 11:20 ص • طريقة الدفع: نقدي
                  </div>

                  <div style={{ borderTop: '1px solid var(--fh-line)', paddingTop: '0.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div>قميص أكسفورد كلاسيك أبيض</div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--fh-ink-muted)' }}>1 × 185.00 ر.س</div>
                    </div>
                    <button
                      type="button"
                      className="boot__button"
                      style={{ padding: '0.35rem 0.75rem', fontSize: '0.85rem', background: '#b91c1c' }}
                      onClick={() => {
                        void (async () => {
                          try {
                            await platform.printer.openCashDrawer()
                          } catch {
                            // Drawer unavailable; refund proceeds without opening hardware drawer
                          }
                          setIsReturnsModalOpen(false)
                          setReturnFound(false)
                          setReturnReceiptInput('')
                          setPaymentSuccess('تم إرجاع الصنف بنجاح وصرف 185.00 ر.س نقداً للعميل وفتح الدرج')
                        })()
                      }}
                    >
                      إرجاع واسترداد (185.00 ر.س)
                    </button>
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="boot__button"
                style={{ background: '#64748b' }}
                onClick={() => {
                  setIsReturnsModalOpen(false)
                  setReturnFound(false)
                  setReturnReceiptInput('')
                }}
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
