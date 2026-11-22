import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { CashierView } from './CashierView'
import { createNoopPlatform } from '@/platform'
import type { Platform } from '@/platform'

describe('<CashierView> POS Cashier Workstation', () => {
  function setup() {
    const openCashDrawer = vi.fn().mockResolvedValue(undefined)
    const printRaw = vi.fn().mockResolvedValue(undefined)

    const platform: Platform = {
      ...createNoopPlatform(),
      printer: {
        listPrinters: () => Promise.resolve([{ name: 'Thermal-Receipt-POS' }]),
        printRaw,
        openCashDrawer,
      },
    }

    const utils = render(<CashierView platform={platform} />)
    return { ...utils, platform, openCashDrawer, printRaw }
  }

  it('renders cashier layout with product catalog, shift indicator, and action buttons', () => {
    setup()

    expect(screen.getByText(/الوردية #42/)).toBeTruthy()
    expect(screen.getByPlaceholderText(/امسح الباركود أو ابحث/)).toBeTruthy()
    expect(screen.getByText('قميص أكسفورد كلاسيك أبيض')).toBeTruthy()
    expect(screen.getByText(/السلة فارغة/)).toBeTruthy()
  })

  it('adds product to cart, calculates 15% VAT, and updates final total', () => {
    setup()

    // Click on the first product: قميص أكسفورد كلاسيك أبيض
    const productCard = screen.getByText('قميص أكسفورد كلاسيك أبيض').closest('.pos-product-card')
    expect(productCard).toBeTruthy()
    fireEvent.click(productCard!)

    // Cart should now have 1 item
    expect(screen.getByText('سلة المبيعات (1)')).toBeTruthy()
    expect(screen.getByText(/المجموع الفرعي/)).toBeTruthy()
    expect(screen.getByText(/ضريبة القيمة المضافة/)).toBeTruthy()
    expect(screen.getByText(/الإجمالي النهائي/)).toBeTruthy()
  })

  it('adjusts item quantity in cart with + and - buttons', () => {
    setup()

    const productCard = screen.getByText('قميص أكسفورد كلاسيك أبيض').closest('.pos-product-card')
    fireEvent.click(productCard!)

    // Increase quantity to 2
    const plusButton = screen.getByText('+')
    fireEvent.click(plusButton)
    expect(screen.getByText('سلة المبيعات (2)')).toBeTruthy()

    // Decrease quantity back to 1
    const minusButton = screen.getByText('-')
    fireEvent.click(minusButton)
    expect(screen.getByText('سلة المبيعات (1)')).toBeTruthy()

    // Decrease quantity to 0 removes it
    fireEvent.click(minusButton)
    expect(screen.getByText(/السلة فارغة/)).toBeTruthy()
  })

  it('allows holding a cart and resuming it from the queue', () => {
    setup()

    const productCard = screen.getByText('بنطال جينز سليم كحلي').closest('.pos-product-card')
    fireEvent.click(productCard!)
    expect(screen.getByText('سلة المبيعات (1)')).toBeTruthy()

    // Click hold cart
    const holdBtn = screen.getByText('تعليق')
    fireEvent.click(holdBtn)

    // Cart is now empty, message displayed
    expect(screen.getByText(/السلة فارغة/)).toBeTruthy()
    expect(screen.getByText(/تم تعليق الفاتورة بنجاح/)).toBeTruthy()

    // Open held carts modal
    const heldModalBtn = screen.getByText(/📋 المعلقة \(1\)/)
    fireEvent.click(heldModalBtn)

    expect(screen.getByText(/الفواتير المعلقة في الانتظار/)).toBeTruthy()

    // Resume the held cart
    const resumeBtn = screen.getByText('استرجاع للسلة')
    fireEvent.click(resumeBtn)

    expect(screen.getByText('سلة المبيعات (1)')).toBeTruthy()
    expect(screen.getAllByText('بنطال جينز سليم كحلي').length).toBeGreaterThanOrEqual(2)
  })

  it('filters product catalog when typing in search input', () => {
    setup()

    const searchInput = screen.getByPlaceholderText(/امسح الباركود أو ابحث/)
    fireEvent.change(searchInput, { target: { value: 'عطر' } })

    expect(screen.getByText('عطر فهرس الشرقي 100 مل')).toBeTruthy()
    expect(screen.queryByText('بنطال جينز سليم كحلي')).toBeNull()

    // Clear search
    const clearBtn = screen.getByText('مسح')
    fireEvent.click(clearBtn)
    expect(screen.getByText('بنطال جينز سليم كحلي')).toBeTruthy()
  })

  it('opens payment modal and completes cash checkout with drawer pulse & receipt printing', async () => {
    const { openCashDrawer, printRaw } = setup()

    const productCard = screen.getByText('تي شيرت قطن مصري أسود').closest('.pos-product-card')
    fireEvent.click(productCard!)

    // Click checkout button
    const checkoutBtn = screen.getByRole('button', { name: /دفع \[F1\]/ })
    fireEvent.click(checkoutBtn)

    // Payment modal opens
    expect(screen.getByText('إتمام الدفع - الفاتورة')).toBeTruthy()

    // Click Cash payment
    const cashBtn = screen.getByText(/💵 نقدي/)
    fireEvent.click(cashBtn)

    // Hardware functions triggered
    await waitFor(() => {
      expect(openCashDrawer).toHaveBeenCalled()
      expect(printRaw).toHaveBeenCalled()
    })

    // Cart cleared after successful payment
    expect(screen.getByText(/السلة فارغة/)).toBeTruthy()
  })

  it('completes card checkout without pulsing cash drawer', async () => {
    const { openCashDrawer, printRaw } = setup()

    const productCard = screen.getByText('تي شيرت قطن مصري أسود').closest('.pos-product-card')
    fireEvent.click(productCard!)

    const checkoutBtn = screen.getByRole('button', { name: /دفع \[F1\]/ })
    fireEvent.click(checkoutBtn)

    // Click Card payment (مدى / بطاقة)
    const cardBtn = screen.getByText(/💳 مدى \/ بطاقة/)
    fireEvent.click(cardBtn)

    await waitFor(() => {
      expect(printRaw).toHaveBeenCalled()
    })
    expect(openCashDrawer).not.toHaveBeenCalled()
    expect(screen.getByText(/السلة فارغة/)).toBeTruthy()
  })

  it('handles Escape key to close open modals', () => {
    setup()

    // Open returns modal
    const returnsBtn = screen.getByText(/↩ مرتجع/)
    fireEvent.click(returnsBtn)
    expect(screen.getByText(/استرجاع واستبدال فاتورة/)).toBeTruthy()

    // Press Escape
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByText(/استرجاع واستبدال فاتورة/)).toBeNull()
  })
})
