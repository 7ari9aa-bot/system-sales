import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { InventoryView } from './InventoryView'
import { createNoopPlatform } from '@/platform'
import type { Platform } from '@/platform'

/**
 * الشاشة كانت على مصفوفة تجريبية ثابتة وبتعدّل الرصيد محليًا، وأزرار الإضافة والاستيراد
 * مابتنفّذش حاجة. الاختبارات دي بتثبت إن القراءة والكتابة بيمرّوا على الباك إند الحقيقي.
 */

const STOCK_ROWS = [
  {
    variant_id: 'v-1',
    product_title: 'تيشيرت قطن أسود',
    sku: 'TEE-BLK-M',
    barcode: '6221234567890',
    category: 'ملابس',
    price: '450.00',
    on_hand: 12,
    reorder_level: 5,
    avg_cost: '120.00',
  },
  {
    variant_id: 'v-2',
    product_title: 'بنطلون جينز كحلي',
    sku: 'JEAN-NVY-L',
    barcode: '6221234567891',
    category: 'ملابس',
    price: '700.00',
    on_hand: 2,
    reorder_level: 4,
    avg_cost: null,
  },
]

function setup(overrides: Record<string, unknown> = {}) {
  const calls: Array<{ endpoint: string; method: string; body?: unknown }> = []
  const request = vi.fn((endpoint: string, options?: { method?: string; body?: unknown }) => {
    calls.push({ endpoint, method: options?.method ?? 'GET', body: options?.body })
    const reply =
      endpoint === 'warehouses'
        ? [{ id: 'w-branch', name: 'فرع مدينة نصر', is_active: true }]
        : endpoint.startsWith('pos/stock')
          ? STOCK_ROWS
          : endpoint === 'inventory/movements'
            ? { id: 'mv-1' }
            : endpoint === 'products/intake'
              ? { id: 'p-new', variants: [{ id: 'v-new' }] }
              : (overrides[endpoint] ?? { ok: true })
    return Promise.resolve(reply)
  })

  const platform: Platform = {
    ...createNoopPlatform(),
    http: { request: request as Platform['http']['request'] },
  }

  const utils = render(<InventoryView platform={platform} />)
  return { ...utils, platform, calls, request }
}

describe('<InventoryView> reads the shop, not a fixture', () => {
  it('shows the rows the API returned with their real balances', async () => {
    setup()
    await waitFor(() => expect(screen.getByText('تيشيرت قطن أسود')).toBeTruthy())
    expect(screen.getByText('12')).toBeTruthy()
    expect(screen.getByText('2')).toBeTruthy()
    // منتج من المصفوفة التجريبية القديمة (قميص أكسفورد) مايظهرش خلاص.
    expect(screen.queryByText('قميص أكسفورد كلاسيك أبيض')).toBeNull()
  })

  it('says a row has no cost instead of pretending it costs zero', async () => {
    setup()
    await waitFor(() => expect(screen.getByText('بنطلون جينز كحلي')).toBeTruthy())
    expect(screen.getByText('بلا تكلفة')).toBeTruthy()
    expect(screen.getByText(/1 صنف بلا تكلفة/)).toBeTruthy()
  })

  it('searches on the server instead of filtering a local array', async () => {
    const { request } = setup()
    await waitFor(() => expect(screen.getByText('تيشيرت قطن أسود')).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText(/بحث في المخزون/), { target: { value: 'جينز' } })
    await waitFor(() => expect(request.mock.calls.some(([endpoint]) => String(endpoint).includes('pos/stock?term='))).toBe(true))
  })
})

describe('<InventoryView> writes real stock movements', () => {
  it('posts the adjustment to inventory/movements on the chosen warehouse', async () => {
    const { calls } = setup()
    await waitFor(() => expect(screen.getByText('تيشيرت قطن أسود')).toBeTruthy())

    fireEvent.click(screen.getAllByText('تسوية رصيد')[0]!)
    // الحركة الافتراضية «إدخال بضاعة»؛ الجرد بيختار الرصيد المطلق.
    fireEvent.change(screen.getByDisplayValue('إدخال بضاعة'), { target: { value: 'adjust' } })
    const qty = screen.getByDisplayValue('0')
    fireEvent.change(qty, { target: { value: '20' } })
    fireEvent.click(screen.getByText('حفظ الحركة'))

    await waitFor(() => expect(calls.some((c) => c.endpoint === 'inventory/movements')).toBe(true))
    const movement = calls.find((c) => c.endpoint === 'inventory/movements')!
    expect(movement.method).toBe('POST')
    expect(movement.body).toMatchObject({ variant_id: 'v-1', warehouse_id: 'w-branch', direction: 'adjust', quantity: 20 })
  })

  it('refuses a zero quantity instead of sending a movement the server rejects', async () => {
    const { calls } = setup()
    await waitFor(() => expect(screen.getByText('تيشيرت قطن أسود')).toBeTruthy())

    fireEvent.click(screen.getAllByText('تسوية رصيد')[0]!)
    fireEvent.click(screen.getByText('حفظ الحركة'))

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('الكمية'))
    expect(calls.some((c) => c.endpoint === 'inventory/movements')).toBe(false)
  })
})

describe('<InventoryView> adds and imports through products/intake', () => {
  it('creates a product with its opening balance and cost', async () => {
    const { calls } = setup()
    await waitFor(() => expect(screen.getByText('تيشيرت قطن أسود')).toBeTruthy())

    fireEvent.click(screen.getByTestId('add-product'))
    fireEvent.change(screen.getByPlaceholderText('مثال: تيشيرت قطن أسود'), { target: { value: 'هودي رمادي' } })
    fireEvent.change(screen.getByPlaceholderText('450'), { target: { value: '600' } })
    fireEvent.change(screen.getByPlaceholderText('TEE-BLK-M'), { target: { value: 'HOOD-GRY-L' } })
    fireEvent.change(screen.getByPlaceholderText('120'), { target: { value: '210' } })
    fireEvent.change(screen.getByPlaceholderText('0'), { target: { value: '7' } })
    fireEvent.click(screen.getByText('حفظ المنتج'))

    await waitFor(() => expect(calls.some((c) => c.endpoint === 'products/intake')).toBe(true))
    const intake = calls.find((c) => c.endpoint === 'products/intake')!
    expect(intake.body).toMatchObject({ title: 'هودي رمادي', status: 'active', warehouse_id: 'w-branch' })
    expect((intake.body as { variants: Array<Record<string, unknown>> }).variants[0]).toMatchObject({
      sku: 'HOOD-GRY-L',
      price: '600.00',
      stock: 7,
      unit_cost: '210.00',
    })
  })

  it('imports a CSV by saving each row through the same intake path', async () => {
    const { calls } = setup()
    await waitFor(() => expect(screen.getByText('تيشيرت قطن أسود')).toBeTruthy())

    const csv = 'المنتج,السعر,SKU,الرصيد,التكلفة\nكاب أسود,150,CAP-BLK,5,60\nوشاح صوف,220,SCARF-1,3,90'
    const file = new File([csv], 'products.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByTestId('import-input'), { target: { files: [file] } })

    await waitFor(() => expect(calls.filter((c) => c.endpoint === 'products/intake')).toHaveLength(2))
    const skus = calls
      .filter((c) => c.endpoint === 'products/intake')
      .map((c) => (c.body as { variants: Array<{ sku: string }> }).variants[0]!.sku)
    expect(skus).toEqual(['CAP-BLK', 'SCARF-1'])
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('2 منتج اتحفظ'))
  })
})
