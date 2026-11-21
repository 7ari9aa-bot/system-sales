import { useState, type FC } from 'react'
import type { Platform } from '@/platform'
import { DashboardView } from '@/features/dashboard/DashboardView'
import { CashierView } from '@/features/cashier/CashierView'
import { InventoryView } from '@/features/inventory/InventoryView'
import { InboxView } from '@/features/inbox/InboxView'
import { SettingsView } from '@/features/settings/SettingsView'

export type WorkstationTab = 'dashboard' | 'cashier' | 'inventory' | 'inbox' | 'settings'

export const AppShell: FC<{
  readonly platform: Platform
  readonly apiBaseUrl: string
  readonly onSaveUrl: (url: string) => void
}> = ({ platform, apiBaseUrl, onSaveUrl }) => {
  const [activeTab, setActiveTab] = useState<WorkstationTab>('cashier')

  return (
    <div className="workstation" dir="rtl">
      {/* Sidebar Navigation */}
      <aside className="workstation__sidebar">
        <div className="workstation__brand">
          <div className="workstation__brand-title">فهرس FIHRIST</div>
          <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>Desktop</span>
        </div>

        <nav className="workstation__nav">
          <button
            type="button"
            className={`workstation__nav-item ${activeTab === 'cashier' ? 'workstation__nav-item--active' : ''}`}
            onClick={() => setActiveTab('cashier')}
          >
            <span>🛒</span>
            <span>نقطة البيع (الكاشير)</span>
          </button>

          <button
            type="button"
            className={`workstation__nav-item ${activeTab === 'dashboard' ? 'workstation__nav-item--active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            <span>📊</span>
            <span>لوحة التحكم</span>
          </button>

          <button
            type="button"
            className={`workstation__nav-item ${activeTab === 'inventory' ? 'workstation__nav-item--active' : ''}`}
            onClick={() => setActiveTab('inventory')}
          >
            <span>📦</span>
            <span>إدارة المخزون</span>
          </button>

          <button
            type="button"
            className={`workstation__nav-item ${activeTab === 'inbox' ? 'workstation__nav-item--active' : ''}`}
            onClick={() => setActiveTab('inbox')}
          >
            <span>💬</span>
            <span>صندوق الوارد (Omnichannel)</span>
          </button>

          <div style={{ marginTop: 'auto', borderTop: '1px solid #282f3d', paddingTop: '0.5rem' }}>
            <button
              type="button"
              className={`workstation__nav-item ${activeTab === 'settings' ? 'workstation__nav-item--active' : ''}`}
              onClick={() => setActiveTab('settings')}
            >
              <span>⚙️</span>
              <span>الإعدادات والأجهزة</span>
            </button>
          </div>
        </nav>
      </aside>

      {/* Main Workspace Area */}
      <main className="workstation__main">
        {/* Topbar */}
        <header className="workstation__topbar">
          <div>
            <h1 className="workstation__topbar-title">
              {activeTab === 'cashier' && 'نقطة البيع والكاشير'}
              {activeTab === 'dashboard' && 'لوحة التحكم والمؤشرات'}
              {activeTab === 'inventory' && 'المخزون والجرد الدوري'}
              {activeTab === 'inbox' && 'صندوق الوارد وخدمة العملاء'}
              {activeTab === 'settings' && 'إعدادات المنظومة والمحطة'}
            </h1>
            <div style={{ fontSize: '0.75rem', color: 'var(--fh-ink-muted)' }}>
              المتجر: <strong>متجر فهرس التجريبي</strong> | الفرع: <strong>الفرع الرئيسي</strong> | الكاشير: <strong>أحمد سالم</strong>
            </div>
          </div>

          <div className="workstation__topbar-actions">
            <span className="workstation__badge workstation__badge--shift">
              الوردية: #42 مفتوحة
            </span>
            <span className="workstation__badge workstation__badge--online">
              ● متصل: {apiBaseUrl}
            </span>
          </div>
        </header>

        {/* Feature View */}
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {activeTab === 'cashier' && <CashierView platform={platform} />}
          {activeTab === 'dashboard' && <DashboardView />}
          {activeTab === 'inventory' && <InventoryView />}
          {activeTab === 'inbox' && <InboxView />}
          {activeTab === 'settings' && (
            <SettingsView
              platform={platform}
              currentApiUrl={apiBaseUrl}
              onSaveUrl={onSaveUrl}
            />
          )}
        </div>
      </main>
    </div>
  )
}
