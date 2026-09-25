mod commands;
mod redaction;

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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let logger = StderrLogger {
        max: if cfg!(debug_assertions) {
            log::LevelFilter::Debug
        } else {
            log::LevelFilter::Info
        },
    };

    if log::set_boxed_logger(Box::new(logger)).is_ok() {
        log::set_max_level(logger.max);
    }

    if let Err(err) = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            commands::app_info,
            commands::log_write
        ])
        .run(tauri::generate_context!())
    {
        eprintln!("Fihrist exited with an error: {err}");
        std::process::exit(2);
    }
}
