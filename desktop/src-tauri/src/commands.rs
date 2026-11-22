use serde::Deserialize;
use serde::Serialize;
use tauri::AppHandle;

use crate::redaction;

/// Whatever the platform can say about the machine it is running on.
///
/// `product_name` comes from the Cargo package name, which is not the brand — it
/// is confirmed against `tauri.conf.json` when the window manager lands in
/// Phase 2. Nothing renders this field today, and it is not asserted anywhere in
/// the UI for that reason.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AppInfo {
    product_name: String,
    version: String,
    os: &'static str,
}

const OS: &str = if cfg!(target_os = "windows") {
    "windows"
} else if cfg!(target_os = "macos") {
    "macos"
} else if cfg!(target_os = "linux") {
    "linux"
} else {
    "unknown"
};

#[tauri::command]
pub fn app_info(app: AppHandle) -> AppInfo {
    let package = app.package_info();

    AppInfo {
        product_name: package.name.clone(),
        version: package.version.to_string(),
        os: OS,
    }
}

/// A record the UI already redacted once. The logger filters again on the way
/// out: two independent chances for a token not to reach a file.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LogRecordIn {
    level: String,
    message: String,
    fields: serde_json::Value,
    request_id: Option<String>,
    sink: String,
}

#[tauri::command]
pub fn log_write(record: LogRecordIn) {
    let level = match record.level.as_str() {
        "debug" => log::Level::Debug,
        "warn" => log::Level::Warn,
        "error" => log::Level::Error,
        _ => log::Level::Info,
    };
    let line = redaction::render(
        &record.message,
        &record.fields,
        record.request_id.as_deref(),
    );

    log::log!(target: record.sink.as_str(), level, "{line}");
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PrinterDevice {
    pub name: String,
    pub vendor_id: Option<u16>,
    pub product_id: Option<u16>,
}

#[tauri::command]
pub fn list_printers() -> Vec<PrinterDevice> {
    #[cfg(target_os = "windows")]
    {
        let output = std::process::Command::new("powershell")
            .args([
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Printer | Select-Object -ExpandProperty Name",
            ])
            .output();

        if let Ok(out) = output {
            if out.status.success() {
                let text = String::from_utf8_lossy(&out.stdout);
                return text
                    .lines()
                    .map(|l| l.trim())
                    .filter(|l| !l.is_empty())
                    .map(|name| PrinterDevice {
                        name: name.to_string(),
                        vendor_id: None,
                        product_id: None,
                    })
                    .collect();
            }
        }
    }
    vec![]
}

#[tauri::command]
pub fn print_raw(data: Vec<u8>) -> Result<(), String> {
    if data.is_empty() {
        return Ok(());
    }

    #[cfg(target_os = "windows")]
    {
        let temp_dir = std::env::temp_dir();
        let file_path = temp_dir.join("fihrist_print_job.bin");
        if std::fs::write(&file_path, &data).is_ok() {
            let cmd = format!("Get-Content -Path '{}' | Out-Printer", file_path.display());
            let _ = std::process::Command::new("powershell")
                .args(["-NoProfile", "-Command", &cmd])
                .output();
            let _ = std::fs::remove_file(&file_path);
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        let _ = data;
    }

    Ok(())
}

#[tauri::command]
pub fn open_cash_drawer(printer_name: Option<String>) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        // Standard ESC/POS kick pulse: ESC p m t1 t2
        let kick_pulse: [u8; 5] = [0x1B, 0x70, 0x00, 0x19, 0xFA];
        let temp_dir = std::env::temp_dir();
        let file_path = temp_dir.join("fihrist_cash_drawer.bin");
        if std::fs::write(&file_path, kick_pulse).is_ok() {
            let cmd = match printer_name {
                Some(name) if !name.is_empty() => {
                    format!(
                        "Get-Content -Path '{}' | Out-Printer -Name '{}'",
                        file_path.display(),
                        name.replace('\'', "''")
                    )
                }
                _ => format!("Get-Content -Path '{}' | Out-Printer", file_path.display()),
            };
            let _ = std::process::Command::new("powershell")
                .args(["-NoProfile", "-Command", &cmd])
                .output();
            let _ = std::fs::remove_file(&file_path);
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        let _ = printer_name;
    }

    Ok(())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateCheckResult {
    pub available: bool,
    pub version: Option<String>,
    pub date: Option<String>,
    pub body: Option<String>,
}

#[tauri::command]
pub fn check_update() -> UpdateCheckResult {
    UpdateCheckResult {
        available: false,
        version: None,
        date: None,
        body: None,
    }
}

#[tauri::command]
pub fn install_update() -> Result<(), String> {
    Ok(())
}

#[tauri::command]
pub fn open_customer_display(app: AppHandle) -> Result<(), String> {
    use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
    if let Some(window) = app.get_webview_window("customer_display") {
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }

    WebviewWindowBuilder::new(
        &app,
        "customer_display",
        WebviewUrl::App("index.html#customer-display".into()),
    )
    .title("Fihrist - شاشة العميل")
    .inner_size(1024.0, 768.0)
    .min_inner_size(640.0, 480.0)
    .resizable(true)
    .build()
    .map_err(|e| e.to_string())?;

    Ok(())
}

#[tauri::command]
pub fn read_settings(app: AppHandle) -> Option<String> {
    use tauri::Manager;
    let path = app
        .path()
        .app_config_dir()
        .ok()?
        .join(crate::shell_url::SETTINGS_FILE_NAME);
    crate::shell_url::read_settings_web_app_url(&path)
}

#[tauri::command]
pub fn write_settings(app: AppHandle, web_app_url: String) -> Result<String, String> {
    use tauri::Manager;
    let validated =
        crate::shell_url::validate_web_app_url(&web_app_url).map_err(|e| format!("{e:?}"))?;

    let dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let path = dir.join(crate::shell_url::SETTINGS_FILE_NAME);

    let obj = serde_json::json!({
        "web_app_url": validated
    });
    std::fs::write(&path, obj.to_string()).map_err(|e| e.to_string())?;
    Ok(validated)
}

pub const SESSION_FILE_NAME: &str = "fihrist-session.json";

#[tauri::command]
pub fn read_auth_session(app: AppHandle) -> Option<String> {
    use tauri::Manager;
    let path = app.path().app_config_dir().ok()?.join(SESSION_FILE_NAME);
    if path.exists() {
        std::fs::read_to_string(&path).ok()
    } else {
        None
    }
}

#[tauri::command]
pub fn write_auth_session(app: AppHandle, session_json: String) -> Result<(), String> {
    use tauri::Manager;
    let dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let path = dir.join(SESSION_FILE_NAME);
    std::fs::write(&path, session_json).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn clear_auth_session(app: AppHandle) -> Result<(), String> {
    use tauri::Manager;
    if let Ok(dir) = app.path().app_config_dir() {
        let path = dir.join(SESSION_FILE_NAME);
        if path.exists() {
            let _ = std::fs::remove_file(path);
        }
    }
    Ok(())
}
