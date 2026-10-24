//! The desktop shell: start the engine, wait for it, open a native window on it.
//!
//! Three decisions worth naming:
//!
//! * **The engine is a separate process.** Freezing the harness into the same binary as the window
//!   would couple UI crashes to runs; as a sidecar, a hung model call is a process you can kill.
//! * **The port is picked, not fixed.** 8765 is the default for humans, but two copies of the app (or
//!   a dev server) must not fight over it, so the shell asks the OS for a free port and tells the
//!   engine.
//! * **A token per launch.** The engine refuses `/api/*` without it, so another local process cannot
//!   drive the harness through the loopback interface.
//!
//! The window loads the engine's own page, which is the same front-end the CLI serves: one UI, not
//! one per shell.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

/// A windowed app must not flash a console per launch. The engine keeps its console subsystem (the
/// CLI is useful on its own), and the shell asks Windows to hide it for this process tree.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

struct Engine(Mutex<Option<Child>>);

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|address| address.port())
        .unwrap_or(8765)
}

fn launch_token() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_nanos())
        .unwrap_or(0);
    format!("{:x}{:x}", nanos, std::process::id())
}

/// The bundled engine (installer) or the built one (development checkout).
fn engine_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    if let Ok(resources) = app.path().resource_dir() {
        let bundled = resources.join("engine").join("nexus-harness-engine.exe");
        if bundled.is_file() {
            return Some(bundled);
        }
    }
    let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("dist")
        .join("nexus-harness-engine.exe");
    dev.is_file().then_some(dev)
}

fn wait_for_engine(port: u16, timeout: Duration) -> bool {
    let started = Instant::now();
    while started.elapsed() < timeout {
        if std::net::TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(120));
    }
    false
}

fn main() {
    tauri::Builder::default()
        .manage(Engine(Mutex::new(None)))
        .setup(|app| {
            let port = free_port();
            let token = launch_token();
            if let Some(path) = engine_path(&app.handle()) {
                let mut command = Command::new(path);
                command
                    .args(["serve", "--host", "127.0.0.1", "--port", &port.to_string()])
                    .env("NEXUS_HARNESS_TOKEN", &token)
                    .stdout(Stdio::null())
                    .stderr(Stdio::null());
                #[cfg(windows)]
                command.creation_flags(CREATE_NO_WINDOW);
                let child = command.spawn().ok();
                *app.state::<Engine>().0.lock().expect("engine lock") = child;
            }
            let url = format!("http://127.0.0.1:{}/?token={}", port, token);
            let parsed = url::Url::parse(&url)?;
            wait_for_engine(port, Duration::from_secs(30));
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(parsed))
                .title("Nexus Harness")
                .inner_size(1320.0, 860.0)
                .min_inner_size(980.0, 620.0)
                .center()
                .focused(true)
                .build()?;
            let _ = window.set_focus();
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.try_state::<Engine>() {
                    if let Ok(mut slot) = state.0.lock() {
                        if let Some(mut child) = slot.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("Nexus Harness failed to start");
}
