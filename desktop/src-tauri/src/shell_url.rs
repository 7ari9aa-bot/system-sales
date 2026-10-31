//! Where the wrap-mode window points.
//!
//! Resolution order (first hit wins):
//!   1. the settings file's `web_app_url` key,
//!   2. the `FH_WEB_APP_URL` environment variable,
//!   3. `DEFAULT_WEB_APP_URL` — the one reviewed default this binary carries.
//!
//! The no-hardcoded-host principle (`desktop/docs/platform-boundary.md`,
//! enforced on the JS bundle by `config/check-no-hardcoded-host.mjs`) is
//! amended here, consciously and narrowly: the SHELL binary may carry a single
//! reviewed default so an install works out of the box, while every setting
//! overrides it and the JS bundle stays host-free. The validation rules are a
//! port of `src/platform/runtime.ts::parseRuntimeConfig` — the two must stay
//! in agreement; the tests mirror the TS cases.

use std::path::Path;

/// The deployed web application. Every override (settings file, env) wins over
/// this; it exists so a fresh install is one double-click away from the real
/// system.
pub const DEFAULT_WEB_APP_URL: &str = "https://fihrist.world";

pub const ENV_VAR: &str = "FH_WEB_APP_URL";
pub const SETTINGS_FILE_NAME: &str = "fihrist-desktop.json";
const SETTINGS_KEY: &str = "web_app_url";

const LOOPBACK_HOSTS: [&str; 3] = ["localhost", "127.0.0.1", "::1"];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UrlError {
    /// Nothing to resolve — the caller should fall back to the scaffold shell.
    Missing,
    /// Present but not a usable absolute http(s) URL (bad parse, credentials,
    /// query string — the places a token would leak).
    Invalid,
    /// Plain http to a non-loopback host.
    Insecure,
}

/// Validates and normalizes a web-app URL under the same rules the desktop's
/// TypeScript applies to API hosts. Returns the normalized origin + path.
pub fn validate_web_app_url(raw: &str) -> Result<String, UrlError> {
    let value = raw.trim();
    if value.is_empty() {
        return Err(UrlError::Missing);
    }

    let url = url::Url::parse(value).map_err(|_| UrlError::Invalid)?;

    let secure = url.scheme() == "https";
    let plain = url.scheme() == "http";
    if !secure && !plain {
        return Err(UrlError::Invalid);
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err(UrlError::Invalid);
    }
    if url.query().is_some() {
        return Err(UrlError::Invalid);
    }

    let host = match url.host() {
        Some(url::Host::Domain(domain)) => domain.to_string(),
        Some(url::Host::Ipv4(ip)) => ip.to_string(),
        Some(url::Host::Ipv6(ip)) => format!("[{ip}]"),
        None => return Err(UrlError::Invalid),
    };

    if !secure && !LOOPBACK_HOSTS.contains(&host.as_str()) {
        return Err(UrlError::Insecure);
    }

    let mut normalized = match url.port() {
        Some(port) => format!("{scheme}://{host}:{port}", scheme = url.scheme()),
        None => format!("{scheme}://{host}", scheme = url.scheme()),
    };
    normalized.push_str(url.path().trim_end_matches('/'));
    Ok(normalized)
}

/// Reads `web_app_url` out of the settings file, tolerating a missing file,
/// malformed JSON, or a missing/wrong-typed key — any of which simply means
/// "no setting" for the resolution order.
pub fn read_settings_web_app_url(path: &Path) -> Option<String> {
    let text = std::fs::read_to_string(path).ok()?;
    let value: serde_json::Value = serde_json::from_str(&text).ok()?;
    value.get(SETTINGS_KEY)?.as_str().map(str::to_string)
}

/// The full resolution order against provided sources. `settings_raw` is the
/// file's `web_app_url` (already read), `env_raw` the environment variable's
/// value. Split from I/O so the order is unit-testable.
pub fn resolve_from_parts(
    settings_raw: Option<String>,
    env_raw: Option<String>,
) -> Result<String, UrlError> {
    let candidates = [settings_raw, env_raw, Some(DEFAULT_WEB_APP_URL.to_string())];
    for candidate in candidates.into_iter().flatten() {
        match validate_web_app_url(&candidate) {
            Ok(normalized) => return Ok(normalized),
            Err(UrlError::Missing) => continue,
            Err(err) => {
                // The audit trail a merchant's broken configuration deserves:
                // name the rejection, then fall back to the reviewed default.
                log::warn!("a configured web_app_url was rejected ({err:?}); using the default");
            }
        }
    }
    // The reviewed default is last and valid, so this line IS the fallback; if
    // a future default edit were ever invalid, degrade to the scaffold instead
    // of panicking a shell that holds an open session.
    validate_web_app_url(DEFAULT_WEB_APP_URL)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_default_resolves() {
        assert_eq!(validate_web_app_url(DEFAULT_WEB_APP_URL), Ok("https://fihrist.world".into()));
    }

    #[test]
    fn empty_is_missing_not_invalid() {
        for raw in ["", "   "] {
            assert_eq!(validate_web_app_url(raw), Err(UrlError::Missing));
        }
    }

    #[test]
    fn refuses_the_shapes_the_ts_gate_refuses() {
        for raw in [
            "api.fihrist.app",
            "/api/v1",
            "ftp://api.fihrist.app",
            "javascript:alert(1)",
            "https://user:pass@fihrist.world",
            "https://user@fihrist.world",
            "https://fihrist.world/?next=/pos",
        ] {
            assert_eq!(validate_web_app_url(raw), Err(UrlError::Invalid), "{raw}");
        }
    }

    #[test]
    fn plain_http_is_loopback_only() {
        assert_eq!(
            validate_web_app_url("http://localhost:5173/"),
            Ok("http://localhost:5173".into())
        );
        assert_eq!(validate_web_app_url("http://127.0.0.1/pos"), Ok("http://127.0.0.1/pos".into()));
        assert_eq!(validate_web_app_url("http://[::1]/"), Ok("http://[::1]".into()));
        assert_eq!(validate_web_app_url("http://fihrist.world"), Err(UrlError::Insecure));
    }

    #[test]
    fn normalizes_trailing_slashes_and_keeps_paths() {
        assert_eq!(
            validate_web_app_url("https://fihrist.world/"),
            Ok("https://fihrist.world".into())
        );
        assert_eq!(
            validate_web_app_url("https://fihrist.world/app/"),
            Ok("https://fihrist.world/app".into())
        );
    }

    #[test]
    fn resolution_order_is_settings_then_env_then_default() {
        let ok = |s: &str| Some(s.to_string());
        // Settings win.
        assert_eq!(
            resolve_from_parts(ok("https://settings.example"), ok("https://env.example"))
                .as_deref(),
            Ok("https://settings.example")
        );
        // Env beats the default.
        assert_eq!(
            resolve_from_parts(None, ok("https://env.example")).as_deref(),
            Ok("https://env.example")
        );
        // The default carries it when nothing else exists.
        assert_eq!(
            resolve_from_parts(None, None).as_deref(),
            Ok(DEFAULT_WEB_APP_URL)
        );
        // Empty strings count as "not set", not as a rejection.
        assert_eq!(resolve_from_parts(ok(""), ok("")).as_deref(), Ok(DEFAULT_WEB_APP_URL));
    }

    #[test]
    fn a_broken_setting_falls_back_to_the_default_not_a_hard_failure() {
        // A merchant pointing at a malformed URL must still boot; the fallback
        // warning is the audit trail. (If the default itself were invalid, the
        // shell falls back to the scaffold — that case is exercised by
        // resolve's caller, since DEFAULT is reviewed this is the reachable
        // path.)
        assert_eq!(
            resolve_from_parts(ok("not a url"), None).as_deref(),
            Ok(DEFAULT_WEB_APP_URL)
        );
    }

    #[test]
    fn settings_reading_tolerates_every_absent_shape() {
        let dir = std::env::temp_dir().join(concat!("fihrist-shell-url-test-", line!()));
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join(SETTINGS_FILE_NAME);

        // Missing file.
        assert_eq!(read_settings_web_app_url(&path), None);

        std::fs::write(&path, "{ not json").ok();
        assert_eq!(read_settings_web_app_url(&path), None);

        std::fs::write(&path, r#"{"other": 1}"#).ok();
        assert_eq!(read_settings_web_app_url(&path), None);

        std::fs::write(&path, r#"{"web_app_url": 42}"#).ok();
        assert_eq!(read_settings_web_app_url(&path), None);

        std::fs::write(&path, r#"{"web_app_url": "https://fihrist.world/app"}"#).ok();
        assert_eq!(
            read_settings_web_app_url(&path),
            Some("https://fihrist.world/app".to_string())
        );

        let _ = std::fs::remove_file(&path);
    }
}
