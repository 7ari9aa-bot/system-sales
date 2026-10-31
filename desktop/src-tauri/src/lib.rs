mod commands;
mod redaction;
mod scan_bridge;
mod shell_url;

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

/// The desktop's own logger. Phase 0 has no log file: the whole point of this
/// layer is that a record is filtered before it leaves the process, and where it
/// lands (rotating file, plugin, remote) is Phase 2's decision with its own ADR.
struct StderrLogger {
    max: log::LevelFilter,
}

impl log::Log for StderrLogger {
    fn enabled(&self, metadata: &log::Metadata<'_>) -> bool {
        metadata.level() <= self.max
    }

    fn log(&self, record: &log::Record<'_>) {
        if !self.enabled(record.metadata()) {
            return;
        }

        eprintln!("[{}] {} {}", record.level(), record.target(), record.args());
    }

    fn flush(&self) {}
}

/// One window, two modes. Wrap mode loads the real web application (the
/// product: cashier, inbox, dashboard) with the scan bridge injected; scaffold
/// mode loads the Phase 0 SPA as the fallback when no web-app URL resolves.
/// Either way the label stays `main`, which is what `capabilities/main.json`
/// grants.
fn build_main_window(manager: &tauri::AppHandle, url: WebviewUrl) -> tauri::Result<()> {
    WebviewWindowBuilder::new(manager, "main", url)
        .title("Fihrist")
        .inner_size(1280.0, 820.0)
        .min_inner_size(940.0, 600.0)
        .resizable(true)
        .center()
        .initialization_script(scan_bridge::SCAN_BRIDGE_JS)
        .build()?;
    Ok(())
}

/// Resolve the wrap-mode target. In a debug build with no explicit override,
/// `tauri dev` keeps loading the local scaffold — development must never
/// silently point a build at production. Release builds resolve settings file
/// → environment → reviewed default (see `shell_url`).
fn resolve_wrap_target(settings_path: Option<&std::path::Path>) -> Option<tauri::Url> {
    if cfg!(debug_assertions) && std::env::var(shell_url::ENV_VAR).is_err() {
        return None;
    }
    let settings_raw = settings_path.and_then(shell_url::read_settings_web_app_url);
    let env_raw = std::env::var(shell_url::ENV_VAR).ok();
    let normalized = match shell_url::resolve_from_parts(settings_raw, env_raw) {
        Ok(value) => value,
        Err(err) => {
            log::warn!("no web app url resolved ({err:?}); loading the scaffold shell");
            return None;
        }
    };
    match tauri::Url::parse(&normalized) {
        Ok(parsed) => Some(parsed),
        Err(err) => {
            // Unreachable while DEFAULT_WEB_APP_URL is valid — kept defensive
            // so a future default edit degrades to the scaffold, never a panic
            // (clippy denies unwrap/expect here on purpose).
            log::error!(
                "the resolved web app url failed re-parse ({err}); loading the scaffold shell"
            );
            None
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let max = if cfg!(debug_assertions) {
        log::LevelFilter::Debug
    } else {
        log::LevelFilter::Info
    };

    if log::set_boxed_logger(Box::new(StderrLogger { max })).is_ok() {
        log::set_max_level(max);
    }

    // A cashier double-clicking the icon twice must not open two tills on one
    // register — the single plugin pulled forward from Phase 2, and the only
    // one v1 takes.
    let result = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .invoke_handler(tauri::generate_handler![commands::app_info, commands::log_write])
        .setup(|app| {
            let settings_path = app
                .path()
                .app_config_dir()
                .ok()
                .map(|dir| dir.join(shell_url::SETTINGS_FILE_NAME));
            let target = resolve_wrap_target(settings_path.as_deref());
            match target {
                Some(parsed) => {
                    log::info!("wrap mode: loading {parsed}");
                    build_main_window(app.handle(), WebviewUrl::External(parsed))?;
                }
                None => {
                    log::info!("loading the scaffold shell (Phase 0 SPA)");
                    build_main_window(app.handle(), WebviewUrl::App("index.html".into()))?;
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!());

    if let Err(err) = result {
        eprintln!("Fihrist exited with an error: {err}");
        std::process::exit(2);
    }
}
