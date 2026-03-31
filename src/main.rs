mod cli;
mod config;
mod error;
mod fuzzy;
mod runner;
mod ui;
mod util;

use std::io::{self, Write};
use std::process;

use crate::cli::Args;
use crate::config::ConfigLoader;
use crate::error::LaunchLineError;
use crate::runner::EntryRunner;
use crate::ui::LaunchLineUI;

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

fn load_config(args: &Args) -> Result<config::LaunchLineConfig, LaunchLineError> {
    let config_existed =
        args.config.is_some() || ConfigLoader::default_path().is_some_and(|p| p.exists());

    let config_path = ConfigLoader::resolve_path(args.config.as_deref())?;

    if !config_existed {
        println!("Created starter config at {}", config_path.display());
        println!("Edit it to add your tools, then run launchline again.\n");
    }

    ConfigLoader::load(&config_path)
}

fn run_app(config: config::LaunchLineConfig) {
    let mut ui = LaunchLineUI::new(&config);
    let runner = EntryRunner::new(&config);

    loop {
        let selected = ui.run();
        let entry = match selected {
            Some(e) => e,
            None => break,
        };

        match runner.launch(entry) {
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
