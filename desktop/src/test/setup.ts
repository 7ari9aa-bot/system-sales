import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// @testing-library/react only auto-registers cleanup when it finds a global
// afterEach. Vitest runs without globals here, so cleanup is explicit.
afterEach(() => {
  cleanup()
})
