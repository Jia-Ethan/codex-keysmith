mod cli_runner;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            cli_runner::cli_run,
            cli_runner::read_manifest,
            cli_runner::detect_cli,
            cli_runner::cli_version,
            cli_runner::python_version,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
