use std::io::{self, IsTerminal, Write};
use std::process;
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};

use launchline::cli::Args;
use launchline::config::ConfigLoader;
use launchline::error::LaunchLineError;
use launchline::runner::EntryRunner;
use launchline::ui::LaunchLineUI;

fn main() {
    let args = Args::parse_args();

    if args.icon_path {
        match Args::icon_path() {
            Some(p) => {
                println!("{}", p.display());
                return;
            }
            None => {
                eprintln!("Error: icon file not found");
                process::exit(1);
            }
        }
    }

    if args.config_path {
        match ConfigLoader::resolve_path(args.config.as_deref()) {
            Ok(p) => {
                println!("{}", p.display());
                return;
            }
            Err(e) => {
                eprintln!("Error: {e}");
                process::exit(1);
            }
        }
    }

    init_logging(&args.log_level);

    let config = match load_config(&args) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("Error: {e}");
            process::exit(1);
        }
    };

    if args.check_config {
        println!("Configuration valid: {} entries", config.entries.len());
        return;
    }
    if !io::stdin().is_terminal() || !io::stdout().is_terminal() {
        eprintln!(
            "Error: Interactive mode requires a terminal; use --check-config to validate configuration."
        );
        process::exit(1);
    }
    run_app(config);
}

fn init_logging(level: &str) {
    let filter = match level.to_uppercase().as_str() {
        "DEBUG" => log::LevelFilter::Debug,
        "INFO" => log::LevelFilter::Info,
        "WARNING" => log::LevelFilter::Warn,
        "ERROR" => log::LevelFilter::Error,
        "CRITICAL" => log::LevelFilter::Error,
        _ => log::LevelFilter::Warn,
    };
    env_logger::Builder::new().filter_level(filter).init();
}

fn load_config(args: &Args) -> Result<launchline::config::LaunchLineConfig, LaunchLineError> {
    let config_path = ConfigLoader::resolve_path(args.config.as_deref())?;

    ConfigLoader::load(&config_path)
}

fn run_app(config: launchline::config::LaunchLineConfig) {
    let interrupted = Arc::new(AtomicBool::new(false));
    let signal = Arc::clone(&interrupted);
    if let Err(error) = ctrlc::set_handler(move || signal.store(true, Ordering::SeqCst)) {
        eprintln!("Error: Cannot install interrupt handler: {error}");
        process::exit(1);
    }
    #[cfg(windows)]
    {
        // SAFETY: A null handler toggles only this process's inherited Ctrl+C flag.
        let enabled =
            unsafe { windows_sys::Win32::System::Console::SetConsoleCtrlHandler(None, 0) };
        if enabled == 0 {
            eprintln!(
                "Error: Cannot enable Ctrl+C: {}",
                io::Error::last_os_error()
            );
            process::exit(1);
        }
    }
    let mut ui = LaunchLineUI::new(&config);
    let runner = EntryRunner::new(&config);

    loop {
        let selected = ui.run();
        let entry = match selected {
            Some(e) => e,
            None => break,
        };

        interrupted.store(false, Ordering::SeqCst);
        let outcome = runner.launch(entry);
        if interrupted.swap(false, Ordering::SeqCst) {
            if config.on_exit == "exit" {
                process::exit(130);
            }
            continue;
        }
        match outcome {
            Ok(exit_code) => {
                if config.on_exit == "exit" {
                    process::exit(exit_code);
                }
            }
            Err(e) => {
                eprintln!("\nError: {e}");
                if config.on_exit == "exit" {
                    process::exit(1);
                }
                eprint!("Press Enter to return to the launcher...");
                let _ = io::stderr().flush();
                let mut buf = String::new();
                let _ = io::stdin().read_line(&mut buf);
            }
        }
    }
}
