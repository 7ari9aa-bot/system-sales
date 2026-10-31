/*
 * The barcode-scan bridge — one file, two consumers.
 *
 * The Tauri shell injects this file verbatim into every webview page
 * (`include_str!` in src-tauri/src/scan_bridge.rs), so it must be PLAIN
 * JavaScript: no ESM syntax, no TS types, nothing a classic <script> cannot
 * parse. The same file is exercised by vitest (desktop/src/platform/scanner/
 * scan_bridge.test.js) by evaluating it in a sandbox and driving the exported
 * pure pieces — one source of truth, so an edit here can never drift from the
 * shipped behavior.
 *
 * Why a global listener: the cashier must be able to scan while focus sits in
 * the customer field, a search box, or nowhere at all. Why `event.code` and
 * never `event.key`: scanners report physical keys, and decoding through a
 * keyboard LAYOUT would turn an Arabic layout into garbage — `KeyD` + `Digit2`
 * decodes to `d2` on every layout on earth.
 *
 * Why nothing here touches Tauri APIs: the shell loads a REMOTE page. This
 * bridge only decodes keystrokes and dispatches a DOM CustomEvent
 * (`fihrist:scan`), so the remote app gets zero IPC surface and the shell
 * needs zero capability changes (verified: withGlobalTauri=false,
 * capabilities grant core:default only).
 *
 * Detection model: USB HID scanners ("keyboard wedge") type the code as a
 * burst of fast keystrokes terminated by Enter. A human types 100–200 ms per
 * key; a scanner fires each key in well under 60 ms and always ends with
 * Enter. A code is ACCEPTED only when the burst was fast, long enough, and
 * within the barcode charset — a human cannot accidentally type six-plus
 * barcode characters at scanner speed, so false positives are effectively
 * impossible.
 */
(function () {
  'use strict';

  var SCAN_EVENT_NAME = 'fihrist:scan';

  /* Punctuation some symbologies carry (Code-128 alphanumerics, SKU dashes).
   * Everything else a keyboard can produce (Shift, Backspace, F-keys, letters
   * via IME…) decodes to null and RESETS the buffer: one non-barcode key is
   * proof of a human hand, not a scanner. */
  var PUNCTUATION = { Minus: '-', Period: '.', Comma: ',', Slash: '/' };

  var CHARSET = /^[0-9A-Za-z./-]+$/;

  function decodeEventCode(event) {
    var code = event && typeof event.code === 'string' ? event.code : '';
    // "KeyD" → "d". Length guard keeps "KeyDown"-style oddities out.
    if (code.length === 4 && code.indexOf('Key') === 0) {
      return code.charAt(3).toLowerCase();
    }
    // "Digit5" → "5".
    if (code.length === 6 && code.indexOf('Digit') === 0) {
      return code.charAt(5);
    }
    // "Numpad5" → "5" (scanner numpad entry); NumpadEnter/Add/… fall through.
    if (code.length === 7 && code.indexOf('Numpad') === 0) {
      var digit = code.charAt(6);
      if (digit >= '0' && digit <= '9') {
        return digit;
      }
      return null;
    }
    return Object.prototype.hasOwnProperty.call(PUNCTUATION, code)
      ? PUNCTUATION[code]
      : null;
  }

  function isEditableTarget(event) {
    var t = event && event.target ? event.target : null;
    if (!t) {
      return false;
    }
    var tag = t.tagName ? String(t.tagName).toUpperCase() : '';
    return tag === 'INPUT' || tag === 'TEXTAREA' || t.isContentEditable === true;
  }

  /* Accumulates one scan burst. State machine:
   *   gap too long | non-barcode key  → reset (human)
   *   Enter                           → finalize (accept if long + charset)
   *   anything else                   → append
   * `now` comes from event.timeStamp (ms, monotonic per page load). */
  function ScannerBuffer(options) {
    var opts = options || {};
    /* 80 ms, not 60: Bluetooth HID scanners and slow USB poll intervals can
     * breathe between keys; a human typing barcode-like text still exceeds
     * this on every keystroke. Tune against a real device before changing. */
    this.maxGapMs = typeof opts.maxGapMs === 'number' ? opts.maxGapMs : 80;
    this.minLength = typeof opts.minLength === 'number' ? opts.minLength : 6;
    this.maxLength = typeof opts.maxLength === 'number' ? opts.maxLength : 64;
    this.chars = [];
    this.firstAt = null;
    this.lastAt = null;
  }

  ScannerBuffer.prototype.reset = function () {
    this.chars = [];
    this.firstAt = null;
    this.lastAt = null;
  };

  /* Returns { accepted: false } while accumulating, or
   * { accepted: true, value, durationMs } / { accepted: false, rejected: reason }
   * when Enter finalizes the burst. */
  ScannerBuffer.prototype.push = function (event) {
    var code = event && typeof event.code === 'string' ? event.code : '';
    var now = typeof (event && event.timeStamp) === 'number' ? event.timeStamp : 0;

    if (this.lastAt !== null && now - this.lastAt > this.maxGapMs) {
      this.reset();
    }

    if (code === 'Enter' || code === 'NumpadEnter') {
      var value = this.chars.join('');
      var durationMs = this.firstAt === null ? 0 : Math.max(0, now - this.firstAt);
      this.reset();
      if (value.length < this.minLength) {
        return { accepted: false, rejected: 'too_short' };
      }
      if (value.length > this.maxLength) {
        return { accepted: false, rejected: 'too_long' };
      }
      if (!CHARSET.test(value)) {
        return { accepted: false, rejected: 'charset' };
      }
      return { accepted: true, value: value, durationMs: durationMs };
    }

    var ch = decodeEventCode(event);
    if (ch === null) {
      this.reset();
      return { accepted: false, rejected: 'human_key' };
    }
    if (this.chars.length >= this.maxLength) {
      this.reset();
      return { accepted: false, rejected: 'too_long' };
    }
    if (this.chars.length === 0) {
      this.firstAt = now;
    }
    this.chars.push(ch);
    this.lastAt = now;
    return { accepted: false };
  };

  /* Installs the capture-phase listener on `window`. Idempotent: the shell may
   * inject this script on every navigation, and dev hot-reload double-runs it. */
  function install(targetWindow) {
    if (!targetWindow || targetWindow.__FIHRIST_SCAN_BRIDGE_INSTALLED) {
      return false;
    }
    targetWindow.__FIHRIST_SCAN_BRIDGE_INSTALLED = true;

    var buffer = new ScannerBuffer();

    targetWindow.document.addEventListener(
      'keydown',
      function (event) {
        // Editable focus: the keystrokes land in the field and the app's own
        // keyboard-wedge path (the POS entry row) handles them. Doing anything
        // here would double-add.
        if (isEditableTarget(event)) {
          buffer.reset();
          return;
        }
        var outcome = buffer.push(event);
        if (outcome.accepted) {
          // Swallow the terminator so Enter never activates whatever random
          // control holds focus; the decoded value travels via the event.
          event.preventDefault();
          targetWindow.dispatchEvent(
            new targetWindow.CustomEvent(SCAN_EVENT_NAME, {
              detail: { value: outcome.value, durationMs: outcome.durationMs }
            })
          );
        }
      },
      true
    );

    return true;
  }

  // Node/vitest consumers get the pure pieces; a real webview auto-installs.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      SCAN_EVENT_NAME: SCAN_EVENT_NAME,
      decodeEventCode: decodeEventCode,
      isEditableTarget: isEditableTarget,
      ScannerBuffer: ScannerBuffer,
      install: install
    };
  }

  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    install(window);
    // Debug handle (and the test seam for jsdom-driven integration checks).
    window.__FihristScanBridge = {
      SCAN_EVENT_NAME: SCAN_EVENT_NAME,
      decodeEventCode: decodeEventCode,
      isEditableTarget: isEditableTarget,
      ScannerBuffer: ScannerBuffer
    };
  }
})();
