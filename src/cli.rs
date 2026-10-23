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
    #[arg(long = "log-level", default_value = "WARNING", value_parser = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])]
    pub log_level: String,

    /// Print the path to the bundled icon and exit.
    #[arg(long = "icon-path")]
    pub icon_path: bool,

    /// Print the path to the active config file and exit.
    #[arg(long = "config-path")]
    pub config_path: bool,

    /// Validate configuration without launching tools.
    #[arg(long = "check-config")]
    pub check_config: bool,
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
            if icon.is_file() {
                return Some(icon);
            }
            // Also check sibling to binary
            let icon = dir.join("launchline.ico");
            if icon.is_file() {
                return Some(icon);
            }
        }
        let directory = dirs::cache_dir()?
            .join("launchline")
            .join("assets")
            .join(env!("CARGO_PKG_VERSION"));
        Self::materialize_icon(&directory).ok()
    }

    fn materialize_icon(directory: &std::path::Path) -> std::io::Result<PathBuf> {
        use std::io::Write;
        const ICON: &[u8] = include_bytes!("../assets/launchline.ico");
        let destination = directory.join("launchline.ico");
        if std::fs::read(&destination).is_ok_and(|bytes| bytes == ICON) {
            return Ok(destination);
        }
        std::fs::create_dir_all(directory)?;
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let temporary = directory.join(format!(".icon-{}-{nonce}.tmp", std::process::id()));
        let result = (|| {
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temporary)?;
            file.write_all(ICON)?;
            file.sync_all()?;
            // Publish atomically without overwriting another process's destination.
            if let Err(error) = std::fs::hard_link(&temporary, &destination)
                && error.kind() != std::io::ErrorKind::AlreadyExists
            {
                return Err(error);
            }
            if std::fs::read(&destination)? != ICON {
                return Err(std::io::Error::other(
                    "Cached icon differs from bundled resource",
                ));
            }
            Ok(destination)
        })();
        let _ = std::fs::remove_file(&temporary);
        result
    }
}
