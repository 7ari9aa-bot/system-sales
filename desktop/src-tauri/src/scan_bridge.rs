//! The injected barcode-scan bridge.
//!
//! The webview loads a REMOTE page (wrap mode), so the bridge must arrive from
//! the shell, not from the web app: a plain-DOM `initialization_script` that
//! decodes keyboard-wedge scanner bursts and dispatches a DOM CustomEvent.
//! It exposes no Tauri IPC to the remote page and needs no capability change —
//! see the file header of the embedded source for the full reasoning.

/// The bridge source, shared with the desktop's own vitest suite. One file, two
/// consumers: `src/platform/scanner/scan_bridge.js` is both the bytes shipped
/// here and the bytes the tests execute, so tested behavior IS shipped
/// behavior.
pub const SCAN_BRIDGE_JS: &str = include_str!("../../src/platform/scanner/scan_bridge.js");

#[cfg(test)]
mod tests {
    use super::SCAN_BRIDGE_JS;

    #[test]
    fn the_embedded_bridge_is_present_and_nontrivial() {
        assert!(SCAN_BRIDGE_JS.contains("fihrist:scan"));
        assert!(SCAN_BRIDGE_JS.contains("__FIHRIST_SCAN_BRIDGE_INSTALLED"));
        // The source must stay plain JavaScript — a TS-only syntax marker here
        // would mean a type annotation leaked into a classic script.
        assert!(
            !SCAN_BRIDGE_JS.contains(": string"),
            "TS leaked into the injected script"
        );
    }
}
