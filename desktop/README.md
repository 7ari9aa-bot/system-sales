# Fihrist Desktop Workstation

A high-performance Tauri 2 native desktop application with a React 19 + TypeScript interface,
delivering the full conversational-commerce Sales OS directly to store PCs, cashier terminals,
and back-office workstations.

## Architecture Overview

Fihrist Desktop runs as a standalone native workstation SPA embedded within the Tauri shell:

- **Native React Workstation:** The UI is compiled into the desktop bundle (`index.html`) and loaded directly via `WebviewUrl::App`.
- **Integrated POS & Scanner Bridge:** Built-in hardware keyboard-wedge scanner bridge (`scan_bridge.js`) injected at startup. Listens globally for USB and wireless barcode scanner bursts (`event.code` based, completely layout-immune and safe for Arabic keyboards) and dispatches DOM `fihrist:scan` events.
- **Hardware Integration:** Native Rust commands for thermal receipt printing (ESC/POS raw bytes), cash drawer kick pulse (`open_cash_drawer`), and secondary customer-facing display window (`open_customer_display`).
- **Secure Session Management:** Hardware-level session storage via Tauri platform commands (`read_auth_session`, `write_auth_session`, `clear_auth_session`) stored in `<app-config-dir>/fihrist-session.json`.
- **Full Module Suite:**
  - 🛒 **نقطة البيع (Cashier POS):** Live catalog search, hardware barcode scanning, VAT-inclusive 15% tax calculation, held carts queue, payment methods (Cash, Mada/Card, Apple Pay, Split), and shift Z-reports.
  - 📊 **لوحة التحكم (Dashboard):** Real-time daily KPIs, average basket, stock alerts, and shift metrics.
  - 📦 **المخزون (Inventory):** SKU/Barcode catalog, stock level tracking, low-stock warnings, and stocktake reconciliation.
  - 🚚 **المشتريات (Purchasing):** Supplier management, purchase orders, and shipment receiving.
  - 📈 **التقارير (Reports):** Financial summaries, sales by payment method, and margins.
  - 👥 **الموظفون (Team):** Team directory, roles, and granular permission enforcement.
  - 💬 **صندوق الوارد (Omnichannel Inbox):** Unified customer conversations across WhatsApp, Messenger, and web chat.
  - ⚙️ **الإعدادات (Settings):** Workstation configuration, printer selection, cash drawer test, and server settings.

## Platform Boundary Rule

The React tree never directly calls `invoke()`, `fetch()`, opens an `EventSource`, or touches web storage (`localStorage` / `sessionStorage`).
Instead, all components interact exclusively through the abstract `Platform` interface (`src/platform/port.ts`):
- Production uses the Tauri adapter (`src/platform/tauri/`).
- Browser dev mode (`npm run dev`) and Vitest unit tests use the in-memory platform (`src/platform/noop.ts`).

This architectural boundary is strictly verified by `config/check-platform-boundary.mjs` and enforced by CI.

## Verification & Commands

```bash
cd desktop
npm ci
npm run dev        # Vite dev server on http://127.0.0.1:5183
npm run verify     # Full verification suite: boundary, typecheck, lint, vitest, build, host check
npm run tauri dev  # Launch native Tauri desktop application
```
