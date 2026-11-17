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
    vec![]
}

#[tauri::command]
pub fn print_raw(_data: Vec<u8>) -> Result<(), String> {
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
