use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::error::LaunchLineError;
use crate::util::expand_tilde;

// -- Public config types ---------------------------------------------------

/// A single launchable entry parsed from the config file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntryConfig {
    pub name: String,
    pub command: String,
    pub args: Vec<String>,
    pub description: String,
    pub working_directory: Option<PathBuf>,
    pub env: HashMap<String, String>,
    pub id: String,
    pub menu: Option<Box<MenuConfig>>,
}

/// A trusted executable provider with a bounded deadline.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProviderConfig {
    pub entry: EntryConfig,
    pub timeout_seconds: u64,
}

/// A static or generated menu declaration; snapshots belong to the session.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MenuConfig {
    pub entries: Vec<EntryConfig>,
    pub title: String,
    pub provider: Option<Box<ProviderConfig>>,
    pub refresh_on_return: bool,
}

/// Top-level configuration combining settings and entries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LaunchLineConfig {
    pub entries: Vec<EntryConfig>,
    pub title: String,
    pub on_exit: String,
    pub show_exit: bool,
    pub clear_on_launch: bool,
    pub ghost_text: bool,
    pub numeric_trigger: bool,
    pub provider: Option<Box<ProviderConfig>>,
    pub refresh_on_return: bool,
}

// -- Raw TOML deserialization types ----------------------------------------
// These intermediate structs accept optional/loose fields from serde, then
// `ConfigLoader::validate` converts them into the strict public types above.

#[derive(Deserialize)]
struct RawConfig {
    settings: Option<RawSettings>,
    entries: Option<Vec<RawEntry>>,
    provider: Option<RawProvider>,
}

#[derive(Deserialize)]
struct RawSettings {
    title: Option<String>,
    on_exit: Option<String>,
    show_exit: Option<bool>,
    clear_on_launch: Option<bool>,
    ghost_text: Option<bool>,
    numeric_trigger: Option<bool>,
    refresh_on_return: Option<bool>,
}

#[derive(Deserialize)]
struct RawEntry {
    id: Option<String>,
    menu: Option<RawMenu>,
    name: Option<String>,
    command: Option<String>,
    args: Option<Vec<String>>,
    description: Option<String>,
    working_directory: Option<String>,
    env: Option<HashMap<String, String>>,
}

#[derive(Deserialize)]
struct RawMenu {
    title: Option<String>,
    refresh_on_return: Option<bool>,
    entries: Option<Vec<RawEntry>>,
    provider: Option<RawProvider>,
}

#[derive(Deserialize)]
struct RawProvider {
    command: String,
    args: Option<Vec<String>>,
    env: Option<HashMap<String, String>>,
    working_directory: Option<String>,
    timeout_seconds: Option<u64>,
    menu: Option<serde_json::Value>,
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
            refresh_on_return: None,
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

        let menu = Self::menu(
            RawMenu {
                title: None,
                refresh_on_return: None,
                entries: raw.entries,
                provider: raw.provider,
            },
            &title,
            0,
        )?;
        if menu.entries.is_empty() && menu.provider.is_none() {
            return Err(LaunchLineError::Configuration(
                "No entries configured.".into(),
            ));
        }
        let entries = menu.entries;
        let provider = menu.provider;
        let refresh_on_return = settings.refresh_on_return.unwrap_or(false);

        Ok(LaunchLineConfig {
            entries,
            title,
            on_exit,
            show_exit,
            clear_on_launch,
            ghost_text,
            numeric_trigger,
            provider,
            refresh_on_return,
        })
    }

    /// Parse a generated entries array through the same typed validation as TOML.
    pub fn parse_entries(
        value: serde_json::Value,
        depth: usize,
    ) -> Result<Vec<EntryConfig>, LaunchLineError> {
        Self::validate_json_entries(&value)?;
        let raw: Vec<RawEntry> = serde_json::from_value(value).map_err(|error| {
            LaunchLineError::Configuration(format!("Invalid provider entries: {error}"))
        })?;
        Self::entries(raw, depth)
    }

    fn reject_nulls(
        table: &serde_json::Map<String, serde_json::Value>,
        keys: &[&str],
    ) -> Result<(), LaunchLineError> {
        if keys
            .iter()
            .any(|key| table.get(*key).is_some_and(serde_json::Value::is_null))
        {
            return Err(LaunchLineError::Configuration(
                "Declared fields must not be null.".into(),
            ));
        }
        Ok(())
    }

    fn validate_json_entries(value: &serde_json::Value) -> Result<(), LaunchLineError> {
        if let Some(entries) = value.as_array() {
            for entry in entries {
                if let Some(table) = entry.as_object() {
                    Self::reject_nulls(
                        table,
                        &[
                            "name",
                            "command",
                            "args",
                            "description",
                            "working_directory",
                            "env",
                            "id",
                            "menu",
                        ],
                    )?;
                    if let Some(menu) = table.get("menu").and_then(serde_json::Value::as_object) {
                        Self::reject_nulls(
                            menu,
                            &["title", "entries", "provider", "refresh_on_return"],
                        )?;
                        if let Some(entries) = menu.get("entries") {
                            Self::validate_json_entries(entries)?;
                        }
                        if let Some(provider) =
                            menu.get("provider").and_then(serde_json::Value::as_object)
                        {
                            Self::reject_nulls(
                                provider,
                                &[
                                    "command",
                                    "args",
                                    "env",
                                    "working_directory",
                                    "timeout_seconds",
                                    "menu",
                                ],
                            )?;
                        }
                    }
                }
            }
        }
        Ok(())
    }

    fn entries(
        raw_entries: Vec<RawEntry>,
        depth: usize,
    ) -> Result<Vec<EntryConfig>, LaunchLineError> {
        if raw_entries.len() > 1000 {
            return Err(LaunchLineError::Configuration(
                "At most 1000 entries are allowed per menu.".into(),
            ));
        }
        let mut entries = Vec::with_capacity(raw_entries.len());
        for (i, raw_entry) in raw_entries.into_iter().enumerate() {
            let idx = i + 1;
            let has_command = raw_entry.command.is_some();
            let name = raw_entry.name.clone().unwrap_or_default();
            let command = raw_entry.command.clone().unwrap_or_default();

            if name.is_empty() || (command.is_empty() && raw_entry.menu.is_none()) {
                return Err(LaunchLineError::Configuration(format!(
                    "Entry {idx}: 'name' and 'command' are required."
                )));
            }

            let id = raw_entry.id.unwrap_or_default();
            Self::validate_display(&id)?;
            if raw_entry.menu.is_some()
                && (has_command
                    || raw_entry.args.is_some()
                    || raw_entry.env.is_some()
                    || raw_entry.working_directory.is_some())
            {
                return Err(LaunchLineError::Configuration(
                    "menu and command fields are exclusive.".into(),
                ));
            }
            let menu = raw_entry
                .menu
                .map(|menu| Self::menu(menu, &name, depth + 1))
                .transpose()?
                .map(Box::new);
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
                id,
                menu,
            });
        }

        let mut identities = std::collections::HashSet::new();
        for entry in &entries {
            if !entry.id.is_empty() && !identities.insert(&entry.id) {
                return Err(LaunchLineError::Configuration(
                    "Entry ids must be unique within each menu.".into(),
                ));
            }
        }
        Ok(entries)
    }

    fn menu(raw: RawMenu, fallback: &str, depth: usize) -> Result<MenuConfig, LaunchLineError> {
        if depth >= 16 {
            return Err(LaunchLineError::Configuration(
                "Menus may be nested at most 16 levels including root.".into(),
            ));
        }
        if raw.provider.is_some() && raw.entries.is_some() {
            return Err(LaunchLineError::Configuration(
                "A menu must declare entries or provider, not both.".into(),
            ));
        }
        let title = raw.title.unwrap_or_else(|| fallback.into());
        Self::validate_display(&title)?;
        let provider = raw.provider.map(Self::provider).transpose()?.map(Box::new);
        let entries = Self::entries(raw.entries.unwrap_or_default(), depth)?;
        Ok(MenuConfig {
            entries,
            title,
            provider,
            refresh_on_return: raw.refresh_on_return.unwrap_or(false),
        })
    }

    fn provider(raw: RawProvider) -> Result<ProviderConfig, LaunchLineError> {
        if raw.menu.is_some() {
            return Err(LaunchLineError::Configuration(
                "A provider must be an executable command.".into(),
            ));
        }
        let timeout_seconds = raw.timeout_seconds.unwrap_or(10);
        if !(1..=300).contains(&timeout_seconds) {
            return Err(LaunchLineError::Configuration(
                "timeout_seconds must be an integer from 1 to 300.".into(),
            ));
        }
        let entry = RawEntry {
            name: Some("menu provider".into()),
            command: Some(raw.command),
            args: raw.args,
            env: raw.env,
            working_directory: raw.working_directory,
            description: None,
            id: None,
            menu: None,
        };
        Ok(ProviderConfig {
            entry: Self::entries(vec![entry], 0)?.remove(0),
            timeout_seconds,
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
