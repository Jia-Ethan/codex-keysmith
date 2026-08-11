mod cli_runner;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            cli_runner::cli_run,
            cli_runner::read_manifest,
            cli_runner::detect_cli,
            cli_runner::cli_version,
            cli_runner::cli_runtime,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
