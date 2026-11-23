import { useState, type FC } from 'react'
import type { AuthSession, Platform } from '@/platform'
import { DashboardView } from '@/features/dashboard/DashboardView'
import { CashierView } from '@/features/cashier/CashierView'
import { InventoryView } from '@/features/inventory/InventoryView'
import { PurchasingView } from '@/features/purchasing/PurchasingView'
import { ReportsView } from '@/features/reports/ReportsView'
import { TeamView } from '@/features/team/TeamView'
import { InboxView } from '@/features/inbox/InboxView'
import { SettingsView } from '@/features/settings/SettingsView'

export type WorkstationTab = 'dashboard' | 'cashier' | 'inventory' | 'purchasing' | 'reports' | 'team' | 'inbox' | 'settings'

export const AppShell: FC<{
  readonly platform: Platform
  readonly session?: AuthSession | null
  readonly onLogout?: () => void
  readonly apiBaseUrl: string
  readonly onSaveUrl: (url: string) => void
}> = ({ platform, session, onLogout, apiBaseUrl, onSaveUrl }) => {
  const [activeTab, setActiveTab] = useState<WorkstationTab>('cashier')

  const permissions = session?.user?.permissions ?? ['*']
  const isOwnerOrAdmin = session?.user?.role === 'owner' || session?.user?.role === 'admin'
  const hasPerm = (perm: string): boolean => isOwnerOrAdmin || permissions.includes('*') || permissions.includes(perm)

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

          {hasPerm('dashboard:read') && (
            <button
              type="button"
              className={`workstation__nav-item ${activeTab === 'dashboard' ? 'workstation__nav-item--active' : ''}`}
              onClick={() => setActiveTab('dashboard')}
            >
              <span>📊</span>
              <span>لوحة التحكم</span>
            </button>
          )}

          {hasPerm('inventory:read') && (
            <button
              type="button"
              className={`workstation__nav-item ${activeTab === 'inventory' ? 'workstation__nav-item--active' : ''}`}
              onClick={() => setActiveTab('inventory')}
            >
              <span>📦</span>
              <span>إدارة المخزون</span>
            </button>
          )}

          {hasPerm('purchasing:read') && (
            <button
              type="button"
              className={`workstation__nav-item ${activeTab === 'purchasing' ? 'workstation__nav-item--active' : ''}`}
              onClick={() => setActiveTab('purchasing')}
            >
              <span>🚚</span>
              <span>المشتريات والموردون</span>
            </button>
          )}

          {hasPerm('reports:read') && (
            <button
              type="button"
              className={`workstation__nav-item ${activeTab === 'reports' ? 'workstation__nav-item--active' : ''}`}
              onClick={() => setActiveTab('reports')}
            >
              <span>📈</span>
              <span>التقارير والتحليلات</span>
            </button>
          )}

          {hasPerm('team:manage') && (
            <button
              type="button"
              className={`workstation__nav-item ${activeTab === 'team' ? 'workstation__nav-item--active' : ''}`}
              onClick={() => setActiveTab('team')}
            >
              <span>👥</span>
              <span>الموظفون والصلاحيات</span>
            </button>
          )}

          {hasPerm('inbox:read') && (
            <button
              type="button"
              className={`workstation__nav-item ${activeTab === 'inbox' ? 'workstation__nav-item--active' : ''}`}
              onClick={() => setActiveTab('inbox')}
            >
              <span>💬</span>
              <span>صندوق الوارد (Omnichannel)</span>
            </button>
          )}

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
              {activeTab === 'purchasing' && 'المشتريات وإدارة الموردين'}
              {activeTab === 'reports' && 'التقارير المالية والتحليلات'}
              {activeTab === 'team' && 'إدارة الموظفين وفريق العمل'}
              {activeTab === 'inbox' && 'صندوق الوارد وخدمة العملاء'}
              {activeTab === 'settings' && 'إعدادات المنظومة والمحطة'}
            </h1>
            <div style={{ fontSize: '0.75rem', color: 'var(--fh-ink-muted)' }}>
              المتجر: <strong>{session?.tenant?.name ?? 'متجر فهرس التجريبي'}</strong> | الفرع: <strong>{session?.branch?.name ?? 'الفرع الرئيسي'}</strong> | الكاشير: <strong>{session?.user?.name ?? 'أحمد سالم'}</strong>
            </div>
          </div>

          <div className="workstation__topbar-actions">
            <span className="workstation__badge workstation__badge--shift">
              الوردية: #42 مفتوحة
            </span>
            <span className="workstation__badge workstation__badge--online">
              ● متصل: {apiBaseUrl}
            </span>
            {onLogout && (
              <button
                type="button"
                onClick={onLogout}
                className="boot__button"
                style={{
                  background: '#dc2626',
                  fontSize: '0.75rem',
                  padding: '0.35rem 0.65rem',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  border: 'none',
                }}
                title="تسجيل الخروج من المحطة"
              >
                تسجيل الخروج
              </button>
            )}
          </div>
        </header>

        {/* Feature View */}
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {activeTab === 'cashier' && <CashierView platform={platform} />}
          {activeTab === 'dashboard' && <DashboardView />}
          {activeTab === 'inventory' && <InventoryView platform={platform} />}
          {activeTab === 'purchasing' && <PurchasingView />}
          {activeTab === 'reports' && <ReportsView />}
          {activeTab === 'team' && <TeamView />}
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
