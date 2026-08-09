//! cli_runner — 包装 codex-instruct.py 的进程执行层
//!
//! 设计约束（见 SPEC.md §3）：
//! - Rust 只做进程执行与文件读取，不做业务解析（解析在前端 parser.js）
//! - 参数以数组传入，绝不拼接 shell 字符串
//! - 写操作全部由 CLI 完成，客户端永不直接修改 ~/.codex

use serde::Serialize;
use std::path::PathBuf;
use std::process::Stdio;
use tokio::io::AsyncReadExt;
use tokio::process::Command;
use tokio::time::{timeout, Duration};

const MANIFEST_FILENAME: &str = ".codex-keysmith-manifest.json";
const DEFAULT_TIMEOUT_MS: u64 = 30_000;
const PYTHON: &str = "python3";
const MAX_OUTPUT_BYTES: usize = 2 * 1024 * 1024; // 2 MB，防止异常输出撑爆内存

const CANDIDATE_NAMES: &[&str] = &["codex-instruct.py", "codex-keysmith"];

#[derive(Serialize)]
pub struct CliOutput {
    stdout: String,
    stderr: String,
    exit_code: i32,
    timed_out: bool,
}

/// 执行 CLI：python3 <cli> <args...>
/// cli_path 为 None 时按定位策略自动探测；为 Some 时只做 exists 校验。
#[tauri::command]
pub async fn cli_run(
    cli_path: Option<String>,
    args: Vec<String>,
    timeout_ms: Option<u64>,
) -> Result<CliOutput, String> {
    let cli = match cli_path {
        Some(p) if !p.trim().is_empty() => {
            let path = PathBuf::from(&p);
            if !path.is_file() {
                return Err(format!("CLI 文件不存在: {p}"));
            }
            path
        }
        _ => locate_cli().await.ok_or_else(|| {
            "未找到 codex-instruct.py。请在设置中指定 CLI 脚本路径。".to_string()
        })?,
    };

    let limit = Duration::from_millis(timeout_ms.unwrap_or(DEFAULT_TIMEOUT_MS));
    let mut child = Command::new(PYTHON)
        .arg(&cli)
        .args(&args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("无法启动 python3: {e}"))?;

    let stdout_reader = child.stdout.take().expect("stdout pipe");
    let stderr_reader = child.stderr.take().expect("stderr pipe");

    // 边跑边读，避免管道缓冲区占满导致死锁
    let read_task = tokio::spawn(async move {
        let mut out_buf = Vec::new();
        let mut err_buf = Vec::new();
        let mut out_limited = stdout_reader.take(MAX_OUTPUT_BYTES as u64);
        let mut err_limited = stderr_reader.take(MAX_OUTPUT_BYTES as u64);
        let (o, e) = tokio::join!(
            out_limited.read_to_end(&mut out_buf),
            err_limited.read_to_end(&mut err_buf)
        );
        o.ok();
        e.ok();
        (out_buf, err_buf)
    });

    let exit = match timeout(limit, child.wait()).await {
        Ok(Ok(status)) => status.code().unwrap_or(-1),
        Ok(Err(e)) => return Err(format!("等待 CLI 进程失败: {e}")),
        Err(_) => {
            // 超时：杀进程并等待退出，防止僵尸进程
            let _ = child.kill().await;
            let _ = child.wait().await;
            let (o, e) = read_task.await.unwrap_or_default();
            return Ok(CliOutput {
                stdout: String::from_utf8_lossy(&o).into_owned(),
                stderr: String::from_utf8_lossy(&e).into_owned(),
                exit_code: -1,
                timed_out: true,
            });
        }
    };

    let (o, e) = read_task.await.unwrap_or_default();
    Ok(CliOutput {
        stdout: String::from_utf8_lossy(&o).into_owned(),
        stderr: String::from_utf8_lossy(&e).into_owned(),
        exit_code: exit,
        timed_out: false,
    })
}

/// 读取指定 codex 目录的部署 manifest（结构化 JSON，SPEC.md §5.3）
///
/// 安全约束：只读取 <codex_dir>/.codex-keysmith-manifest.json，
/// 文件名精确匹配，不做任意文件读取。
#[tauri::command]
pub async fn read_manifest(codex_dir: String) -> Result<serde_json::Value, String> {
    let dir = PathBuf::from(&codex_dir);
    if !dir.is_dir() {
        return Err(format!("目录不存在: {codex_dir}"));
    }
    let manifest_path = dir.join(MANIFEST_FILENAME);
    if !manifest_path.is_file() {
        return Err(format!(
            "未找到部署清单: {}",
            manifest_path.display()
        ));
    }
    let content = tokio::fs::read(&manifest_path)
        .await
        .map_err(|e| format!("读取部署清单失败: {e}"))?;
    serde_json::from_slice(&content).map_err(|e| format!("部署清单不是合法 JSON: {e}"))
}

/// 探测 CLI 脚本路径。返回 None 表示未找到。
#[tauri::command]
pub async fn detect_cli() -> Result<Option<String>, String> {
    Ok(locate_cli().await.map(|p| p.to_string_lossy().into_owned()))
}

/// 获取 CLI 版本（python3 <cli> --version 的 stdout）
#[tauri::command]
pub async fn cli_version(cli_path: String) -> Result<String, String> {
    let path = PathBuf::from(&cli_path);
    if !path.is_file() {
        return Err(format!("CLI 文件不存在: {cli_path}"));
    }
    let output = Command::new(PYTHON)
        .arg(&path)
        .arg("--version")
        .output()
        .await
        .map_err(|e| format!("无法执行 CLI: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "获取版本失败 (exit {}): {}",
            output.status.code().unwrap_or(-1),
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

/// 获取 Python 版本（python3 --version）
#[tauri::command]
pub async fn python_version() -> Result<String, String> {
    let output = Command::new(PYTHON)
        .arg("--version")
        .output()
        .await
        .map_err(|e| format!("无法执行 python3: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "python3 不可用 (exit {}): {}",
            output.status.code().unwrap_or(-1),
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

/// 定位 CLI 脚本：环境变量 > 候选路径 > PATH
async fn locate_cli() -> Option<PathBuf> {
    if let Ok(env_path) = std::env::var("CODEX_KEYSMITH_CLI") {
        let p = PathBuf::from(env_path);
        if p.is_file() {
            return Some(p);
        }
    }

    for candidate in candidate_paths() {
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    find_in_path().await
}

fn candidate_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();

    // 可执行文件同目录（sidecar 未来放这里）
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for name in CANDIDATE_NAMES {
                paths.push(dir.join(name));
            }
        }
    }

    // 常见开发/安装位置
    if let Some(home) = std::env::var_os("HOME") {
        let home = PathBuf::from(home);
        for name in CANDIDATE_NAMES {
            paths.push(home.join(".codex-keysmith-gui").join(name));
            paths.push(home.join("codex-keysmith").join(name));
            paths.push(home.join("ZCodeProject").join("codex-keysmith").join(name));
            paths.push(home.join(".local").join("bin").join(name));
            paths.push(home.join("bin").join(name));
        }
    }

    paths.push(PathBuf::from("/usr/local/bin").join(CANDIDATE_NAMES[0]));
    paths.push(PathBuf::from("/opt/homebrew/bin").join(CANDIDATE_NAMES[0]));
    paths
}

async fn find_in_path() -> Option<PathBuf> {
    let path_var = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path_var) {
        for name in CANDIDATE_NAMES {
            let candidate = dir.join(name);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}
