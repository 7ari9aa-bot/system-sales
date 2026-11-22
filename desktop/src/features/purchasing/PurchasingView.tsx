import { useState, type FC } from 'react'
import { formatSar } from '@/shared/money'

export interface Supplier {
  readonly id: string
  readonly name: string
  readonly phone: string
  readonly contactPerson: string
  balanceSar: string // Outstanding balance owed to supplier
}

export interface PurchaseOrderItem {
  readonly productId: string
  readonly productName: string
  readonly quantity: number
  readonly unitCost: string
}

export interface PurchaseOrder {
  readonly id: string
  readonly poNumber: string
  readonly supplierId: string
  readonly supplierName: string
  readonly orderDate: string
  readonly totalSar: string
  status: 'pending' | 'received' | 'paid'
  readonly items: PurchaseOrderItem[]
}

const INITIAL_SUPPLIERS: Supplier[] = [
  { id: 's1', name: 'شركة نسيج الجزيرة للأقمشة والملابس', phone: '0501122334', contactPerson: 'سلمان العتيبي', balanceSar: '12400.00' },
  { id: 's2', name: 'مؤسسة الرياض للأحذية والمصنوعات الجلدية', phone: '0559988776', contactPerson: 'فهد القحطاني', balanceSar: '6800.00' },
  { id: 's3', name: 'شركة أطياب الشرق للعطور والزيوت', phone: '0543322110', contactPerson: 'بندر الشمري', balanceSar: '0.00' },
]

const INITIAL_PURCHASE_ORDERS: PurchaseOrder[] = [
  {
    id: 'po1',
    poNumber: 'PO-2026-001',
    supplierId: 's1',
    supplierName: 'شركة نسيج الجزيرة للأقمشة والملابس',
    orderDate: '2026-11-18',
    totalSar: '18500.00',
    status: 'received',
    items: [
      { productId: 'i1', productName: 'قميص أكسفورد كلاسيك أبيض', quantity: 100, unitCost: '90.00' },
      { productId: 'i3', productName: 'تي شيرت قطن مصري أسود', quantity: 200, unitCost: '45.00' },
    ],
  },
  {
    id: 'po2',
    poNumber: 'PO-2026-002',
    supplierId: 's2',
    supplierName: 'مؤسسة الرياض للأحذية والمصنوعات الجلدية',
    orderDate: '2026-11-20',
    totalSar: '6800.00',
    status: 'pending',
    items: [
      { productId: 'i4', productName: 'حذاء كاجوال جلد بني', quantity: 40, unitCost: '170.00' },
    ],
  },
]

export const PurchasingView: FC = () => {
  const [activeTab, setActiveTab] = useState<'orders' | 'suppliers'>('orders')
  const [orders, setOrders] = useState<PurchaseOrder[]>(INITIAL_PURCHASE_ORDERS)
  const [suppliers, setSuppliers] = useState<Supplier[]>(INITIAL_SUPPLIERS)
  const [search, setSearch] = useState('')

  // Modals
  const [isNewPoOpen, setIsNewPoOpen] = useState(false)
  const [isNewSupplierOpen, setIsNewSupplierOpen] = useState(false)
  const [isPaymentOpen, setIsPaymentOpen] = useState(false)
  const [selectedSupplierForPayment, setSelectedSupplierForPayment] = useState<Supplier | null>(null)
  const [paymentAmount, setPaymentAmount] = useState('')

  // New PO form state
  const [newPoSupplierId, setNewPoSupplierId] = useState(suppliers[0]?.id ?? '')
  const [newPoItemName, setNewPoItemName] = useState('')
  const [newPoItemQty, setNewPoItemQty] = useState(10)
  const [newPoItemCost, setNewPoItemCost] = useState('50.00')

  // New Supplier form state
  const [newSupName, setNewSupName] = useState('')
  const [newSupPhone, setNewSupPhone] = useState('')
  const [newSupContact, setNewSupContact] = useState('')

  const handleCreatePo = (): void => {
    const supplier = suppliers.find((s) => s.id === newPoSupplierId)
    if (!supplier || !newPoItemName.trim()) return

    const total = (newPoItemQty * parseFloat(newPoItemCost || '0')).toFixed(2)
    const newPo: PurchaseOrder = {
      id: `po_${Date.now()}`,
      poNumber: `PO-2026-00${orders.length + 1}`,
      supplierId: supplier.id,
      supplierName: supplier.name,
      orderDate: new Date().toISOString().split('T')[0] ?? '2026-11-21',
      totalSar: total,
      status: 'pending',
      items: [
        {
          productId: `custom_${Date.now()}`,
          productName: newPoItemName.trim(),
          quantity: newPoItemQty,
          unitCost: newPoItemCost,
        },
      ],
    }

    setOrders((prev) => [newPo, ...prev])
    setIsNewPoOpen(false)
    setNewPoItemName('')
  }

  const handleCreateSupplier = (): void => {
    if (!newSupName.trim()) return
    const newSupplier: Supplier = {
      id: `s_${Date.now()}`,
      name: newSupName.trim(),
      phone: newSupPhone.trim() || '05XXXXXXXX',
      contactPerson: newSupContact.trim() || 'المسؤول التجاري',
      balanceSar: '0.00',
    }
    setSuppliers((prev) => [...prev, newSupplier])
    setIsNewSupplierOpen(false)
    setNewSupName('')
    setNewSupPhone('')
    setNewSupContact('')
  }

  const handleReceiveOrder = (poId: string): void => {
    setOrders((prev) =>
      prev.map((o) => {
        if (o.id === poId) {
          return { ...o, status: 'received' }
        }
        return o
      }),
    )
  }

  const handleRecordPayment = (): void => {
    if (!selectedSupplierForPayment || !paymentAmount) return
    const payVal = parseFloat(paymentAmount)
    if (isNaN(payVal) || payVal <= 0) return

    setSuppliers((prev) =>
      prev.map((s) => {
        if (s.id === selectedSupplierForPayment.id) {
          const current = parseFloat(s.balanceSar)
          const nextBal = Math.max(0, current - payVal).toFixed(2)
          return { ...s, balanceSar: nextBal }
        }
        return s
      }),
    )

    setIsPaymentOpen(false)
    setSelectedSupplierForPayment(null)
    setPaymentAmount('')
  }

  const filteredOrders = orders.filter((o) => {
    const q = search.trim().toLowerCase()
    if (!q) return true
    return o.poNumber.toLowerCase().includes(q) || o.supplierName.toLowerCase().includes(q)
  })

  const filteredSuppliers = suppliers.filter((s) => {
    const q = search.trim().toLowerCase()
    if (!q) return true
    return s.name.toLowerCase().includes(q) || s.phone.includes(q) || s.contactPerson.toLowerCase().includes(q)
  })

  return (
    <div className="workstation__content">
      {/* Header & Sub-Navigation */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            type="button"
            className={`boot__button ${activeTab === 'orders' ? '' : 'boot__button--secondary'}`}
            style={{ background: activeTab === 'orders' ? 'var(--fh-accent)' : 'transparent', color: activeTab === 'orders' ? '#fff' : 'var(--fh-ink)' }}
            onClick={() => setActiveTab('orders')}
          >
            📋 أوامر الشراء ({orders.length})
          </button>
          <button
            type="button"
            className={`boot__button ${activeTab === 'suppliers' ? '' : 'boot__button--secondary'}`}
            style={{ background: activeTab === 'suppliers' ? 'var(--fh-accent)' : 'transparent', color: activeTab === 'suppliers' ? '#fff' : 'var(--fh-ink)' }}
            onClick={() => setActiveTab('suppliers')}
          >
            🏢 قاعدة الموردين ({suppliers.length})
          </button>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem' }}>
          {activeTab === 'orders' ? (
            <button
              type="button"
              className="boot__button"
              onClick={() => setIsNewPoOpen(true)}
            >
              + إنشاء أمر شراء جديد
            </button>
          ) : (
            <button
              type="button"
              className="boot__button"
              onClick={() => setIsNewSupplierOpen(true)}
            >
              + إضافة مورد جديد
            </button>
          )}
        </div>
      </div>

      {/* Search Input */}
      <div>
        <input
          type="text"
          className="pos-search-input"
          style={{ maxWidth: '420px' }}
          placeholder={activeTab === 'orders' ? 'بحث برقم أمر الشراء أو اسم المورد...' : 'بحث في الموردين بالاسم أو رقم الجوال...'}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Orders View */}
      {activeTab === 'orders' && (
        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>رقم الطلب</th>
                <th>المورد</th>
                <th>التاريخ</th>
                <th>عدد الأصناف</th>
                <th>إجمالي القيمة</th>
                <th>حالة الاستلام</th>
                <th>إجراءات</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.map((po) => {
                const totalItems = po.items.reduce((s, i) => s + i.quantity, 0)
                let statusBadge = 'workstation__badge--online'
                let statusText = 'تم الاستلام'
                if (po.status === 'pending') {
                  statusBadge = 'workstation__badge--shift'
                  statusText = 'بانتظار الاستلام'
                } else if (po.status === 'paid') {
                  statusBadge = 'workstation__badge--online'
                  statusText = 'مسددة'
                }

                return (
                  <tr key={po.id}>
                    <td style={{ fontWeight: 700, fontFamily: 'monospace' }}>{po.poNumber}</td>
                    <td>{po.supplierName}</td>
                    <td style={{ color: 'var(--fh-ink-muted)', fontSize: '0.85rem' }}>{po.orderDate}</td>
                    <td>{totalItems} قطعة ({po.items.length} أصناف)</td>
                    <td style={{ fontWeight: 600 }}>{formatSar(po.totalSar)}</td>
                    <td>
                      <span className={`workstation__badge ${statusBadge}`}>
                        {statusText}
                      </span>
                    </td>
                    <td>
                      {po.status === 'pending' ? (
                        <button
                          type="button"
                          className="boot__button"
                          style={{ padding: '0.35rem 0.75rem', fontSize: '0.85rem', background: '#0284c7' }}
                          onClick={() => handleReceiveOrder(po.id)}
                        >
                          استلام ومطابقة
                        </button>
                      ) : (
                        <span style={{ fontSize: '0.85rem', color: '#16a34a' }}>✓ مكتمل</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Suppliers View */}
      {activeTab === 'suppliers' && (
        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>اسم الشركة / المورد</th>
                <th>رقم الهاتف</th>
                <th>مسؤول التواصل</th>
                <th>الرصيد المستحق (SAR)</th>
                <th>إجراءات</th>
              </tr>
            </thead>
            <tbody>
              {filteredSuppliers.map((s) => {
                const hasDues = parseFloat(s.balanceSar) > 0
                return (
                  <tr key={s.id}>
                    <td style={{ fontWeight: 600 }}>{s.name}</td>
                    <td style={{ direction: 'ltr', textAlign: 'right' }}>{s.phone}</td>
                    <td>{s.contactPerson}</td>
                    <td style={{ fontWeight: 700, color: hasDues ? '#dc2626' : '#16a34a' }}>
                      {formatSar(s.balanceSar)}
                    </td>
                    <td>
                      {hasDues ? (
                        <button
                          type="button"
                          className="boot__button"
                          style={{ padding: '0.35rem 0.75rem', fontSize: '0.85rem', background: '#0f766e' }}
                          onClick={() => {
                            setSelectedSupplierForPayment(s)
                            setPaymentAmount(s.balanceSar)
                            setIsPaymentOpen(true)
                          }}
                        >
                          سداد دفعة
                        </button>
                      ) : (
                        <span style={{ fontSize: '0.85rem', color: 'var(--fh-ink-muted)' }}>لا توجد مستحقات</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal: New Purchase Order */}
      {isNewPoOpen && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.15rem' }}>إنشاء أمر شراء بضاعة (PO)</h3>
              <button
                type="button"
                onClick={() => setIsNewPoOpen(false)}
                style={{ background: 'none', border: 'none', fontSize: '1.25rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                  المورد
                </label>
                <select
                  className="pos-search-input"
                  value={newPoSupplierId}
                  onChange={(e) => setNewPoSupplierId(e.target.value)}
                >
                  {suppliers.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                  الصنف / البضاعة المطلوبة
                </label>
                <input
                  type="text"
                  className="pos-search-input"
                  placeholder="مثال: قميص أكسفورد كلاسيك أبيض"
                  value={newPoItemName}
                  onChange={(e) => setNewPoItemName(e.target.value)}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                    الكمية
                  </label>
                  <input
                    type="number"
                    className="pos-search-input"
                    value={newPoItemQty}
                    onChange={(e) => setNewPoItemQty(parseInt(e.target.value, 10) || 1)}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                    سعر التكلفة للوحدة (ر.س)
                  </label>
                  <input
                    type="text"
                    className="pos-search-input"
                    value={newPoItemCost}
                    onChange={(e) => setNewPoItemCost(e.target.value)}
                  />
                </div>
              </div>

              <div style={{ padding: '0.75rem', background: 'rgba(0,0,0,0.03)', borderRadius: 'var(--fh-radius)' }}>
                <strong>الإجمالي المقدر: </strong>
                <span>{formatSar((newPoItemQty * parseFloat(newPoItemCost || '0')).toFixed(2))}</span>
              </div>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="boot__button"
                style={{ background: '#64748b' }}
                onClick={() => setIsNewPoOpen(false)}
              >
                إلغاء
              </button>
              <button
                type="button"
                className="boot__button"
                disabled={!newPoItemName.trim()}
                onClick={handleCreatePo}
              >
                حفظ أمر الشراء
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: New Supplier */}
      {isNewSupplierOpen && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.15rem' }}>إضافة مورد جديد</h3>
              <button
                type="button"
                onClick={() => setIsNewSupplierOpen(false)}
                style={{ background: 'none', border: 'none', fontSize: '1.25rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                  اسم المورد / المنشأة
                </label>
                <input
                  type="text"
                  className="pos-search-input"
                  placeholder="مثال: شركة التوزيع الحديثة"
                  value={newSupName}
                  onChange={(e) => setNewSupName(e.target.value)}
                />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                  رقم الهاتف
                </label>
                <input
                  type="text"
                  className="pos-search-input"
                  placeholder="05XXXXXXXX"
                  value={newSupPhone}
                  onChange={(e) => setNewSupPhone(e.target.value)}
                />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                  مسؤول المبيعات / التواصل
                </label>
                <input
                  type="text"
                  className="pos-search-input"
                  placeholder="الاسم"
                  value={newSupContact}
                  onChange={(e) => setNewSupContact(e.target.value)}
                />
              </div>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="boot__button"
                style={{ background: '#64748b' }}
                onClick={() => setIsNewSupplierOpen(false)}
              >
                إلغاء
              </button>
              <button
                type="button"
                className="boot__button"
                disabled={!newSupName.trim()}
                onClick={handleCreateSupplier}
              >
                حفظ المورد
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Record Supplier Payment */}
      {isPaymentOpen && selectedSupplierForPayment && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '1.15rem' }}>تسجيل سداد دفعة للمورد</h3>
              <button
                type="button"
                onClick={() => setIsPaymentOpen(false)}
                style={{ background: 'none', border: 'none', fontSize: '1.25rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div>
                <strong>المورد: </strong> {selectedSupplierForPayment.name}
              </div>
              <div>
                <strong>الرصيد القائم: </strong> {formatSar(selectedSupplierForPayment.balanceSar)}
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                  مبلغ الدفعة المسددة (ر.س)
                </label>
                <input
                  type="text"
                  className="pos-search-input"
                  value={paymentAmount}
                  onChange={(e) => setPaymentAmount(e.target.value)}
                />
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
              <button
                type="button"
                className="boot__button"
                onClick={handleRecordPayment}
              >
                تأكيد السداد وتحديث الحساب
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
