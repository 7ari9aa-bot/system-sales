/**
 * The UI never calls the transport directly and never reaches for the bridge;
 * both live behind the platform adapters. This comment is the scanner's own test
 * case: a doc line that names a banned call must not be reported as a violation.
 */
export const NOTES = 'web storage is unavailable in this layer'
