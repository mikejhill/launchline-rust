use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::error::LaunchLineError;
use crate::util::expand_tilde;

// -- Public config types ---------------------------------------------------

/// A single launchable entry parsed from the config file.
#[derive(Debug, Clone)]
pub struct EntryConfig {
    pub name: String,
    pub command: String,
    pub args: Vec<String>,
    pub description: String,
    pub working_directory: Option<PathBuf>,
    pub env: HashMap<String, String>,
}

/// Top-level configuration combining settings and entries.
#[derive(Debug, Clone)]
pub struct LaunchLineConfig {
    pub entries: Vec<EntryConfig>,
    pub title: String,
    pub on_exit: String,
    pub show_exit: bool,
    pub clear_on_launch: bool,
    pub ghost_text: bool,
    pub numeric_trigger: bool,
}

// -- Raw TOML deserialization types ----------------------------------------
// These intermediate structs accept optional/loose fields from serde, then
// `ConfigLoader::validate` converts them into the strict public types above.

#[derive(Deserialize)]
struct RawConfig {
    settings: Option<RawSettings>,
    entries: Option<Vec<RawEntry>>,
}

#[derive(Deserialize)]
struct RawSettings {
    title: Option<String>,
    on_exit: Option<String>,
    show_exit: Option<bool>,
    clear_on_launch: Option<bool>,
    ghost_text: Option<bool>,
    numeric_trigger: Option<bool>,
}

#[derive(Deserialize)]
struct RawEntry {
    name: Option<String>,
    command: Option<String>,
    args: Option<Vec<String>>,
    description: Option<String>,
    working_directory: Option<String>,
    env: Option<HashMap<String, String>>,
}

// -- Config loader ---------------------------------------------------------

/// Handles locating, loading, and validating LaunchLine config files.
pub struct ConfigLoader;

const ENV_VAR_NAME: &str = "LAUNCHLINE_CONFIG";
const VALID_ON_EXIT: &[&str] = &["restart", "exit"];

const STARTER_CONFIG: &str = "\
# LaunchLine configuration
# See https://github.com/mikejhill/launchline#configuration-reference

[settings]
# title = \"LaunchLine\"
# on_exit = \"restart\"   # \"restart\" (default) or \"exit\"
# show_exit = true
# clear_on_launch = true
# ghost_text = true
# numeric_trigger = true

[[entries]]
name = \"PowerShell\"
command = \"pwsh\"
description = \"PowerShell 7\"
";

impl ConfigLoader {
    /// Return the default config path: ~/.config/launchline/config.toml
    ///
    /// Uses `~/.config` on all platforms to match the Python version's behavior
    /// and ensure config file compatibility across the transition.
    pub fn default_path() -> Option<PathBuf> {
        dirs::home_dir().map(|h| h.join(".config").join("launchline").join("config.toml"))
    }

    /// Resolve the config file path using priority:
    /// CLI flag → env var → default path (auto-create if missing).
    pub fn resolve_path(cli_path: Option<&Path>) -> Result<PathBuf, LaunchLineError> {
        if let Some(p) = cli_path {
            let expanded = expand_tilde(p);
            if !expanded.exists() {
                return Err(LaunchLineError::Configuration(format!(
                    "Config file not found: {}",
                    expanded.display()
                )));
            }
            return Ok(expanded);
        }

        if let Ok(env_val) = std::env::var(ENV_VAR_NAME)
            && !env_val.is_empty()
        {
            let expanded = expand_tilde(Path::new(&env_val));
            if expanded.exists() {
                return Ok(expanded);
            }
            return Err(LaunchLineError::Configuration(format!(
                "Config file from {ENV_VAR_NAME} not found: {}",
                expanded.display()
            )));
        }

        if let Some(default) = Self::default_path()
            && default.exists()
        {
            return Ok(default);
        }

        Self::create_default()
    }

    /// Load and validate a TOML config file.
    pub fn load(config_path: &Path) -> Result<LaunchLineConfig, LaunchLineError> {
        let content = fs::read_to_string(config_path).map_err(|e| {
            LaunchLineError::Configuration(format!("Cannot read {}: {e}", config_path.display()))
        })?;

        let raw: RawConfig = toml::from_str(&content).map_err(|e| {
            LaunchLineError::Configuration(format!(
                "Invalid TOML in {}: {e}",
                config_path.display()
            ))
        })?;

        let settings = raw.settings.unwrap_or(RawSettings {
            title: None,
            on_exit: None,
            show_exit: None,
            clear_on_launch: None,
            ghost_text: None,
            numeric_trigger: None,
        });

        let title = settings.title.unwrap_or_else(|| "LaunchLine".to_string());
        Self::validate_display(&title)?;
        let on_exit = settings.on_exit.unwrap_or_else(|| "restart".to_string());

        if !VALID_ON_EXIT.contains(&on_exit.as_str()) {
            return Err(LaunchLineError::Configuration(format!(
                "Invalid on_exit value: '{on_exit}'. Must be one of: {}",
                VALID_ON_EXIT.join(", ")
            )));
        }

        let show_exit = settings.show_exit.unwrap_or(true);
        let clear_on_launch = settings.clear_on_launch.unwrap_or(true);
        let ghost_text = settings.ghost_text.unwrap_or(true);
        let numeric_trigger = settings.numeric_trigger.unwrap_or(true);

        let raw_entries = raw.entries.unwrap_or_default();
        if raw_entries.is_empty() {
            return Err(LaunchLineError::Configuration(
                "No entries configured.".to_string(),
            ));
        }

        let mut entries = Vec::with_capacity(raw_entries.len());
        for (i, raw_entry) in raw_entries.into_iter().enumerate() {
            let idx = i + 1;
            let name = raw_entry.name.unwrap_or_default();
            let command = raw_entry.command.unwrap_or_default();

            if name.is_empty() || command.is_empty() {
                return Err(LaunchLineError::Configuration(format!(
                    "Entry {idx}: 'name' and 'command' are required."
                )));
            }

            let args = raw_entry.args.unwrap_or_default();

            let description = raw_entry.description.unwrap_or_default();

            if let Some(directory) = &raw_entry.working_directory {
                Self::validate_display(directory)?;
            }
            let working_directory = raw_entry.working_directory.and_then(|wd| {
                if wd.is_empty() {
                    return None;
                }
                let expanded = expand_tilde(Path::new(&wd));
                if expanded.is_dir() {
                    Some(expanded)
                } else {
                    log::warn!(
                        "Entry '{}': working_directory does not exist: {}",
                        name,
                        expanded.display()
                    );
                    None
                }
            });

            let env = raw_entry.env.unwrap_or_default();
            for value in [&name, &command, &description] {
                Self::validate_display(value)?;
            }
            if args.iter().any(|arg| arg.contains('\0'))
                || env.iter().any(|(key, value)| {
                    key.is_empty() || key.contains(['=', '\0']) || value.contains('\0')
                })
            {
                return Err(LaunchLineError::Configuration(format!(
                    "Entry {idx}: invalid NUL or environment key."
                )));
            }

            entries.push(EntryConfig {
                name,
                command,
                args,
                description,
                working_directory,
                env,
            });
        }

        Ok(LaunchLineConfig {
            entries,
            title,
            on_exit,
            show_exit,
            clear_on_launch,
            ghost_text,
            numeric_trigger,
        })
    }

    fn validate_display(value: &str) -> Result<(), LaunchLineError> {
        if value.chars().any(char::is_control) {
            return Err(LaunchLineError::Configuration(
                "Display values must not contain control characters.".to_string(),
            ));
        }
        Ok(())
    }

    fn create_default() -> Result<PathBuf, LaunchLineError> {
        let path = Self::default_path().ok_or_else(|| {
            LaunchLineError::Configuration("Cannot determine config directory".to_string())
        })?;

        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| {
                LaunchLineError::Configuration(format!("Cannot create config directory: {e}"))
            })?;
        }

        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
        {
            Ok(mut stream) => stream
                .write_all(STARTER_CONFIG.as_bytes())
                .map_err(|error| {
                    LaunchLineError::Configuration(format!("Cannot write config file: {error}"))
                })?,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => return Ok(path),
            Err(error) => {
                return Err(LaunchLineError::Configuration(format!(
                    "Cannot create config file: {error}"
                )));
            }
        }

        log::info!("Created starter config at {}", path.display());
        Ok(path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn load_valid_config() {
        let toml_content = r#"
[settings]
title = "Test"
on_exit = "exit"

[[entries]]
name = "Alpha"
command = "alpha-cmd"
description = "First entry"
args = ["--flag"]

[[entries]]
name = "Beta"
command = "beta-cmd"
"#;
        let dir = std::env::temp_dir().join("launchline_test_valid");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("config.toml");
        let mut f = fs::File::create(&path).unwrap();
        f.write_all(toml_content.as_bytes()).unwrap();

        let config = ConfigLoader::load(&path).unwrap();
        assert_eq!(config.title, "Test", "title should match");
        assert_eq!(config.on_exit, "exit", "on_exit should match");
        assert_eq!(config.entries.len(), 2, "should have 2 entries");
        assert_eq!(config.entries[0].name, "Alpha", "first entry name");
        assert_eq!(config.entries[0].args, vec!["--flag"], "first entry args");
        assert_eq!(config.entries[1].name, "Beta", "second entry name");

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn load_no_entries_fails() {
        let toml_content = "[settings]\ntitle = \"Empty\"\n";
        let dir = std::env::temp_dir().join("launchline_test_no_entries");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("config.toml");
        fs::write(&path, toml_content).unwrap();

        let result = ConfigLoader::load(&path);
        assert!(result.is_err(), "should fail with no entries");

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn load_invalid_on_exit_fails() {
        let toml_content = r#"
[settings]
on_exit = "invalid"

[[entries]]
name = "A"
command = "a"
"#;
        let dir = std::env::temp_dir().join("launchline_test_invalid_on_exit");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("config.toml");
        fs::write(&path, toml_content).unwrap();

        let result = ConfigLoader::load(&path);
        assert!(result.is_err(), "should fail with invalid on_exit");

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn load_missing_name_fails() {
        let toml_content = "[[entries]]\ncommand = \"x\"\n";
        let dir = std::env::temp_dir().join("launchline_test_missing_name");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("config.toml");
        fs::write(&path, toml_content).unwrap();

        let result = ConfigLoader::load(&path);
        assert!(result.is_err(), "should fail when entry missing name");

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn defaults_applied() {
        let toml_content = "[[entries]]\nname = \"A\"\ncommand = \"a\"\n";
        let dir = std::env::temp_dir().join("launchline_test_defaults");
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("config.toml");
        fs::write(&path, toml_content).unwrap();

        let config = ConfigLoader::load(&path).unwrap();
        assert_eq!(config.title, "LaunchLine", "default title");
        assert_eq!(config.on_exit, "restart", "default on_exit");
        assert!(config.show_exit, "default show_exit");
        assert!(config.clear_on_launch, "default clear_on_launch");
        assert!(config.ghost_text, "default ghost_text");
        assert!(config.numeric_trigger, "default numeric_trigger");

        let _ = fs::remove_dir_all(&dir);
    }
}
