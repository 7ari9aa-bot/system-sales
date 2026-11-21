import { useEffect, useState, type FC } from 'react'
import type { Platform, PrinterDevice } from '@/platform'

export const SettingsView: FC<{
  readonly platform: Platform
  readonly currentApiUrl: string | null
  readonly onSaveUrl: (url: string) => void
}> = ({ platform, currentApiUrl, onSaveUrl }) => {
  const [printers, setPrinters] = useState<PrinterDevice[]>([])
  const [selectedPrinter, setSelectedPrinter] = useState<string>('')
  const [serverUrl, setServerUrl] = useState(currentApiUrl ?? '')
  const [hardwareStatus, setHardwareStatus] = useState<string | null>(null)

  useEffect(() => {
    void platform.printer.listPrinters().then((list) => {
      setPrinters(list)
      if (list.length > 0 && !selectedPrinter) {
        setSelectedPrinter(list[0]?.name ?? '')
      }
    })
  }, [platform, selectedPrinter])

  const handleTestDrawer = async (): Promise<void> => {
    try {
      await platform.printer.openCashDrawer(selectedPrinter || undefined)
      setHardwareStatus('تم إرسال نبضة فتح درج النقدية بنجاح.')
    } catch (e: unknown) {
      setHardwareStatus(`تعذر فتح درج النقدية: ${String(e)}`)
    }
  }

  const handleTestPrint = async (): Promise<void> => {
    try {
      const testText = `\x1B\x40\x1B\x61\x01FIHRIST PRINTER TEST\n` +
        `--------------------------------\n` +
        `Printer: ${selectedPrinter || 'Default'}\n` +
        `Workstation: Windows PC POS\n` +
        `Hardware connection: OK\n` +
        `--------------------------------\n\x1D\x56\x00`
      const encoder = new TextEncoder()
      await platform.printer.printRaw(encoder.encode(testText))
      setHardwareStatus('تم إرسال أمر طباعة الإيصال التجريبي بنجاح.')
    } catch (e: unknown) {
      setHardwareStatus(`تعذر إرسال أمر الطباعة: ${String(e)}`)
    }
  }

  return (
    <div className="workstation__content" style={{ maxWidth: '720px' }}>
      <h2 style={{ margin: '0 0 1rem 0', fontSize: '1.25rem' }}>إعدادات المنظومة ومحطة العمل</h2>

      {hardwareStatus && (
        <div style={{ padding: '0.75rem 1rem', background: '#dcfce7', color: '#166534', borderRadius: 'var(--fh-radius)', fontWeight: 600 }}>
          {hardwareStatus}
        </div>
      )}

      {/* Hardware Section */}
      <div style={{ border: '1px solid var(--fh-line)', borderRadius: 'var(--fh-radius)', padding: '1.25rem', background: 'var(--fh-surface)', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <h3 style={{ margin: 0, fontSize: '1.05rem', color: 'var(--fh-accent)' }}>🖨️ إدارة الطابعات الحرارية ودرج النقدية</h3>

        <div>
          <label style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.35rem' }}>طابعة الفواتير الافتراضية (58mm / 80mm ESC/POS)</label>
          <select
            className="pos-search-input"
            style={{ width: '100%' }}
            value={selectedPrinter}
            onChange={(e) => setSelectedPrinter(e.target.value)}
          >
            {printers.length === 0 ? (
              <option value="">(طابعة النظام الافتراضية)</option>
            ) : (
              printers.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))
            )}
          </select>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <button type="button" className="boot__button" onClick={() => void handleTestPrint()}>
            طباعة إيصال فحص تجريبي
          </button>
          <button type="button" className="boot__button" style={{ background: '#0284c7' }} onClick={() => void handleTestDrawer()}>
            فتح درج النقدية الكهروميكانيكي
          </button>
        </div>
      </div>

      {/* Server URL Section */}
      <div style={{ border: '1px solid var(--fh-line)', borderRadius: 'var(--fh-radius)', padding: '1.25rem', background: 'var(--fh-surface)', display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '1rem' }}>
        <h3 style={{ margin: 0, fontSize: '1.05rem', color: 'var(--fh-accent)' }}>🌐 ربط خادم المنصة (Backend API)</h3>

        <div>
          <label style={{ display: 'block', fontSize: '0.9rem', marginBottom: '0.35rem' }}>عنوان الخادم الموحد</label>
          <input
            type="text"
            className="pos-search-input"
            style={{ width: '100%' }}
            value={serverUrl}
            onChange={(e) => setServerUrl(e.target.value)}
            placeholder="api.yourstore.com/api/v1"
          />
        </div>

        <button
          type="button"
          className="boot__button"
          onClick={() => onSaveUrl(serverUrl)}
        >
          حفظ إعدادات الخادم
        </button>
      </div>
    </div>
  )
}
