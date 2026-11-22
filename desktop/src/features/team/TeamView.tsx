import { useState, type FC } from 'react'

export interface StaffMember {
  readonly id: string
  readonly name: string
  readonly username: string
  readonly role: 'manager' | 'cashier' | 'stock_keeper' | 'accountant'
  readonly branch: string
  readonly isActive: boolean
  readonly lastLogin: string
}

const INITIAL_STAFF: readonly StaffMember[] = [
  { id: 'u1', name: 'سلمان العتيبي', username: 'salman', role: 'manager', branch: 'الفرع الرئيسي', isActive: true, lastLogin: '2026-11-22 08:15' },
  { id: 'u2', name: 'أحمد محمود', username: 'ahmed_pos', role: 'cashier', branch: 'الفرع الرئيسي', isActive: true, lastLogin: '2026-11-22 08:00' },
  { id: 'u3', name: 'سارة خالد', username: 'sara_k', role: 'cashier', branch: 'الفرع الرئيسي', isActive: true, lastLogin: '2026-11-21 15:55' },
  { id: 'u4', name: 'فهد القحطاني', username: 'fahad_inv', role: 'stock_keeper', branch: 'المستودع المركزي', isActive: true, lastLogin: '2026-11-22 07:45' },
  { id: 'u5', name: 'منى السعيد', username: 'mona_acc', role: 'accountant', branch: 'الإدارة العامة', isActive: false, lastLogin: '2026-11-19 12:30' },
]

interface AuditLogEntry {
  readonly id: string
  readonly timestamp: string
  readonly staffName: string
  readonly action: string
  readonly target: string
  readonly status: 'success' | 'warning' | 'alert'
}

const SAMPLE_LOGS: readonly AuditLogEntry[] = [
  { id: 'log1', timestamp: '2026-11-22 14:30', staffName: 'أحمد محمود', action: 'إتمام عملية بيع', target: 'INV-2026-0891 (345.00 ر.س)', status: 'success' },
  { id: 'log2', timestamp: '2026-11-22 13:15', staffName: 'سلمان العتيبي', action: 'موافقة على خصم استثنائي (15%)', target: 'INV-2026-0888', status: 'warning' },
  { id: 'log3', timestamp: '2026-11-22 11:40', staffName: 'فهد القحطاني', action: 'تسجيل استلام شحنة مشتريات', target: 'PO-2026-001', status: 'success' },
  { id: 'log4', timestamp: '2026-11-22 08:00', staffName: 'أحمد محمود', action: 'فتح وردية كاشير', target: 'SH-2026-112 (افتتاحي 500.00 ر.س)', status: 'success' },
  { id: 'log5', timestamp: '2026-11-21 21:10', staffName: 'سارة خالد', action: 'فتح درج النقدية يدويًا بدون بيع', target: 'صندوق رقم 2', status: 'alert' },
]

export const TeamView: FC = () => {
  const [staffList, setStaffList] = useState<readonly StaffMember[]>(INITIAL_STAFF)
  const [activeSubTab, setActiveSubTab] = useState<'members' | 'permissions' | 'audit'>('members')
  const [showAddModal, setShowAddModal] = useState<boolean>(false)
  const [newName, setNewName] = useState<string>('')
  const [newUsername, setNewUsername] = useState<string>('')
  const [newRole, setNewRole] = useState<'manager' | 'cashier' | 'stock_keeper' | 'accountant'>('cashier')
  const [newBranch, setNewBranch] = useState<string>('الفرع الرئيسي')

  const handleAddMember = (e: React.FormEvent) => {
    e.preventDefault()
    if (!newName.trim() || !newUsername.trim()) return

    const newMember: StaffMember = {
      id: `u_${Date.now()}`,
      name: newName.trim(),
      username: newUsername.trim(),
      role: newRole,
      branch: newBranch,
      isActive: true,
      lastLogin: 'لم يسجل دخول بعد',
    }

    setStaffList((prev) => [...prev, newMember])
    setShowAddModal(false)
    setNewName('')
    setNewUsername('')
  }

  const toggleMemberStatus = (id: string) => {
    setStaffList((prev) =>
      prev.map((m) => (m.id === id ? { ...m, isActive: !m.isActive } : m)),
    )
  }

  const getRoleBadge = (role: StaffMember['role']) => {
    switch (role) {
      case 'manager':
        return <span style={{ padding: '0.2rem 0.6rem', borderRadius: '4px', fontSize: '0.8rem', background: '#f3e8ff', color: '#6b21a8' }}>مدير فرع</span>
      case 'cashier':
        return <span style={{ padding: '0.2rem 0.6rem', borderRadius: '4px', fontSize: '0.8rem', background: '#dbeafe', color: '#1e40af' }}>كاشير</span>
      case 'stock_keeper':
        return <span style={{ padding: '0.2rem 0.6rem', borderRadius: '4px', fontSize: '0.8rem', background: '#fef3c7', color: '#92400e' }}>أمين مخزن</span>
      case 'accountant':
        return <span style={{ padding: '0.2rem 0.6rem', borderRadius: '4px', fontSize: '0.8rem', background: '#dcfce7', color: '#166534' }}>محاسب</span>
    }
  }

  return (
    <div className="workstation__content" dir="rtl" style={{ padding: '1.5rem', overflowY: 'auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 'bold', margin: 0 }}>👥 إدارة الموظفين والصلاحيات</h2>
          <p style={{ color: '#64748b', fontSize: '0.9rem', margin: '0.25rem 0 0 0' }}>
            التحكم بفريق العمل، تعيين الصلاحيات، متابعة الورديات، وسجل الأمان الرقابي
          </p>
        </div>

        <button
          type="button"
          onClick={() => setShowAddModal(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            backgroundColor: '#0284c7',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            padding: '0.6rem 1.25rem',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          ➕ إضافة موظف جديد
        </button>
      </div>

      {/* Sub Tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '2px solid #e2e8f0', marginBottom: '1.5rem' }}>
        <button
          type="button"
          onClick={() => setActiveSubTab('members')}
          style={{
            padding: '0.75rem 1.25rem',
            border: 'none',
            background: 'none',
            borderBottom: activeSubTab === 'members' ? '3px solid #0284c7' : '3px solid transparent',
            color: activeSubTab === 'members' ? '#0284c7' : '#64748b',
            fontWeight: activeSubTab === 'members' ? 'bold' : 'normal',
            cursor: 'pointer',
            fontSize: '1rem',
          }}
        >
          👤 قائمة الموظفين ({staffList.length})
        </button>

        <button
          type="button"
          onClick={() => setActiveSubTab('permissions')}
          style={{
            padding: '0.75rem 1.25rem',
            border: 'none',
            background: 'none',
            borderBottom: activeSubTab === 'permissions' ? '3px solid #0284c7' : '3px solid transparent',
            color: activeSubTab === 'permissions' ? '#0284c7' : '#64748b',
            fontWeight: activeSubTab === 'permissions' ? 'bold' : 'normal',
            cursor: 'pointer',
            fontSize: '1rem',
          }}
        >
          🛡️ مصفوفة الصلاحيات
        </button>

        <button
          type="button"
          onClick={() => setActiveSubTab('audit')}
          style={{
            padding: '0.75rem 1.25rem',
            border: 'none',
            background: 'none',
            borderBottom: activeSubTab === 'audit' ? '3px solid #0284c7' : '3px solid transparent',
            color: activeSubTab === 'audit' ? '#0284c7' : '#64748b',
            fontWeight: activeSubTab === 'audit' ? 'bold' : 'normal',
            cursor: 'pointer',
            fontSize: '1rem',
          }}
        >
          📋 سجل النشاط والرقابة
        </button>
      </div>

      {/* Tab 1: Members Table */}
      {activeSubTab === 'members' && (
        <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'right', fontSize: '0.9rem' }}>
            <thead style={{ background: '#f1f5f9', borderBottom: '1px solid #cbd5e1' }}>
              <tr>
                <th style={{ padding: '0.75rem 1rem' }}>الاسم</th>
                <th style={{ padding: '0.75rem 1rem' }}>اسم المستخدم</th>
                <th style={{ padding: '0.75rem 1rem' }}>الدور الوظيفي</th>
                <th style={{ padding: '0.75rem 1rem' }}>الفرع</th>
                <th style={{ padding: '0.75rem 1rem' }}>آخر تسجيل دخول</th>
                <th style={{ padding: '0.75rem 1rem' }}>الحالة</th>
                <th style={{ padding: '0.75rem 1rem' }}>الإجراءات</th>
              </tr>
            </thead>
            <tbody>
              {staffList.map((m) => (
                <tr key={m.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '0.75rem 1rem', fontWeight: 600 }}>{m.name}</td>
                  <td style={{ padding: '0.75rem 1rem', color: '#64748b' }}>@{m.username}</td>
                  <td style={{ padding: '0.75rem 1rem' }}>{getRoleBadge(m.role)}</td>
                  <td style={{ padding: '0.75rem 1rem' }}>{m.branch}</td>
                  <td style={{ padding: '0.75rem 1rem', color: '#64748b', fontSize: '0.8rem' }}>{m.lastLogin}</td>
                  <td style={{ padding: '0.75rem 1rem' }}>
                    <span style={{
                      padding: '0.2rem 0.6rem',
                      borderRadius: '4px',
                      fontSize: '0.8rem',
                      background: m.isActive ? '#dcfce7' : '#fee2e2',
                      color: m.isActive ? '#166534' : '#991b1b',
                    }}>
                      {m.isActive ? 'نشط' : 'معطل'}
                    </span>
                  </td>
                  <td style={{ padding: '0.75rem 1rem' }}>
                    <button
                      type="button"
                      onClick={() => toggleMemberStatus(m.id)}
                      style={{
                        padding: '0.3rem 0.6rem',
                        fontSize: '0.8rem',
                        border: '1px solid #cbd5e1',
                        borderRadius: '4px',
                        background: 'white',
                        cursor: 'pointer',
                      }}
                    >
                      {m.isActive ? 'تعطيل الحساب' : 'تفعيل الحساب'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 2: Permissions Matrix */}
      {activeSubTab === 'permissions' && (
        <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'right', fontSize: '0.9rem' }}>
            <thead style={{ background: '#f1f5f9', borderBottom: '1px solid #cbd5e1' }}>
              <tr>
                <th style={{ padding: '0.75rem 1rem' }}>الصلاحية</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>مدير الفرع</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>الكاشير</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>أمين المخزن</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>المحاسب</th>
              </tr>
            </thead>
            <tbody>
              {[
                { perm: 'تسجيل عمليات البيع وطباعة الفاتورة', manager: '✅ مسموح', cashier: '✅ مسموح', stock: '❌ ممنوع', acc: '❌ ممنوع' },
                { perm: 'تطبيق خصم على الفاتورة أو المنتج', manager: '✅ مسموح', cashier: '⚠️ حتى 5%', stock: '❌ ممنوع', acc: '✅ مسموح' },
                { perm: 'تعديل سعر البيع يدوياً', manager: '✅ مسموح', cashier: '🔒 بموافقة المدير', stock: '❌ ممنوع', acc: '🔒 بموافقة المدير' },
                { perm: 'فتح درج الكاشير بدون عملية بيع', manager: '✅ مسموح', cashier: '🔒 بتسجيل سبب', stock: '❌ ممنوع', acc: '❌ ممنوع' },
                { perm: 'استرجاع الفواتير واستبدال الأصناف', manager: '✅ مسموح', cashier: '✅ مسموح بالباركود', stock: '❌ ممنوع', acc: '✅ مسموح' },
                { perm: 'إجراء الجرد وتعديل أرصدة المخزون', manager: '✅ مسموح', cashier: '❌ ممنوع', stock: '✅ مسموح', acc: '🔒 مراجعة فقط' },
                { perm: 'إنشاء أوامر الشراء واعتماد الموردين', manager: '✅ مسموح', cashier: '❌ ممنوع', stock: '🔒 طلب فقط', acc: '✅ مسموح' },
                { perm: 'الاطلاع على أرباح المتجر والتقارير المالية', manager: '✅ مسموح', cashier: '❌ ممنوع', stock: '❌ ممنوع', acc: '✅ مسموح' },
              ].map((row, idx) => (
                <tr key={idx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '0.75rem 1rem', fontWeight: 600 }}>{row.perm}</td>
                  <td style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>{row.manager}</td>
                  <td style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>{row.cashier}</td>
                  <td style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>{row.stock}</td>
                  <td style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>{row.acc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 3: Audit Log */}
      {activeSubTab === 'audit' && (
        <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'right', fontSize: '0.9rem' }}>
            <thead style={{ background: '#f1f5f9', borderBottom: '1px solid #cbd5e1' }}>
              <tr>
                <th style={{ padding: '0.75rem 1rem' }}>التاريخ والوقت</th>
                <th style={{ padding: '0.75rem 1rem' }}>الموظف</th>
                <th style={{ padding: '0.75rem 1rem' }}>العملية</th>
                <th style={{ padding: '0.75rem 1rem' }}>الهدف / التفاصيل</th>
                <th style={{ padding: '0.75rem 1rem' }}>مستوى الأمان</th>
              </tr>
            </thead>
            <tbody>
              {SAMPLE_LOGS.map((log) => (
                <tr key={log.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '0.75rem 1rem', color: '#64748b' }}>{log.timestamp}</td>
                  <td style={{ padding: '0.75rem 1rem', fontWeight: 600 }}>{log.staffName}</td>
                  <td style={{ padding: '0.75rem 1rem' }}>{log.action}</td>
                  <td style={{ padding: '0.75rem 1rem' }}>{log.target}</td>
                  <td style={{ padding: '0.75rem 1rem' }}>
                    <span style={{
                      padding: '0.2rem 0.6rem',
                      borderRadius: '4px',
                      fontSize: '0.8rem',
                      background: log.status === 'success' ? '#dcfce7' : log.status === 'warning' ? '#fef9c3' : '#fee2e2',
                      color: log.status === 'success' ? '#166534' : log.status === 'warning' ? '#854d0e' : '#991b1b',
                    }}>
                      {log.status === 'success' ? 'عادي' : log.status === 'warning' ? 'استثنائي' : 'تنبيه أمني'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add Staff Modal */}
      {showAddModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
        }}>
          <div style={{
            background: 'white',
            borderRadius: '12px',
            padding: '2rem',
            width: '100%',
            maxWidth: '460px',
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1)',
          }}>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 'bold', margin: '0 0 1rem 0' }}>إضافة موظف جديد</h3>
            <form onSubmit={handleAddMember}>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.35rem' }}>اسم الموظف</label>
                <input
                  type="text"
                  required
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="مثال: تركي الشمري"
                  style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                />
              </div>

              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.35rem' }}>اسم المستخدم</label>
                <input
                  type="text"
                  required
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  placeholder="turki_pos"
                  style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                />
              </div>

              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.35rem' }}>الدور الوظيفي</label>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as StaffMember['role'])}
                  style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                >
                  <option value="cashier">كاشير</option>
                  <option value="manager">مدير فرع</option>
                  <option value="stock_keeper">أمين مخزن</option>
                  <option value="accountant">محاسب</option>
                </select>
              </div>

              <div style={{ marginBottom: '1.5rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.35rem' }}>الفرع المخصص</label>
                <select
                  value={newBranch}
                  onChange={(e) => setNewBranch(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                >
                  <option value="الفرع الرئيسي">الفرع الرئيسي</option>
                  <option value="المستودع المركزي">المستودع المركزي</option>
                  <option value="الإدارة العامة">الإدارة العامة</option>
                </select>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  style={{ padding: '0.6rem 1rem', borderRadius: '6px', border: '1px solid #cbd5e1', background: 'white', cursor: 'pointer' }}
                >
                  إلغاء
                </button>
                <button
                  type="submit"
                  style={{ padding: '0.6rem 1.25rem', borderRadius: '6px', border: 'none', background: '#0284c7', color: 'white', fontWeight: 'bold', cursor: 'pointer' }}
                >
                  حفظ الموظف
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
