use std::io::{self, Write};
use std::path::Path;
use std::process::Command;

use crate::config::{EntryConfig, LaunchLineConfig};
use crate::error::LaunchLineError;
use crate::util::expand_tilde_str;

/// Handles launching subprocess commands for selected entries.
pub struct EntryRunner<'a> {
    config: &'a LaunchLineConfig,
}

impl<'a> EntryRunner<'a> {
    /// Create a runner with the given configuration.
    pub fn new(config: &'a LaunchLineConfig) -> Self {
        Self { config }
    }

    /// Launch an entry's command as a subprocess. Returns the exit code.
    pub fn launch(&self, entry: &EntryConfig) -> Result<i32, LaunchLineError> {
        Self::set_terminal_title(&entry.name);

        if self.config.clear_on_launch {
            Self::clear_screen();
        }

        let mut env: Vec<(String, String)> = std::env::vars().collect();
        for (key, value) in &entry.env {
            let expanded = if value.contains('~') {
                expand_tilde_str(value)
            } else {
                value.clone()
            };
            // Update existing or push new
            if let Some(existing) = env.iter_mut().find(|(k, _)| k == key) {
                existing.1 = expanded;
            } else {
                env.push((key.clone(), expanded));
            }
        }

        let cwd = entry.working_directory.as_deref();

        let mut cmd_args: Vec<&str> = Vec::new();
        let command;

        // On Windows, wrap .bat/.cmd files with cmd.exe /c
        #[cfg(target_os = "windows")]
        {
            let ext = Path::new(&entry.command)
                .extension()
                .and_then(|e| e.to_str())
                .unwrap_or("")
                .to_lowercase();
            if ext == "bat" || ext == "cmd" {
                command = "cmd.exe".to_string();
                cmd_args.push("/c");
                cmd_args.push(&entry.command);
            } else {
                command = entry.command.clone();
            }
        }
        #[cfg(not(target_os = "windows"))]
        {
            command = entry.command.clone();
        }

        for arg in &entry.args {
            cmd_args.push(arg);
        }

        log::info!("Launching: {} {}", command, cmd_args.join(" "));

        let mut proc = Command::new(&command);
        proc.args(&cmd_args);
        proc.envs(env.iter().map(|(k, v)| (k.as_str(), v.as_str())));

        if let Some(dir) = cwd {
            proc.current_dir(dir);
        }

        // Pass through stdin/stdout/stderr (inherit)
        proc.stdin(std::process::Stdio::inherit());
        proc.stdout(std::process::Stdio::inherit());
        proc.stderr(std::process::Stdio::inherit());

        let status = proc.status().map_err(|e| {
            if e.kind() == io::ErrorKind::NotFound {
                LaunchLineError::Launch {
                    command: entry.command.clone(),
                    reason: format!("Command not found: {}", entry.command),
                }
            } else {
                LaunchLineError::Launch {
                    command: entry.command.clone(),
                    reason: e.to_string(),
                }
            }
        })?;

        Ok(status.code().unwrap_or(1))
    }

    /// Clear the terminal screen and move the cursor to the home position.
    fn clear_screen() {
        let mut stdout = io::stdout();
        let _ = stdout.write_all(b"\x1b[2J\x1b[H");
        let _ = stdout.flush();
    }

    /// Set the terminal window/tab title using OSC escape sequence.
    fn set_terminal_title(title: &str) {
        let mut stdout = io::stdout();
        let _ = write!(stdout, "\x1b]0;{title}\x07");
        let _ = stdout.flush();
    }
}
