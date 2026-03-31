use std::path::PathBuf;

use clap::Parser;

#[derive(Parser, Debug)]
#[command(
    name = "launchline",
    about = "A lightweight launcher for interactive CLI tools."
)]
pub struct Args {
    /// Path to config TOML (overrides env var and default path).
    #[arg(long)]
    pub config: Option<PathBuf>,

    /// Logging verbosity (default: WARNING).
    #[arg(long = "log-level", default_value = "WARNING")]
    pub log_level: String,

    /// Print the path to the bundled icon and exit.
    #[arg(long = "icon-path")]
    pub icon_path: bool,

    /// Print the path to the active config file and exit.
    #[arg(long = "config-path")]
    pub config_path: bool,
}

impl Args {
    /// Parse command-line arguments.
    pub fn parse_args() -> Self {
        Self::parse()
    }

    /// Return the path to the bundled LaunchLine icon, if it exists.
    pub fn icon_path() -> Option<PathBuf> {
        // Look for the icon relative to the executable
        if let Ok(exe) = std::env::current_exe()
            && let Some(dir) = exe.parent()
        {
            let icon = dir.join("assets").join("launchline.ico");
            if icon.exists() {
                return Some(icon);
            }
            // Also check sibling to binary
            let icon = dir.join("launchline.ico");
            if icon.exists() {
                return Some(icon);
            }
        }
        None
    }
}
