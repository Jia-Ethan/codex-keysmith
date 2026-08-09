//! Process boundary between the desktop client and codex-keysmith CLI.
//!
//! Packaged builds prefer the PyInstaller sidecar. Development and advanced
//! users can still point the app at `codex-instruct.py` as a fallback.

use serde::Serialize;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use tokio::io::{AsyncRead, AsyncReadExt};
use tokio::process::{Child, Command};
use tokio::time::{timeout, Duration};

const MANIFEST_FILENAME: &str = ".codex-keysmith-manifest.json";
const DEFAULT_TIMEOUT_MS: u64 = 30_000;
const VERSION_TIMEOUT_MS: u64 = 5_000;
const MAX_OUTPUT_BYTES: usize = 2 * 1024 * 1024;
const SIDECAR_BASENAME: &str = "codex-keysmith-cli";
const SCRIPT_NAME: &str = "codex-instruct.py";

#[derive(Default)]
struct CapturedOutput {
    bytes: Vec<u8>,
    truncated: bool,
    error: Option<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum CliRuntime {
    Bundled,
    Executable,
    Python,
}

impl CliRuntime {
    fn key(self) -> &'static str {
        match self {
            Self::Bundled => "bundled",
            Self::Executable => "executable",
            Self::Python => "python",
        }
    }
}

#[derive(Clone, Debug)]
struct CliInvocation {
    path: PathBuf,
    program: PathBuf,
    prefix_args: Vec<OsString>,
    runtime: CliRuntime,
}

impl CliInvocation {
    fn command(&self) -> Command {
        let mut command = Command::new(&self.program);
        command.args(&self.prefix_args);
        command
    }
}

#[derive(Serialize)]
pub struct CliDescriptor {
    path: String,
    runtime: &'static str,
}

impl From<&CliInvocation> for CliDescriptor {
    fn from(invocation: &CliInvocation) -> Self {
        Self {
            path: invocation.path.to_string_lossy().into_owned(),
            runtime: invocation.runtime.key(),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct CliOutput {
    stdout: String,
    stderr: String,
    exit_code: i32,
    timed_out: bool,
}

#[tauri::command]
pub async fn cli_run(
    cli_path: Option<String>,
    args: Vec<String>,
    timeout_ms: Option<u64>,
) -> Result<CliOutput, String> {
    let invocation = resolve_invocation(cli_path.as_deref())?;
    run_invocation(
        &invocation,
        &args,
        Duration::from_millis(timeout_ms.unwrap_or(DEFAULT_TIMEOUT_MS)),
    )
    .await
}

async fn run_invocation(
    invocation: &CliInvocation,
    args: &[String],
    limit: Duration,
) -> Result<CliOutput, String> {
    let mut command = invocation.command();
    configure_process_tree(&mut command);
    command.kill_on_drop(true);
    let mut child = command
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| {
            format!(
                "无法启动 CLI（{}）: {error}",
                invocation.path.to_string_lossy()
            )
        })?;

    let stdout_reader = child.stdout.take().expect("stdout pipe");
    let stderr_reader = child.stderr.take().expect("stderr pipe");
    let read_task = tokio::spawn(async move {
        tokio::join!(read_capped(stdout_reader), read_capped(stderr_reader))
    });

    let exit = match timeout(limit, child.wait()).await {
        Ok(Ok(status)) => status.code().unwrap_or(-1),
        Ok(Err(error)) => {
            terminate_process_tree(&mut child).await;
            let _ = read_task.await;
            return Err(format!("等待 CLI 进程失败: {error}"));
        }
        Err(_) => {
            terminate_process_tree(&mut child).await;
            let (stdout, stderr) = read_task.await.unwrap_or_default();
            return Ok(CliOutput {
                stdout: String::from_utf8_lossy(&stdout.bytes).into_owned(),
                stderr: String::from_utf8_lossy(&stderr.bytes).into_owned(),
                exit_code: -1,
                timed_out: true,
            });
        }
    };

    let (stdout, stderr) = read_task
        .await
        .map_err(|error| format!("读取 CLI 输出任务失败: {error}"))?;
    validate_captured_output(&stdout, &stderr)?;
    Ok(CliOutput {
        stdout: String::from_utf8_lossy(&stdout.bytes).into_owned(),
        stderr: String::from_utf8_lossy(&stderr.bytes).into_owned(),
        exit_code: exit,
        timed_out: false,
    })
}

#[cfg(unix)]
fn configure_process_tree(command: &mut Command) {
    command.process_group(0);
}

#[cfg(windows)]
fn configure_process_tree(command: &mut Command) {
    const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
    command.creation_flags(CREATE_NEW_PROCESS_GROUP);
}

#[cfg(not(any(unix, windows)))]
fn configure_process_tree(_command: &mut Command) {}

#[cfg(unix)]
async fn terminate_process_tree(child: &mut Child) {
    if let Some(pid) = child.id() {
        if let Ok(pid) = i32::try_from(pid) {
            // The child is the leader of an isolated process group, so this
            // also stops PyInstaller bootloader descendants.
            unsafe {
                libc::kill(-pid, libc::SIGKILL);
            }
        }
    }
    let _ = child.kill().await;
    let _ = child.wait().await;
}

#[cfg(windows)]
async fn terminate_process_tree(child: &mut Child) {
    if let Some(pid) = child.id() {
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .await;
    }
    let _ = child.kill().await;
    let _ = child.wait().await;
}

#[cfg(not(any(unix, windows)))]
async fn terminate_process_tree(child: &mut Child) {
    let _ = child.kill().await;
    let _ = child.wait().await;
}

fn validate_captured_output(
    stdout: &CapturedOutput,
    stderr: &CapturedOutput,
) -> Result<(), String> {
    let mut issues = Vec::new();
    for (label, captured) in [("stdout", stdout), ("stderr", stderr)] {
        if captured.truncated {
            issues.push(format!("{label} 超过 {MAX_OUTPUT_BYTES} 字节上限"));
        }
        if let Some(error) = &captured.error {
            issues.push(format!("读取 {label} 失败: {error}"));
        }
    }
    if issues.is_empty() {
        Ok(())
    } else {
        Err(format!(
            "CLI 输出不完整，已阻止继续操作: {}",
            issues.join("; ")
        ))
    }
}

async fn read_capped<R>(mut reader: R) -> CapturedOutput
where
    R: AsyncRead + Unpin,
{
    let mut captured = CapturedOutput::default();
    let mut chunk = [0_u8; 8192];
    loop {
        let read = match reader.read(&mut chunk).await {
            Ok(0) => break,
            Ok(read) => read,
            Err(error) => {
                captured.error = Some(error.to_string());
                break;
            }
        };
        let remaining = MAX_OUTPUT_BYTES.saturating_sub(captured.bytes.len());
        if remaining > 0 {
            captured
                .bytes
                .extend_from_slice(&chunk[..read.min(remaining)]);
        }
        if read > remaining {
            captured.truncated = true;
        }
    }
    captured
}

/// Read only the deployment manifest at the exact supported filename.
#[tauri::command]
pub async fn read_manifest(codex_dir: String) -> Result<serde_json::Value, String> {
    let dir = PathBuf::from(&codex_dir);
    if !dir.is_dir() {
        return Err(format!("目录不存在: {codex_dir}"));
    }
    let manifest_path = dir.join(MANIFEST_FILENAME);
    if !manifest_path.is_file() {
        return Err(format!("未找到部署清单: {}", manifest_path.display()));
    }
    let content = tokio::fs::read(&manifest_path)
        .await
        .map_err(|error| format!("读取部署清单失败: {error}"))?;
    serde_json::from_slice(&content).map_err(|error| format!("部署清单不是合法 JSON: {error}"))
}

#[tauri::command]
pub async fn detect_cli() -> Result<Option<CliDescriptor>, String> {
    Ok(locate_cli()?.as_ref().map(CliDescriptor::from))
}

#[tauri::command]
pub async fn cli_version(cli_path: Option<String>) -> Result<String, String> {
    let invocation = resolve_invocation(cli_path.as_deref())?;
    let output = run_invocation(
        &invocation,
        &["--version".to_string()],
        Duration::from_millis(VERSION_TIMEOUT_MS),
    )
    .await?;
    if output.timed_out {
        return Err("获取 CLI 版本超时".to_string());
    }
    if output.exit_code != 0 {
        return Err(format!(
            "获取版本失败 (exit {}): {}",
            output.exit_code, output.stderr
        ));
    }
    Ok(output.stdout.trim().to_string())
}

#[tauri::command]
pub async fn cli_runtime(cli_path: Option<String>) -> Result<String, String> {
    Ok(resolve_invocation(cli_path.as_deref())?
        .runtime
        .key()
        .to_string())
}

fn resolve_invocation(cli_path: Option<&str>) -> Result<CliInvocation, String> {
    if let Some(path) = cli_path.filter(|path| !path.trim().is_empty()) {
        return invocation_for_path(PathBuf::from(path), false);
    }
    locate_cli()?.ok_or_else(|| {
        "未找到内置 CLI 或 codex-instruct.py。请重新安装应用或在设置中指定脚本路径。".to_string()
    })
}

fn locate_cli() -> Result<Option<CliInvocation>, String> {
    if let Some(path) = bundled_sidecar_path().filter(|path| path.is_file()) {
        return invocation_for_path(path, true).map(Some);
    }

    if let Ok(path) = std::env::var("CODEX_KEYSMITH_CLI") {
        let path = PathBuf::from(path);
        if path.is_file() {
            return invocation_for_path(path, false).map(Some);
        }
    }

    for path in fallback_candidate_paths() {
        if path.is_file() {
            return invocation_for_path(path, false).map(Some);
        }
    }

    for name in path_candidate_names() {
        if let Some(path) = find_program_in_path(name) {
            return invocation_for_path(path, false).map(Some);
        }
    }
    Ok(None)
}

fn invocation_for_path(path: PathBuf, bundled: bool) -> Result<CliInvocation, String> {
    if !path.is_file() {
        return Err(format!("CLI 文件不存在: {}", path.display()));
    }

    let runtime = runtime_for_path(&path, bundled);
    if runtime == CliRuntime::Python {
        let python = python_program().ok_or_else(|| {
            "指定的是 Python 脚本，但系统中没有可用的 Python 解释器。".to_string()
        })?;
        return Ok(CliInvocation {
            path: path.clone(),
            program: python,
            prefix_args: vec![path.into_os_string()],
            runtime,
        });
    }

    Ok(CliInvocation {
        program: path.clone(),
        path,
        prefix_args: Vec::new(),
        runtime,
    })
}

fn runtime_for_path(path: &Path, bundled: bool) -> CliRuntime {
    if bundled {
        CliRuntime::Bundled
    } else if path
        .extension()
        .is_some_and(|extension| extension.eq_ignore_ascii_case("py"))
    {
        CliRuntime::Python
    } else {
        CliRuntime::Executable
    }
}

fn bundled_sidecar_path() -> Option<PathBuf> {
    std::env::current_exe()
        .ok()?
        .parent()
        .map(|directory| directory.join(sidecar_filename()))
}

#[cfg(windows)]
fn sidecar_filename() -> String {
    format!("{SIDECAR_BASENAME}.exe")
}

#[cfg(not(windows))]
fn sidecar_filename() -> &'static str {
    SIDECAR_BASENAME
}

fn fallback_candidate_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Ok(executable) = std::env::current_exe() {
        if let Some(directory) = executable.parent() {
            for name in path_candidate_names() {
                paths.push(directory.join(name));
            }
        }
    }

    if let Some(home) = home_directory() {
        for name in path_candidate_names() {
            paths.push(home.join(".codex-keysmith-gui").join(name));
            paths.push(home.join("codex-keysmith").join(name));
            paths.push(home.join("ZCodeProject").join("codex-keysmith").join(name));
            paths.push(home.join(".local").join("bin").join(name));
            paths.push(home.join("bin").join(name));
        }
    }

    #[cfg(not(windows))]
    for directory in ["/usr/local/bin", "/opt/homebrew/bin"] {
        for name in path_candidate_names() {
            paths.push(PathBuf::from(directory).join(name));
        }
    }
    paths
}

fn home_directory() -> Option<PathBuf> {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
}

fn path_candidate_names() -> &'static [&'static str] {
    #[cfg(windows)]
    {
        &["codex-keysmith.exe", "codex-keysmith", SCRIPT_NAME]
    }
    #[cfg(not(windows))]
    {
        &["codex-keysmith", SCRIPT_NAME]
    }
}

fn python_program() -> Option<PathBuf> {
    if let Some(path) = std::env::var_os("CODEX_KEYSMITH_PYTHON") {
        let path = PathBuf::from(path);
        if path.is_file() {
            return Some(path);
        }
    }

    #[cfg(windows)]
    let candidates = ["python.exe", "python3.exe"];
    #[cfg(not(windows))]
    let candidates = ["python3", "python"];

    candidates
        .iter()
        .find_map(|candidate| find_program_in_path(candidate))
}

fn find_program_in_path(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|directory| directory.join(name))
        .find(|candidate| candidate.is_file())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundled_runtime_wins_over_file_extension() {
        assert_eq!(
            runtime_for_path(Path::new("codex-keysmith-cli.py"), true),
            CliRuntime::Bundled
        );
    }

    #[test]
    fn python_scripts_are_fallback_invocations() {
        assert_eq!(
            runtime_for_path(Path::new("codex-instruct.PY"), false),
            CliRuntime::Python
        );
    }

    #[test]
    fn native_binaries_run_directly() {
        assert_eq!(
            runtime_for_path(Path::new("codex-keysmith.exe"), false),
            CliRuntime::Executable
        );
    }

    #[test]
    fn executable_candidates_precede_python_script() {
        let candidates = path_candidate_names();
        assert_eq!(candidates.last(), Some(&SCRIPT_NAME));
        assert!(candidates[..candidates.len() - 1]
            .iter()
            .all(|candidate| !candidate.ends_with(".py")));
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn timeout_terminates_descendant_processes() {
        let invocation = CliInvocation {
            path: PathBuf::from("/bin/sh"),
            program: PathBuf::from("/bin/sh"),
            prefix_args: vec![
                OsString::from("-c"),
                OsString::from("sleep 60 & child=$!; echo $child; wait $child"),
            ],
            runtime: CliRuntime::Executable,
        };

        let output = run_invocation(&invocation, &[], Duration::from_millis(100))
            .await
            .expect("timeout result");
        assert!(output.timed_out);
        let descendant: i32 = output.stdout.trim().parse().expect("descendant pid");

        for _ in 0..40 {
            if unsafe { libc::kill(descendant, 0) } != 0 {
                return;
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        panic!("descendant process survived timeout");
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn oversized_output_fails_closed() {
        let invocation = CliInvocation {
            path: PathBuf::from("/bin/sh"),
            program: PathBuf::from("/bin/sh"),
            prefix_args: vec![
                OsString::from("-c"),
                OsString::from("dd if=/dev/zero bs=1048576 count=3 2>/dev/null"),
            ],
            runtime: CliRuntime::Executable,
        };

        let error = run_invocation(&invocation, &[], Duration::from_secs(5))
            .await
            .expect_err("oversized output must fail closed");
        assert!(error.contains("stdout"));
        assert!(error.contains("输出不完整"));
    }
}
