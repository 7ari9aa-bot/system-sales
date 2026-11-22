import { useEffect, useState, type FC } from 'react'

export interface CustomerCartItem {
  readonly id: string
  readonly name: string
  readonly quantity: number
  readonly priceSar: string
  readonly totalSar: string
}

export interface CustomerDisplayState {
  readonly items: readonly CustomerCartItem[]
  readonly subtotalSar: string
  readonly vatSar: string
  readonly totalSar: string
  readonly storeName: string
}

const DEFAULT_STATE: CustomerDisplayState = {
  items: [],
  subtotalSar: '0.00',
  vatSar: '0.00',
  totalSar: '0.00',
  storeName: 'فهرست للأعمال التجارية',
}

export const CustomerDisplayView: FC = () => {
  const [data, setData] = useState<CustomerDisplayState>(DEFAULT_STATE)
  const [currentTime, setCurrentTime] = useState(new Date())

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return

    const channel = new BroadcastChannel('fihrist-customer-display')
    channel.onmessage = (event: MessageEvent<CustomerDisplayState>) => {
      if (event.data && typeof event.data === 'object') {
        setData(event.data)
      }
    }

    // Ping channel in case cashier is already open
    channel.postMessage({ type: 'REQUEST_CURRENT_STATE' })

    return () => {
      channel.close()
    }
  }, [])

  const hasItems = data.items.length > 0

  return (
    <div
      dir="rtl"
      className="flex h-screen w-screen flex-col bg-slate-950 font-sans text-slate-100 select-none overflow-hidden"
    >
      {/* Top branding bar */}
      <header className="flex h-18 shrink-0 items-center justify-between border-b border-slate-800 bg-slate-900/90 px-8 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-600 font-bold text-white shadow-lg shadow-emerald-900/50">
            ف
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white">{data.storeName}</h1>
            <p className="text-xs text-slate-400">شاشة العميل — مرحباً بك</p>
          </div>
        </div>

        <div className="flex items-center gap-4 text-sm text-slate-400">
          <span className="rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-400 ring-1 ring-emerald-500/20">
            ● مباشر
          </span>
          <span>
            {currentTime.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        </div>
      </header>

      {/* Main split display */}
      <main className="flex flex-1 overflow-hidden p-6 gap-6">
        {/* Items Table (65% width) */}
        <section className="flex flex-1 flex-col rounded-2xl border border-slate-800 bg-slate-900/60 p-5 shadow-xl">
          <h2 className="mb-4 text-base font-semibold text-slate-300">قائمة الأصناف الممسوحة</h2>

          {hasItems ? (
            <div className="flex-1 overflow-y-auto pr-1">
              <table className="w-full text-right text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-xs font-medium text-slate-400">
                    <th className="pb-3 pr-2">الصنف</th>
                    <th className="pb-3 text-center">الكمية</th>
                    <th className="pb-3 text-center">سعر الوحدة</th>
                    <th className="pb-3 pl-2 text-left">الإجمالي</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {data.items.map((item) => (
                    <tr key={item.id} className="text-slate-200 animate-fadeIn">
                      <td className="py-3.5 pr-2 font-medium">{item.name}</td>
                      <td className="py-3.5 text-center text-slate-400 font-mono text-base">{item.quantity}</td>
                      <td className="py-3.5 text-center font-mono text-slate-300">{item.priceSar} ر.س</td>
                      <td className="py-3.5 pl-2 text-left font-mono font-bold text-white text-base">
                        {item.totalSar} ر.س
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center text-center">
              <div className="mb-4 flex h-20 w-20 items-center justify-center rounded-2xl bg-slate-800/50 text-4xl">
                🛒
              </div>
              <p className="text-lg font-medium text-slate-300">مرحباً بكم في متجرنا</p>
              <p className="text-sm text-slate-500 mt-1">يتم عرض المشتريات هنا مباشرة أثناء المسح</p>
            </div>
          )}
        </section>

        {/* Totals & Payment QR column (35% width) */}
        <aside className="flex w-96 flex-col justify-between rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl">
          {/* Totals breakdown */}
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-slate-300">ملخص الحساب</h2>

            <div className="space-y-2.5 rounded-xl bg-slate-950/60 p-4 border border-slate-800/80">
              <div className="flex justify-between text-sm text-slate-400">
                <span>المجموع الفرعي:</span>
                <span className="font-mono text-slate-200">{data.subtotalSar} ر.س</span>
              </div>
              <div className="flex justify-between text-sm text-slate-400">
                <span>ضريبة القيمة المضافة (15%):</span>
                <span className="font-mono text-slate-200">{data.vatSar} ر.س</span>
              </div>
              <div className="my-2 border-t border-slate-800" />
              <div className="flex items-baseline justify-between">
                <span className="text-base font-semibold text-white">المبلغ المطلوب:</span>
                <div className="text-left">
                  <span className="text-3xl font-extrabold font-mono text-emerald-400 tracking-tight">
                    {data.totalSar}
                  </span>
                  <span className="mr-1 text-sm text-emerald-500 font-medium">ر.س</span>
                </div>
              </div>
            </div>

            {/* ZATCA QR / Digital Pay card */}
            <div className="flex flex-col items-center rounded-xl bg-slate-950/40 p-4 border border-slate-800/60 text-center">
              <div className="mb-2 flex h-28 w-28 items-center justify-center rounded-lg bg-white p-2 shadow-inner">
                {/* SVG QR Code Simulation */}
                <svg viewBox="0 0 100 100" className="h-full w-full fill-slate-950">
                  <rect x="10" y="10" width="24" height="24" rx="2" />
                  <rect x="66" y="10" width="24" height="24" rx="2" />
                  <rect x="10" y="66" width="24" height="24" rx="2" />
                  <rect x="16" y="16" width="12" height="12" fill="white" />
                  <rect x="72" y="16" width="12" height="12" fill="white" />
                  <rect x="16" y="72" width="12" height="12" fill="white" />
                  <rect x="20" y="20" width="4" height="4" />
                  <rect x="76" y="20" width="4" height="4" />
                  <rect x="20" y="76" width="4" height="4" />
                  <circle cx="50" cy="50" r="6" />
                  <rect x="44" y="20" width="12" height="6" />
                  <rect x="44" y="74" width="12" height="6" />
                  <rect x="74" y="44" width="6" height="12" />
                  <rect x="20" y="44" width="6" height="12" />
                </svg>
              </div>
              <p className="text-xs font-medium text-slate-300">الفاتورة الإلكترونية والمدفوعات</p>
              <p className="text-[11px] text-slate-500 mt-0.5">متوافق مع هيئة الزكاة والضريبة والجمارك (ZATCA)</p>
            </div>
          </div>

          {/* Footer note */}
          <div className="mt-4 text-center">
            <p className="text-xs text-slate-400">✨ سعداء بخدمتكم دائماً</p>
          </div>
        </aside>
      </main>
    </div>
  )
}
