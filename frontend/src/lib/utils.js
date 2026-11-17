import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs))
} 


// Guarded so the module can be imported outside a browser (unit tests, SSR).
export const isIframe = typeof window !== "undefined" && window.self !== window.top;
