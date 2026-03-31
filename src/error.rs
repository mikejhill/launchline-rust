use std::fmt;

/// Error types for LaunchLine operations.
#[derive(Debug)]
pub enum LaunchLineError {
    /// A configuration file error (invalid TOML, missing fields, bad values).
    Configuration(String),
    /// A subprocess launch failure (command not found, permission denied, etc.).
    Launch { command: String, reason: String },
}

impl fmt::Display for LaunchLineError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Configuration(msg) => write!(f, "{msg}"),
            Self::Launch { command, reason } => {
                write!(f, "Failed to launch '{command}': {reason}")
            }
        }
    }
}

impl std::error::Error for LaunchLineError {}
