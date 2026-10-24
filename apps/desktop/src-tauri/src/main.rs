//! The desktop shell: start the engine, wait for it, open a native window on it, and leave cleanly.
//!
//! Five decisions worth naming:
//!
//! * **The engine is a separate process.** Freezing the harness into the same binary as the window
//!   would couple UI crashes to runs; as a sidecar, a hung model call is a process you can kill.
//! * **The port is picked, not fixed.** 8765 is the default for humans, but two copies of the app (or
//!   a dev server) must not fight over it, so the shell asks the OS for a free port and tells the
//!   engine.
//! * **A token per launch.** The engine refuses `/api/*` without it, so another local process cannot
//!   drive the harness through the loopback interface.
//! * **Closing the window hides it in the tray.** Work in progress must survive the reflex of clicking
//!   the X, and the tray menu is where "stop everything" lives.
//! * **Leaving is orderly.** `POST /api/shutdown` first (the engine closes its socket and calls
//!   `os._exit(0)`, taking the PyInstaller bootloader with it), then `taskkill /T /F` as the fallback.
//!   Killing only the bootloader is what leaves an engine alive holding its own `.exe`, which is what
//!   silently blocks the next installer.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Write;
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

/// A windowed app must not flash a console per launch. The engine keeps its console subsystem (the
/// CLI is useful on its own), and the shell asks Windows to hide it for this process tree.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

struct Running {
    child: Child,
    port: u16,
    token: String,
}

struct Engine(Mutex<Option<Running>>);

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

/// Ask the engine to exit on its own: it closes its socket and calls `os._exit(0)`.
fn shutdown_request(port: u16, token: &str) -> bool {
    let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) else {
        return false;
    };
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    let request = format!(
        "POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Nexus-Token: {}\r\n\
         Content-Length: 0\r\nConnection: close\r\n\r\n",
        token
    );
    stream.write_all(request.as_bytes()).is_ok()
}

/// Last resort: the whole tree, because the bootloader and the engine are two PIDs.
fn tree_kill(pid: u32) {
    let mut command = Command::new("taskkill");
    command
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    let _ = command.status();
}

fn stop_engine(app: &tauri::AppHandle) {
    let running = app
        .try_state::<Engine>()
        .and_then(|state| state.0.lock().ok().and_then(|mut slot| slot.take()));
    if let Some(mut running) = running {
        shutdown_request(running.port, &running.token);
        std::thread::sleep(Duration::from_millis(400));
        if running.child.try_wait().ok().flatten().is_none() {
            tree_kill(running.child.id());
        }
        let _ = running.child.kill();
        let _ = running.child.wait();
    }
}

fn show_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
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
                if let Ok(child) = command.spawn() {
                    *app.state::<Engine>().0.lock().expect("engine lock") =
                        Some(Running { child, port, token: token.clone() });
                }
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

            let open = MenuItem::with_id(app, "open", "Abrir Nexus Harness", true, None::<&str>)?;
            let status = MenuItem::with_id(app, "status", "Estado del motor", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Salir completamente", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &status, &quit])?;
            let mut tray = TrayIconBuilder::with_id("nexus")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .tooltip("Nexus Harness")
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "open" => show_window(app),
                    "status" => show_window(app),
                    "quit" => {
                        stop_engine(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_window(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| match event {
            // The X hides the window: the run keeps going and the tray brings it back.
            tauri::WindowEvent::CloseRequested { api, .. } => {
                api.prevent_close();
                let _ = window.hide();
            }
            tauri::WindowEvent::Destroyed => stop_engine(window.app_handle()),
            _ => {}
        })
        .run(tauri::generate_context!())
        .expect("Nexus Harness failed to start");
}
