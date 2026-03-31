use std::path::{Path, PathBuf};

/// Expand a leading `~` in a path to the user's home directory.
pub fn expand_tilde(path: &Path) -> PathBuf {
    let s = path.to_string_lossy();
    if s.starts_with('~')
        && let Some(home) = dirs::home_dir()
    {
        let rest = s
            .strip_prefix("~/")
            .or_else(|| s.strip_prefix("~\\"))
            .or_else(|| s.strip_prefix('~'))
            .unwrap_or("");
        return home.join(rest);
    }
    path.to_path_buf()
}

/// Expand a leading `~` in a string to the user's home directory.
pub fn expand_tilde_str(s: &str) -> String {
    if s.starts_with('~')
        && let Some(home) = dirs::home_dir()
    {
        let rest = s
            .strip_prefix("~/")
            .or_else(|| s.strip_prefix("~\\"))
            .or_else(|| s.strip_prefix('~'))
            .unwrap_or("");
        return home.join(rest).to_string_lossy().to_string();
    }
    s.to_string()
}
