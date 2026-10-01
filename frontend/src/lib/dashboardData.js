// Display-only dashboard controls and formatting helpers.
// Business metrics and records must come from the authenticated API.
export const DATE_RANGES = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "7d", label: "Last 7 days" },
  { id: "30d", label: "Last 30 days" },
  { id: "90d", label: "Last 90 days" },
];

export const DEFAULT_RANGE = "30d";

export { formatCurrency } from "@/lib/regional";
