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

/// Build the primary workstation window. The native React application is
/// bundled directly within the installer and loaded via `WebviewUrl::App("index.html")`.
/// The hardware keyboard-wedge scanner bridge is injected as an initialization script.
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
#[allow(dead_code)]
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
        .invoke_handler(tauri::generate_handler![
            commands::app_info,
            commands::log_write,
            commands::list_printers,
            commands::print_raw,
            commands::open_cash_drawer,
            commands::check_update,
            commands::install_update,
            commands::open_customer_display,
            commands::read_settings,
            commands::write_settings
        ])
        .setup(|app| {
            log::info!("launching native Fihrist desktop workstation");
            build_main_window(app.handle(), WebviewUrl::App("index.html".into()))?;
            Ok(())
        })
        .run(tauri::generate_context!());

    if let Err(err) = result {
        eprintln!("Fihrist exited with an error: {err}");
        std::process::exit(2);
    }
}
