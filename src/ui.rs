use std::io::{self, Write};
use std::time::Duration;

use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers},
    terminal,
};

use crate::config::{EntryConfig, LaunchLineConfig};
use crate::fuzzy::FuzzyMatcher;

const MAX_LIST_HEIGHT: usize = 10;
// header(4) + cwd(1) + sep_above(1) + prompt(1) + sep_below(1) + footer(1)
const CHROME_LINES: usize = 9;

// ANSI SGR colour codes
const HEADER_ACCENT: &str = "\x1b[38;5;69m"; // Cornflower blue
const ACTIVE_ACCENT: &str = "\x1b[92m"; // Bright green
const GRAY: &str = "\x1b[90m"; // Dark gray
const BOLD: &str = "\x1b[1m";
const WHITE: &str = "\x1b[97m"; // Bright white
const RESET: &str = "\x1b[0m";

/// A numbered entry for display (1-based index, 0 for exit).
#[derive(Clone)]
struct NumberedEntry<'a> {
    number: usize,
    entry: &'a EntryConfig,
}

/// Sentinel exit entry.
fn exit_entry_config() -> EntryConfig {
    EntryConfig {
        name: "Exit".to_string(),
        command: String::new(),
        args: Vec::new(),
        description: "Close the launcher".to_string(),
        working_directory: None,
        env: std::collections::HashMap::new(),
    }
}

/// Interactive terminal UI for the launcher menu.
pub struct LaunchLineUI<'a> {
    config: &'a LaunchLineConfig,
    all_entries: Vec<NumberedEntry<'a>>,
    exit_entry: EntryConfig,
    show_exit: bool,
    ghost_text_enabled: bool,
    numeric_trigger: bool,

    // Mutable state
    query: String,
    cursor_pos: usize,
    highlight_idx: usize,
    visible: Vec<usize>, // indices into all_entries
    exit_visible: bool,
    viewport_offset: usize,
}

impl<'a> LaunchLineUI<'a> {
    /// Create a new UI from the loaded configuration.
    pub fn new(config: &'a LaunchLineConfig) -> Self {
        let all_entries: Vec<NumberedEntry<'a>> = config
            .entries
            .iter()
            .enumerate()
            .map(|(i, e)| NumberedEntry {
                number: i + 1,
                entry: e,
            })
            .collect();

        let visible: Vec<usize> = (0..all_entries.len()).collect();

        Self {
            config,
            all_entries,
            exit_entry: exit_entry_config(),
            show_exit: config.show_exit,
            ghost_text_enabled: config.ghost_text,
            numeric_trigger: config.numeric_trigger,
            query: String::new(),
            cursor_pos: 0,
            highlight_idx: 0,
            visible,
            exit_visible: config.show_exit,
            viewport_offset: 0,
        }
    }

    /// Display the launcher and wait for user selection.
    /// Returns the selected EntryConfig, or None if the user exits.
    pub fn run(&mut self) -> Option<&EntryConfig> {
        self.reset();
        self.enter_alt_screen();

        let result_idx = self.run_loop();

        self.leave_alt_screen();
        result_idx.map(|idx| &self.config.entries[idx])
    }

    fn run_loop(&mut self) -> Option<usize> {
        let mut dirty = true;
        let mut last_size: (u16, u16) = (0, 0);

        loop {
            let size = terminal::size().unwrap_or((80, 24));
            if dirty || size != last_size {
                self.render();
                last_size = size;
                dirty = false;
            }

            // Poll for key events with 50ms timeout
            if event::poll(Duration::from_millis(50)).unwrap_or(false) {
                if let Ok(Event::Key(key_event)) = event::read() {
                    // Only process key press events (not release/repeat)
                    if key_event.kind != KeyEventKind::Press {
                        continue;
                    }
                    match self.on_key(key_event) {
                        KeyAction::Continue => {
                            dirty = true;
                        }
                        KeyAction::Launch(idx) => {
                            return Some(idx);
                        }
                        KeyAction::Exit => {
                            return None;
                        }
                        KeyAction::Ignore => {}
                    }
                }
            } else if size != last_size {
                // Terminal resized with no key event
                dirty = true;
            }
        }
    }

    fn reset(&mut self) {
        self.query.clear();
        self.cursor_pos = 0;
        self.highlight_idx = 0;
        self.visible = (0..self.all_entries.len()).collect();
        self.exit_visible = self.show_exit;
        self.viewport_offset = 0;
    }

    // -- Display list (visible + exit) -------------------------------------

    fn display_list_len(&self) -> usize {
        self.visible.len() + if self.exit_visible { 1 } else { 0 }
    }

    fn display_entry(&self, idx: usize) -> (&str, usize, &str) {
        // Returns (name, number, description) for display index
        if idx < self.visible.len() {
            let ne = &self.all_entries[self.visible[idx]];
            (&ne.entry.name, ne.number, &ne.entry.description)
        } else {
            (&self.exit_entry.name, 0, &self.exit_entry.description)
        }
    }

    fn is_exit_entry(&self, display_idx: usize) -> bool {
        display_idx >= self.visible.len()
    }

    // -- Key handling ------------------------------------------------------

    fn on_key(&mut self, key: KeyEvent) -> KeyAction {
        let modifiers = key.modifiers;
        let ctrl = modifiers.contains(KeyModifiers::CONTROL);
        let alt = modifiers.contains(KeyModifiers::ALT);

        match key.code {
            KeyCode::Esc => {
                if !self.query.is_empty() {
                    self.query.clear();
                    self.cursor_pos = 0;
                    self.update_filter();
                    KeyAction::Continue
                } else {
                    KeyAction::Exit
                }
            }

            KeyCode::Enter => {
                let dl_len = self.display_list_len();
                if dl_len > 0 && self.highlight_idx < dl_len {
                    if self.is_exit_entry(self.highlight_idx) {
                        KeyAction::Exit
                    } else {
                        let entry_idx = self.visible[self.highlight_idx];
                        KeyAction::Launch(entry_idx)
                    }
                } else {
                    KeyAction::Ignore
                }
            }

            KeyCode::Up => {
                let dl_len = self.display_list_len();
                if dl_len > 0 {
                    if self.highlight_idx > 0 {
                        self.highlight_idx -= 1;
                    } else {
                        self.highlight_idx = dl_len - 1;
                    }
                    self.ensure_highlight_visible();
                }
                KeyAction::Continue
            }

            KeyCode::Down => {
                let dl_len = self.display_list_len();
                if dl_len > 0 {
                    if self.highlight_idx < dl_len - 1 {
                        self.highlight_idx += 1;
                    } else {
                        self.highlight_idx = 0;
                    }
                    self.ensure_highlight_visible();
                }
                KeyAction::Continue
            }

            KeyCode::Backspace if ctrl || alt => {
                if !self.query.is_empty() && self.cursor_pos > 0 {
                    self.delete_word_back();
                    self.update_filter();
                }
                KeyAction::Continue
            }

            KeyCode::Backspace => {
                if !self.query.is_empty() && self.cursor_pos > 0 {
                    self.cursor_pos -= 1;
                    self.query.remove(self.cursor_pos);
                    self.update_filter();
                }
                KeyAction::Continue
            }

            KeyCode::Char('u') if ctrl => {
                if !self.query.is_empty() {
                    self.query = self.query[self.cursor_pos..].to_string();
                    self.cursor_pos = 0;
                    self.update_filter();
                }
                KeyAction::Continue
            }

            KeyCode::Char('k') if ctrl => {
                if self.cursor_pos < self.query.len() {
                    self.query.truncate(self.cursor_pos);
                    self.update_filter();
                }
                KeyAction::Continue
            }

            KeyCode::Char('w') if ctrl => {
                if !self.query.is_empty() && self.cursor_pos > 0 {
                    self.delete_word_back();
                    self.update_filter();
                }
                KeyAction::Continue
            }

            KeyCode::Char('a') if ctrl => {
                self.cursor_pos = 0;
                KeyAction::Continue
            }

            KeyCode::Char('e') if ctrl => {
                self.cursor_pos = self.query.len();
                KeyAction::Continue
            }

            KeyCode::Char('b') if ctrl => {
                if self.cursor_pos > 0 {
                    self.cursor_pos -= 1;
                }
                KeyAction::Continue
            }

            KeyCode::Char('f') if ctrl => {
                if self.cursor_pos < self.query.len() {
                    self.cursor_pos += 1;
                }
                KeyAction::Continue
            }

            KeyCode::Char('d') if ctrl => {
                if !self.query.is_empty() && self.cursor_pos < self.query.len() {
                    self.query.remove(self.cursor_pos);
                    self.update_filter();
                } else if self.query.is_empty() {
                    return KeyAction::Exit;
                }
                KeyAction::Continue
            }

            KeyCode::Char('h') if ctrl => {
                // ctrl-h = backspace
                if !self.query.is_empty() && self.cursor_pos > 0 {
                    self.cursor_pos -= 1;
                    self.query.remove(self.cursor_pos);
                    self.update_filter();
                }
                KeyAction::Continue
            }

            KeyCode::Char('b') if alt => {
                self.cursor_pos = self.word_boundary_back();
                KeyAction::Continue
            }

            KeyCode::Char('f') if alt => {
                self.cursor_pos = self.word_boundary_forward();
                KeyAction::Continue
            }

            KeyCode::Char('d') if alt => {
                if self.cursor_pos < self.query.len() {
                    let end = self.word_boundary_forward();
                    self.query =
                        format!("{}{}", &self.query[..self.cursor_pos], &self.query[end..]);
                    self.update_filter();
                }
                KeyAction::Continue
            }

            KeyCode::Char('c') if ctrl => KeyAction::Exit,

            KeyCode::Char(ch) if !ctrl && !alt => self.on_char(ch),

            _ => KeyAction::Ignore,
        }
    }

    fn on_char(&mut self, ch: char) -> KeyAction {
        // "0" with no active query selects exit
        if self.query.is_empty() && ch == '0' && self.show_exit {
            return KeyAction::Exit;
        }

        // Immediate single-digit launch when ≤9 total entries
        if self.numeric_trigger
            && self.query.is_empty()
            && ch.is_ascii_digit()
            && self.all_entries.len() <= 9
        {
            let num = ch.to_digit(10).unwrap_or(0) as usize;
            if num >= 1 && num <= self.all_entries.len() {
                return KeyAction::Launch(num - 1);
            }
            return KeyAction::Ignore;
        }

        self.query.insert(self.cursor_pos, ch);
        self.cursor_pos += 1;
        self.update_filter();

        // Auto-launch if exactly one numeric match remains
        if self.numeric_trigger
            && self.query.chars().all(|c| c.is_ascii_digit())
            && self.visible.len() == 1
        {
            return KeyAction::Launch(self.visible[0]);
        }

        KeyAction::Continue
    }

    // -- Word operations ---------------------------------------------------

    fn word_boundary_back(&self) -> usize {
        let bytes = self.query.as_bytes();
        let mut i = self.cursor_pos;
        while i > 0 && bytes[i - 1] == b' ' {
            i -= 1;
        }
        while i > 0 && bytes[i - 1] != b' ' {
            i -= 1;
        }
        i
    }

    fn word_boundary_forward(&self) -> usize {
        let bytes = self.query.as_bytes();
        let n = bytes.len();
        let mut i = self.cursor_pos;
        while i < n && bytes[i] != b' ' {
            i += 1;
        }
        while i < n && bytes[i] == b' ' {
            i += 1;
        }
        i
    }

    fn delete_word_back(&mut self) {
        let left = &self.query[..self.cursor_pos];
        let right = &self.query[self.cursor_pos..];
        let bytes = left.as_bytes();
        let mut i = bytes.len();
        while i > 0 && bytes[i - 1] == b' ' {
            i -= 1;
        }
        while i > 0 && bytes[i - 1] != b' ' {
            i -= 1;
        }
        self.query = format!("{}{}", &left[..i], right);
        self.cursor_pos = i;
    }

    // -- Filtering ---------------------------------------------------------

    fn update_filter(&mut self) {
        if self.query.is_empty() {
            self.visible = (0..self.all_entries.len()).collect();
            self.exit_visible = self.show_exit;
        } else if self.query.chars().all(|c| c.is_ascii_digit()) && self.numeric_trigger {
            // Numeric prefix filter against entry numbers
            self.visible = (0..self.all_entries.len())
                .filter(|&i| {
                    self.all_entries[i]
                        .number
                        .to_string()
                        .starts_with(&self.query)
                })
                .collect();
            self.exit_visible = self.show_exit && "0".starts_with(&self.query);
        } else if self.query.chars().all(|c| c.is_ascii_digit()) {
            // Numeric + fuzzy: number prefix matches first, then name fuzzy
            let mut number_matches: Vec<usize> = (0..self.all_entries.len())
                .filter(|&i| {
                    self.all_entries[i]
                        .number
                        .to_string()
                        .starts_with(&self.query)
                })
                .collect();
            let number_set: std::collections::HashSet<usize> =
                number_matches.iter().copied().collect();

            let mut scored: Vec<(i32, usize)> = (0..self.all_entries.len())
                .filter(|i| !number_set.contains(i))
                .filter_map(|i| {
                    FuzzyMatcher::score(&self.query, &self.all_entries[i].entry.name)
                        .map(|s| (s, i))
                })
                .collect();
            scored.sort_by(|a, b| b.0.cmp(&a.0));

            number_matches.extend(scored.iter().map(|&(_, i)| i));
            self.visible = number_matches;
            self.exit_visible = self.show_exit && "0".starts_with(&self.query);
        } else {
            // Fuzzy search against entry names
            let mut scored: Vec<(i32, usize)> = (0..self.all_entries.len())
                .filter_map(|i| {
                    FuzzyMatcher::score(&self.query, &self.all_entries[i].entry.name)
                        .map(|s| (s, i))
                })
                .collect();
            scored.sort_by(|a, b| b.0.cmp(&a.0));
            self.visible = scored.iter().map(|&(_, i)| i).collect();

            self.exit_visible =
                self.show_exit && FuzzyMatcher::score(&self.query, &self.exit_entry.name).is_some();
        }

        self.highlight_idx = 0;
        self.viewport_offset = 0;
    }

    // -- Viewport ----------------------------------------------------------

    fn max_visible_entries(&self) -> usize {
        let (_, th) = terminal::size().unwrap_or((80, 24));
        let available = (th as usize).saturating_sub(CHROME_LINES).max(1);
        available.min(MAX_LIST_HEIGHT)
    }

    fn ensure_highlight_visible(&mut self) {
        let max_vis = self.max_visible_entries();
        if self.highlight_idx < self.viewport_offset {
            self.viewport_offset = self.highlight_idx;
        } else if self.highlight_idx >= self.viewport_offset + max_vis {
            self.viewport_offset = self.highlight_idx - max_vis + 1;
        }
    }

    // -- Rendering ---------------------------------------------------------

    fn render(&self) {
        let (tw, th) = terminal::size().unwrap_or((80, 24));
        let tw = tw as usize;
        let th = th as usize;
        let max_vis = self.max_visible_entries();

        let dl_len = self.display_list_len();
        let total_items = dl_len;

        let num_width = if self.all_entries.is_empty() {
            1
        } else {
            self.all_entries.len().to_string().len()
        };
        let max_name_len = self
            .all_entries
            .iter()
            .map(|ne| ne.entry.name.len())
            .max()
            .unwrap_or(0)
            .max(4); // "Exit" length

        let sep_line: String = format!("{GRAY}{}{RESET}", "\u{2500}".repeat(tw));

        let mut buf = String::with_capacity(4096);
        let mut row: usize = 1;

        // -- Header (4 lines: top border, title, subtitle, bottom border) --
        let title = &self.config.title;
        let header_inner = 72usize.min(tw.saturating_sub(2)).max(4);
        let subtitle = "Select a tool to launch.";
        let subtitle_plain = format!(" {subtitle} ");
        let subtitle_fill = header_inner.saturating_sub(subtitle_plain.len());

        // Top border
        buf.push_str(&format!(
            "\x1b[{row};1H{HEADER_ACCENT}\u{256d}{}{HEADER_ACCENT}\u{256e}{RESET}\x1b[K",
            "\u{2500}".repeat(header_inner),
        ));
        row += 1;

        // Title row
        let title_text = format!(" {title} ");
        let title_fill = header_inner.saturating_sub(title_text.len());
        buf.push_str(&format!(
            "\x1b[{row};1H{HEADER_ACCENT}\u{2502}{RESET}{BOLD}{WHITE}{title_text}{RESET}{}{HEADER_ACCENT}\u{2502}{RESET}\x1b[K",
            " ".repeat(title_fill),
        ));
        row += 1;

        // Subtitle row
        buf.push_str(&format!(
            "\x1b[{row};1H{HEADER_ACCENT}\u{2502}{RESET}{GRAY}{subtitle_plain}{RESET}{}{HEADER_ACCENT}\u{2502}{RESET}\x1b[K",
            " ".repeat(subtitle_fill),
        ));
        row += 1;

        // Bottom border
        buf.push_str(&format!(
            "\x1b[{row};1H{HEADER_ACCENT}\u{2570}{}{HEADER_ACCENT}\u{256f}{RESET}\x1b[K",
            "\u{2500}".repeat(header_inner),
        ));
        row += 1;

        // -- CWD (1 line, gray) --
        let cwd = std::env::current_dir()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_default();
        let home = dirs::home_dir()
            .map(|h| h.to_string_lossy().to_string())
            .unwrap_or_default();
        let display_cwd = if !home.is_empty() && cwd.starts_with(&home) {
            format!("~{}", &cwd[home.len()..])
        } else {
            cwd
        };
        buf.push_str(&format!("\x1b[{row};1H {GRAY}{display_cwd}{RESET}\x1b[K"));
        row += 1;

        // -- Separator above prompt --
        buf.push_str(&format!("\x1b[{row};1H{sep_line}\x1b[K"));
        row += 1;

        // -- Prompt line --
        let hint = if self.ghost_text_enabled {
            self.ghost_text()
        } else {
            String::new()
        };
        let hint_str = if !hint.is_empty() {
            format!(" {GRAY}({hint}){RESET}")
        } else {
            String::new()
        };
        let no_match = if !self.query.is_empty() && dl_len == 0 {
            format!(" {GRAY}(no matches){RESET}")
        } else {
            String::new()
        };
        buf.push_str(&format!(
            "\x1b[{row};1H{ACTIVE_ACCENT}\u{276f}{RESET} {WHITE}{BOLD}{}{RESET}{hint_str}{no_match}\x1b[K",
            self.query,
        ));
        let prompt_row = row;
        row += 1;

        // -- Separator below prompt --
        buf.push_str(&format!("\x1b[{row};1H{sep_line}\x1b[K"));
        row += 1;

        // -- Scrollbar computation --
        let needs_scrollbar = total_items > max_vis && max_vis > 0;
        let (thumb_top, thumb_size) = if needs_scrollbar {
            let ts = ((max_vis * max_vis) as f64 / total_items as f64)
                .round()
                .max(1.0) as usize;
            let tt = (self.viewport_offset as f64 * max_vis as f64 / total_items as f64).round()
                as usize;
            let tt = tt.min(max_vis.saturating_sub(ts));
            (tt, ts)
        } else {
            (0, 0)
        };

        // -- Entry rows with scrollbar --
        for i in 0..max_vis {
            // Scrollbar character
            let sb = if needs_scrollbar {
                let in_thumb = i >= thumb_top && i < thumb_top + thumb_size;
                if in_thumb {
                    format!("{ACTIVE_ACCENT}\u{2503}{RESET}")
                } else {
                    format!("{GRAY}\u{2502}{RESET}")
                }
            } else {
                " ".to_string()
            };

            let viewport_idx = self.viewport_offset + i;
            if viewport_idx < dl_len {
                let (name, number, desc) = self.display_entry(viewport_idx);
                let is_hl = viewport_idx == self.highlight_idx;

                let num_str = format!("{:>width$}", number, width = num_width);
                let name_pad = format!("{:<width$}", name, width = max_name_len);
                let marker = if is_hl { "\u{25b8}" } else { " " };

                if is_hl {
                    let hl_desc = if !desc.is_empty() {
                        format!("  {ACTIVE_ACCENT}{desc}{RESET}")
                    } else {
                        String::new()
                    };
                    buf.push_str(&format!(
                        "\x1b[{row};1H{sb} {ACTIVE_ACCENT}{BOLD}{marker} {num_str}  {name_pad}{RESET}{hl_desc}\x1b[K"
                    ));
                } else {
                    let desc_str = if !desc.is_empty() {
                        format!("  {GRAY}{desc}{RESET}")
                    } else {
                        String::new()
                    };
                    buf.push_str(&format!(
                        "\x1b[{row};1H{sb} {marker} {GRAY}{num_str}  {name_pad}{desc_str}{RESET}\x1b[K"
                    ));
                }
            } else {
                buf.push_str(&format!("\x1b[{row};1H{sb}\x1b[K"));
            }
            row += 1;
        }

        // -- Clear remaining rows between list and footer --
        let footer_row = th;
        while row < footer_row {
            buf.push_str(&format!("\x1b[{row};1H\x1b[K"));
            row += 1;
        }

        // -- Footer hint (last line) --
        buf.push_str(&format!(
            "\x1b[{th};1H{GRAY}#=select  type=search  \u{2191}\u{2193}=navigate  Esc=back  Ctrl+C=quit{RESET}\x1b[K"
        ));

        // Position cursor on prompt line
        let cursor_col = 2 + self.cursor_pos + 1; // "❯ " is 2 visible chars
        buf.push_str(&format!("\x1b[{prompt_row};{cursor_col}H"));

        let mut stdout = io::stdout();
        let _ = stdout.write_all(buf.as_bytes());
        let _ = stdout.flush();
    }

    fn ghost_text(&self) -> String {
        let dl_len = self.display_list_len();
        if dl_len > 0 && self.highlight_idx < dl_len {
            let (name, _, _) = self.display_entry(self.highlight_idx);
            return name.to_string();
        }
        String::new()
    }

    // -- Alternate screen --------------------------------------------------

    fn enter_alt_screen(&self) {
        let mut stdout = io::stdout();
        // Set terminal title
        let _ = write!(stdout, "\x1b]0;{}\x07", self.config.title);
        // Enter alt screen + clear (no Kitty protocol — crossterm handles key decoding)
        let _ = stdout.write_all(b"\x1b[?1049h\x1b[H\x1b[2J");
        let _ = stdout.flush();
        // Enable raw mode for crossterm event reading
        let _ = terminal::enable_raw_mode();
    }

    fn leave_alt_screen(&self) {
        let _ = terminal::disable_raw_mode();
        let mut stdout = io::stdout();
        // Leave alt screen
        let _ = stdout.write_all(b"\x1b[?1049l");
        let _ = stdout.flush();
    }
}

#[derive(Debug, PartialEq)]
enum KeyAction {
    Continue,
    Launch(usize), // index into config.entries
    Exit,
    Ignore,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crossterm::event::{KeyCode, KeyEvent, KeyEventKind, KeyEventState, KeyModifiers};

    // ── Helpers ──────────────────────────────────────────────────────────

    fn test_config(n: usize) -> LaunchLineConfig {
        LaunchLineConfig {
            title: "Test".to_string(),
            on_exit: "restart".to_string(),
            show_exit: true,
            clear_on_launch: false,
            ghost_text: false,
            numeric_trigger: true,
            entries: (1..=n)
                .map(|i| EntryConfig {
                    name: format!("Entry {i}"),
                    command: "test".to_string(),
                    args: vec![],
                    description: String::new(),
                    working_directory: None,
                    env: std::collections::HashMap::new(),
                })
                .collect(),
        }
    }

    fn named_config(names: &[&str]) -> LaunchLineConfig {
        LaunchLineConfig {
            title: "Test".to_string(),
            on_exit: "restart".to_string(),
            show_exit: true,
            clear_on_launch: false,
            ghost_text: false,
            numeric_trigger: true,
            entries: names
                .iter()
                .map(|name| EntryConfig {
                    name: name.to_string(),
                    command: "test".to_string(),
                    args: vec![],
                    description: String::new(),
                    working_directory: None,
                    env: std::collections::HashMap::new(),
                })
                .collect(),
        }
    }

    fn key(code: KeyCode, modifiers: KeyModifiers) -> KeyEvent {
        KeyEvent {
            code,
            modifiers,
            kind: KeyEventKind::Press,
            state: KeyEventState::NONE,
        }
    }

    fn plain(code: KeyCode) -> KeyEvent {
        key(code, KeyModifiers::NONE)
    }

    fn char_key(ch: char) -> KeyEvent {
        key(KeyCode::Char(ch), KeyModifiers::NONE)
    }

    fn ctrl(ch: char) -> KeyEvent {
        key(KeyCode::Char(ch), KeyModifiers::CONTROL)
    }

    fn alt(ch: char) -> KeyEvent {
        key(KeyCode::Char(ch), KeyModifiers::ALT)
    }

    fn ctrl_code(code: KeyCode) -> KeyEvent {
        key(code, KeyModifiers::CONTROL)
    }

    fn alt_code(code: KeyCode) -> KeyEvent {
        key(code, KeyModifiers::ALT)
    }

    fn set_query(ui: &mut LaunchLineUI, text: &str) {
        ui.query = text.to_string();
        ui.cursor_pos = text.len();
        ui.update_filter();
    }

    // ── Escape key ───────────────────────────────────────────────────────

    #[test]
    fn on_key_escape_empty_query_returns_exit() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(plain(KeyCode::Esc));

        assert_eq!(
            action,
            KeyAction::Exit,
            "Escape with empty query should exit, got {action:?}"
        );
    }

    #[test]
    fn on_key_escape_nonempty_query_clears_and_resets_cursor() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "hello");

        let action = ui.on_key(plain(KeyCode::Esc));

        assert_eq!(
            action,
            KeyAction::Continue,
            "Escape with active query should continue, got {action:?}"
        );
        assert_eq!(
            ui.query, "",
            "Escape should clear query, got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 0,
            "Escape should reset cursor to 0, got {}",
            ui.cursor_pos
        );
    }

    // ── Enter key ────────────────────────────────────────────────────────

    #[test]
    fn on_key_enter_highlighted_entry_returns_launch() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.highlight_idx = 1;

        let action = ui.on_key(plain(KeyCode::Enter));

        assert_eq!(
            action,
            KeyAction::Launch(1),
            "Enter on entry at index 1 should launch it, got {action:?}"
        );
    }

    #[test]
    fn on_key_enter_exit_entry_highlighted_returns_exit() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.highlight_idx = ui.display_list_len() - 1;

        let action = ui.on_key(plain(KeyCode::Enter));

        assert_eq!(
            action,
            KeyAction::Exit,
            "Enter on exit entry should exit, got {action:?}"
        );
    }

    #[test]
    fn on_key_enter_empty_display_list_returns_ignore() {
        let config = named_config(&["Alpha"]);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "zzz");
        assert_eq!(
            ui.display_list_len(),
            0,
            "Precondition: display list should be empty after non-matching filter"
        );

        let action = ui.on_key(plain(KeyCode::Enter));

        assert_eq!(
            action,
            KeyAction::Ignore,
            "Enter with empty display list should ignore, got {action:?}"
        );
    }

    // ── Arrow keys ───────────────────────────────────────────────────────

    #[test]
    fn on_key_up_from_first_item_wraps_to_last() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.highlight_idx = 0;
        let last = ui.display_list_len() - 1;

        ui.on_key(plain(KeyCode::Up));

        assert_eq!(
            ui.highlight_idx, last,
            "Up from first item should wrap to last (index {last}), got {}",
            ui.highlight_idx
        );
    }

    #[test]
    fn on_key_up_from_middle_moves_to_previous() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.highlight_idx = 2;

        ui.on_key(plain(KeyCode::Up));

        assert_eq!(
            ui.highlight_idx, 1,
            "Up from index 2 should move to 1, got {}",
            ui.highlight_idx
        );
    }

    #[test]
    fn on_key_down_from_last_item_wraps_to_first() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        let last = ui.display_list_len() - 1;
        ui.highlight_idx = last;

        ui.on_key(plain(KeyCode::Down));

        assert_eq!(
            ui.highlight_idx, 0,
            "Down from last item should wrap to 0, got {}",
            ui.highlight_idx
        );
    }

    #[test]
    fn on_key_down_from_middle_moves_to_next() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.highlight_idx = 1;

        ui.on_key(plain(KeyCode::Down));

        assert_eq!(
            ui.highlight_idx, 2,
            "Down from index 1 should move to 2, got {}",
            ui.highlight_idx
        );
    }

    #[test]
    fn on_key_up_empty_list_returns_continue() {
        let config = named_config(&["Alpha"]);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "zzz");

        let action = ui.on_key(plain(KeyCode::Up));

        assert_eq!(
            action,
            KeyAction::Continue,
            "Up with empty list should continue, got {action:?}"
        );
    }

    // ── Backspace ────────────────────────────────────────────────────────

    #[test]
    fn on_key_backspace_removes_char_before_cursor() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "abc");

        ui.on_key(plain(KeyCode::Backspace));

        assert_eq!(
            ui.query, "ab",
            "Backspace should remove last char, got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 2,
            "Cursor should be at 2 after backspace, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_backspace_cursor_in_middle_removes_before_cursor() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "abcd".to_string();
        ui.cursor_pos = 2;
        ui.update_filter();

        ui.on_key(plain(KeyCode::Backspace));

        assert_eq!(
            ui.query, "acd",
            "Backspace at pos 2 in 'abcd' should give 'acd', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 1,
            "Cursor should move from 2 to 1, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_backspace_empty_query_no_change() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(plain(KeyCode::Backspace));

        assert_eq!(
            action,
            KeyAction::Continue,
            "Backspace on empty query should continue, got {action:?}"
        );
        assert_eq!(ui.query, "", "Query should remain empty");
    }

    #[test]
    fn on_key_backspace_cursor_at_start_no_change() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "abc".to_string();
        ui.cursor_pos = 0;
        ui.update_filter();

        ui.on_key(plain(KeyCode::Backspace));

        assert_eq!(
            ui.query, "abc",
            "Backspace at cursor pos 0 should not change query, got {:?}",
            ui.query
        );
    }

    #[test]
    fn on_key_ctrl_backspace_deletes_word_backward() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "hello world");

        ui.on_key(ctrl_code(KeyCode::Backspace));

        assert_eq!(
            ui.query, "hello ",
            "Ctrl+Backspace should delete 'world', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 6,
            "Cursor should be at 6 after word delete, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_alt_backspace_deletes_word_backward() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "hello world");

        ui.on_key(alt_code(KeyCode::Backspace));

        assert_eq!(
            ui.query, "hello ",
            "Alt+Backspace should delete 'world', got {:?}",
            ui.query
        );
    }

    // ── Ctrl+U (kill backward to start) ──────────────────────────────────

    #[test]
    fn on_key_ctrl_u_cursor_in_middle_removes_before_cursor() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello world".to_string();
        ui.cursor_pos = 6;
        ui.update_filter();

        ui.on_key(ctrl('u'));

        assert_eq!(
            ui.query, "world",
            "Ctrl+U at pos 6 of 'hello world' should keep 'world', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 0,
            "Ctrl+U should reset cursor to 0, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_ctrl_u_cursor_at_end_clears_entire_query() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "hello");

        ui.on_key(ctrl('u'));

        assert_eq!(
            ui.query, "",
            "Ctrl+U at end should clear entire query, got {:?}",
            ui.query
        );
    }

    #[test]
    fn on_key_ctrl_u_empty_query_returns_continue() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(ctrl('u'));

        assert_eq!(
            action,
            KeyAction::Continue,
            "Ctrl+U on empty query should continue, got {action:?}"
        );
    }

    // ── Ctrl+K (kill forward to end) ─────────────────────────────────────

    #[test]
    fn on_key_ctrl_k_cursor_in_middle_removes_after_cursor() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello world".to_string();
        ui.cursor_pos = 5;
        ui.update_filter();

        ui.on_key(ctrl('k'));

        assert_eq!(
            ui.query, "hello",
            "Ctrl+K at pos 5 of 'hello world' should keep 'hello', got {:?}",
            ui.query
        );
    }

    #[test]
    fn on_key_ctrl_k_cursor_at_end_no_change() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "hello");

        let action = ui.on_key(ctrl('k'));

        assert_eq!(
            action,
            KeyAction::Continue,
            "Ctrl+K at end should continue, got {action:?}"
        );
        assert_eq!(
            ui.query, "hello",
            "Ctrl+K at end should not change query, got {:?}",
            ui.query
        );
    }

    // ── Ctrl+W (delete word backward) ────────────────────────────────────

    #[test]
    fn on_key_ctrl_w_deletes_word_before_cursor() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "hello world");

        ui.on_key(ctrl('w'));

        assert_eq!(
            ui.query, "hello ",
            "Ctrl+W should delete 'world' backward, got {:?}",
            ui.query
        );
    }

    // ── Cursor movement (Ctrl+A, E, B, F) ────────────────────────────────

    #[test]
    fn on_key_ctrl_a_moves_cursor_to_start() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "hello");

        ui.on_key(ctrl('a'));

        assert_eq!(
            ui.cursor_pos, 0,
            "Ctrl+A should move cursor to 0, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_ctrl_e_moves_cursor_to_end() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello".to_string();
        ui.cursor_pos = 0;
        ui.update_filter();

        ui.on_key(ctrl('e'));

        assert_eq!(
            ui.cursor_pos, 5,
            "Ctrl+E should move cursor to end (5), got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_ctrl_b_moves_cursor_left() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "abc");

        ui.on_key(ctrl('b'));

        assert_eq!(
            ui.cursor_pos, 2,
            "Ctrl+B from pos 3 should move to 2, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_ctrl_b_at_start_stays_at_zero() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "abc".to_string();
        ui.cursor_pos = 0;
        ui.update_filter();

        ui.on_key(ctrl('b'));

        assert_eq!(
            ui.cursor_pos, 0,
            "Ctrl+B at pos 0 should stay at 0, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_ctrl_f_moves_cursor_right() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "abc".to_string();
        ui.cursor_pos = 0;
        ui.update_filter();

        ui.on_key(ctrl('f'));

        assert_eq!(
            ui.cursor_pos, 1,
            "Ctrl+F from pos 0 should move to 1, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_ctrl_f_at_end_stays_at_end() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "abc");

        ui.on_key(ctrl('f'));

        assert_eq!(
            ui.cursor_pos, 3,
            "Ctrl+F at end should stay at 3, got {}",
            ui.cursor_pos
        );
    }

    // ── Ctrl+D (delete forward / exit on empty) ──────────────────────────

    #[test]
    fn on_key_ctrl_d_deletes_char_at_cursor() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "abc".to_string();
        ui.cursor_pos = 1;
        ui.update_filter();

        ui.on_key(ctrl('d'));

        assert_eq!(
            ui.query, "ac",
            "Ctrl+D at pos 1 of 'abc' should delete 'b', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 1,
            "Cursor should stay at 1 after forward delete, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_ctrl_d_empty_query_returns_exit() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(ctrl('d'));

        assert_eq!(
            action,
            KeyAction::Exit,
            "Ctrl+D on empty query should exit, got {action:?}"
        );
    }

    #[test]
    fn on_key_ctrl_d_cursor_at_end_returns_continue() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "abc");

        let action = ui.on_key(ctrl('d'));

        assert_eq!(
            action,
            KeyAction::Continue,
            "Ctrl+D at end of non-empty query should continue, got {action:?}"
        );
        assert_eq!(
            ui.query, "abc",
            "Query should be unchanged when Ctrl+D at end, got {:?}",
            ui.query
        );
    }

    // ── Ctrl+H (backspace equivalent) ────────────────────────────────────

    #[test]
    fn on_key_ctrl_h_removes_char_before_cursor() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "abc");

        ui.on_key(ctrl('h'));

        assert_eq!(
            ui.query, "ab",
            "Ctrl+H should act as backspace and remove 'c', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 2,
            "Cursor should move to 2 after Ctrl+H, got {}",
            ui.cursor_pos
        );
    }

    // ── Ctrl+C ───────────────────────────────────────────────────────────

    #[test]
    fn on_key_ctrl_c_returns_exit() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(ctrl('c'));

        assert_eq!(
            action,
            KeyAction::Exit,
            "Ctrl+C should always exit, got {action:?}"
        );
    }

    #[test]
    fn on_key_ctrl_c_with_active_query_returns_exit() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "hello");

        let action = ui.on_key(ctrl('c'));

        assert_eq!(
            action,
            KeyAction::Exit,
            "Ctrl+C should exit even with active query, got {action:?}"
        );
    }

    // ── Alt key word operations ──────────────────────────────────────────

    #[test]
    fn on_key_alt_b_jumps_to_previous_word_boundary() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "hello world");

        ui.on_key(alt('b'));

        assert_eq!(
            ui.cursor_pos, 6,
            "Alt+B from end of 'hello world' should jump to pos 6, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_alt_b_from_middle_of_word_jumps_to_word_start() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello world".to_string();
        ui.cursor_pos = 8;
        ui.update_filter();

        ui.on_key(alt('b'));

        assert_eq!(
            ui.cursor_pos, 6,
            "Alt+B from mid-word should jump to word start at 6, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_alt_f_jumps_to_next_word_boundary() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello world".to_string();
        ui.cursor_pos = 0;
        ui.update_filter();

        ui.on_key(alt('f'));

        assert_eq!(
            ui.cursor_pos, 6,
            "Alt+F from start of 'hello world' should jump to 6, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_alt_d_deletes_word_forward() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello world".to_string();
        ui.cursor_pos = 0;
        ui.update_filter();

        ui.on_key(alt('d'));

        assert_eq!(
            ui.query, "world",
            "Alt+D at start of 'hello world' should delete 'hello ', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 0,
            "Cursor should stay at 0 after Alt+D, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_alt_d_at_end_no_change() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "hello");

        let action = ui.on_key(alt('d'));

        assert_eq!(
            action,
            KeyAction::Continue,
            "Alt+D at end should continue, got {action:?}"
        );
        assert_eq!(
            ui.query, "hello",
            "Alt+D at end should not change query, got {:?}",
            ui.query
        );
    }

    // ── Character input ──────────────────────────────────────────────────

    #[test]
    fn on_key_char_inserts_at_cursor_and_advances() {
        let config = named_config(&["Alpha", "Bravo", "Charlie"]);
        let mut ui = LaunchLineUI::new(&config);

        ui.on_key(char_key('a'));

        assert_eq!(
            ui.query, "a",
            "Typing 'a' should set query to 'a', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 1,
            "Cursor should advance to 1 after typing, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_char_inserts_at_middle_position() {
        let config = named_config(&["Alpha", "Bravo", "Charlie"]);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "ac".to_string();
        ui.cursor_pos = 1;
        ui.update_filter();

        ui.on_key(char_key('b'));

        assert_eq!(
            ui.query, "abc",
            "Typing 'b' at pos 1 of 'ac' should give 'abc', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 2,
            "Cursor should advance to 2, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn on_key_digit_zero_empty_query_show_exit_returns_exit() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(char_key('0'));

        assert_eq!(
            action,
            KeyAction::Exit,
            "Digit '0' with empty query and show_exit=true should exit, got {action:?}"
        );
    }

    #[test]
    fn on_key_digit_zero_empty_query_no_show_exit_returns_ignore() {
        let mut config = test_config(3);
        config.show_exit = false;
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(char_key('0'));

        assert_eq!(
            action,
            KeyAction::Ignore,
            "Digit '0' with show_exit=false should be ignored (no entry 0), got {action:?}"
        );
    }

    #[test]
    fn on_key_digit_numeric_trigger_with_few_entries_launches() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(char_key('2'));

        assert_eq!(
            action,
            KeyAction::Launch(1),
            "Digit '2' should launch entry at index 1 (0-based), got {action:?}"
        );
    }

    #[test]
    fn on_key_digit_numeric_trigger_out_of_range_returns_ignore() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(char_key('5'));

        assert_eq!(
            action,
            KeyAction::Ignore,
            "Digit '5' with only 3 entries should be ignored, got {action:?}"
        );
    }

    #[test]
    fn on_key_digit_numeric_trigger_disabled_inserts_digit() {
        let mut config = test_config(3);
        config.numeric_trigger = false;
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(char_key('2'));

        assert_eq!(
            action,
            KeyAction::Continue,
            "Digit with numeric_trigger=false should insert and continue, got {action:?}"
        );
        assert_eq!(
            ui.query, "2",
            "Digit should be inserted into query, got {:?}",
            ui.query
        );
    }

    #[test]
    fn on_key_digit_auto_launch_on_single_numeric_match() {
        let config = test_config(12); // >9 entries, so immediate launch is skipped
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(char_key('3'));

        assert_eq!(
            action,
            KeyAction::Launch(2),
            "Digit '3' with 12 entries should auto-launch entry at index 2, got {action:?}"
        );
    }

    #[test]
    fn on_key_digit_no_auto_launch_with_multiple_matches() {
        let config = test_config(12);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(char_key('1'));

        assert_eq!(
            action,
            KeyAction::Continue,
            "Digit '1' matching entries 1,10,11,12 should continue (no auto-launch), got {action:?}"
        );
    }

    // ── Unknown/unhandled keys ───────────────────────────────────────────

    #[test]
    fn on_key_unknown_key_returns_ignore() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(plain(KeyCode::F(1)));

        assert_eq!(
            action,
            KeyAction::Ignore,
            "Unhandled key F1 should return Ignore, got {action:?}"
        );
    }

    #[test]
    fn on_key_ctrl_with_unhandled_char_returns_ignore() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        let action = ui.on_key(ctrl('z'));

        assert_eq!(
            action,
            KeyAction::Ignore,
            "Ctrl+Z (unhandled) should return Ignore, got {action:?}"
        );
    }

    // ── Word boundary helpers ────────────────────────────────────────────

    #[test]
    fn word_boundary_back_multiple_words_stops_at_word_start() {
        let config = test_config(1);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello world".to_string();
        ui.cursor_pos = 11;

        let pos = ui.word_boundary_back();

        assert_eq!(
            pos, 6,
            "word_boundary_back from end of 'hello world' should return 6, got {pos}"
        );
    }

    #[test]
    fn word_boundary_back_at_start_returns_zero() {
        let config = test_config(1);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello".to_string();
        ui.cursor_pos = 0;

        let pos = ui.word_boundary_back();

        assert_eq!(
            pos, 0,
            "word_boundary_back at start should return 0, got {pos}"
        );
    }

    #[test]
    fn word_boundary_back_skips_trailing_spaces() {
        let config = test_config(1);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello   world".to_string();
        ui.cursor_pos = 8;

        let pos = ui.word_boundary_back();

        assert_eq!(
            pos, 0,
            "word_boundary_back should skip spaces then 'hello', landing at 0, got {pos}"
        );
    }

    #[test]
    fn word_boundary_forward_multiple_words_stops_past_word() {
        let config = test_config(1);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello world".to_string();
        ui.cursor_pos = 0;

        let pos = ui.word_boundary_forward();

        assert_eq!(
            pos, 6,
            "word_boundary_forward from 0 in 'hello world' should return 6, got {pos}"
        );
    }

    #[test]
    fn word_boundary_forward_at_end_returns_length() {
        let config = test_config(1);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello".to_string();
        ui.cursor_pos = 5;

        let pos = ui.word_boundary_forward();

        assert_eq!(
            pos, 5,
            "word_boundary_forward at end should return length (5), got {pos}"
        );
    }

    #[test]
    fn delete_word_back_removes_word_and_updates_cursor() {
        let config = test_config(1);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello world".to_string();
        ui.cursor_pos = 11;

        ui.delete_word_back();

        assert_eq!(
            ui.query, "hello ",
            "delete_word_back should remove 'world', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 6,
            "cursor should be at 6 after word delete, got {}",
            ui.cursor_pos
        );
    }

    #[test]
    fn delete_word_back_at_start_no_change() {
        let config = test_config(1);
        let mut ui = LaunchLineUI::new(&config);
        ui.query = "hello".to_string();
        ui.cursor_pos = 0;

        ui.delete_word_back();

        assert_eq!(
            ui.query, "hello",
            "delete_word_back at start should not change query, got {:?}",
            ui.query
        );
    }

    // ── Filter / update_filter ───────────────────────────────────────────

    #[test]
    fn update_filter_empty_query_shows_all_entries() {
        let config = test_config(5);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "x");
        set_query(&mut ui, "");

        assert_eq!(
            ui.visible.len(),
            5,
            "Empty query should show all 5 entries, got {}",
            ui.visible.len()
        );
        assert!(
            ui.exit_visible,
            "Exit entry should be visible with empty query"
        );
    }

    #[test]
    fn update_filter_fuzzy_match_filters_entries() {
        let config = named_config(&["Firefox", "Chrome", "Safari"]);
        let mut ui = LaunchLineUI::new(&config);

        set_query(&mut ui, "fire");

        assert_eq!(
            ui.visible.len(),
            1,
            "Query 'fire' should match only Firefox, got {} matches",
            ui.visible.len()
        );
        assert_eq!(
            ui.visible[0], 0,
            "Matched entry should be index 0 (Firefox), got {}",
            ui.visible[0]
        );
    }

    #[test]
    fn update_filter_no_match_shows_empty_list() {
        let config = named_config(&["Alpha", "Bravo", "Charlie"]);
        let mut ui = LaunchLineUI::new(&config);

        set_query(&mut ui, "xyz");

        assert_eq!(
            ui.visible.len(),
            0,
            "Query 'xyz' should match nothing, got {} matches",
            ui.visible.len()
        );
        assert!(
            !ui.exit_visible,
            "Exit entry should not be visible when 'xyz' doesn't match 'Exit'"
        );
    }

    #[test]
    fn update_filter_numeric_query_matches_by_entry_number() {
        let config = test_config(3);
        let mut ui = LaunchLineUI::new(&config);

        set_query(&mut ui, "2");

        assert_eq!(
            ui.visible.len(),
            1,
            "Numeric query '2' should match entry #2 only, got {} matches",
            ui.visible.len()
        );
        assert_eq!(
            ui.visible[0], 1,
            "Matched entry should be index 1 (Entry 2), got {}",
            ui.visible[0]
        );
    }

    #[test]
    fn update_filter_resets_highlight_and_viewport() {
        let config = test_config(5);
        let mut ui = LaunchLineUI::new(&config);
        ui.highlight_idx = 3;
        ui.viewport_offset = 2;

        set_query(&mut ui, "e");

        assert_eq!(
            ui.highlight_idx, 0,
            "Filter should reset highlight to 0, got {}",
            ui.highlight_idx
        );
        assert_eq!(
            ui.viewport_offset, 0,
            "Filter should reset viewport to 0, got {}",
            ui.viewport_offset
        );
    }

    // ── Display list helpers ─────────────────────────────────────────────

    #[test]
    fn display_list_len_show_exit_true_includes_exit_entry() {
        let config = test_config(3);
        let ui = LaunchLineUI::new(&config);

        assert_eq!(
            ui.display_list_len(),
            4,
            "3 entries + exit = 4 display items, got {}",
            ui.display_list_len()
        );
    }

    #[test]
    fn display_list_len_show_exit_false_excludes_exit_entry() {
        let mut config = test_config(3);
        config.show_exit = false;
        let ui = LaunchLineUI::new(&config);

        assert_eq!(
            ui.display_list_len(),
            3,
            "3 entries without exit = 3 display items, got {}",
            ui.display_list_len()
        );
    }

    #[test]
    fn is_exit_entry_beyond_visible_returns_true() {
        let config = test_config(3);
        let ui = LaunchLineUI::new(&config);
        let exit_idx = ui.visible.len();

        assert!(
            ui.is_exit_entry(exit_idx),
            "Index {exit_idx} (past visible entries) should be the exit entry"
        );
    }

    #[test]
    fn is_exit_entry_regular_entry_returns_false() {
        let config = test_config(3);
        let ui = LaunchLineUI::new(&config);

        assert!(!ui.is_exit_entry(0), "Index 0 should not be the exit entry");
    }

    // ── Edge cases / integration ─────────────────────────────────────────

    #[test]
    fn on_key_single_entry_navigation_wraps_correctly() {
        let config = test_config(1);
        let mut ui = LaunchLineUI::new(&config);
        assert_eq!(ui.highlight_idx, 0);

        ui.on_key(plain(KeyCode::Down));
        assert_eq!(
            ui.highlight_idx, 1,
            "Down from 0 with 2 items should go to 1, got {}",
            ui.highlight_idx
        );

        ui.on_key(plain(KeyCode::Down));
        assert_eq!(
            ui.highlight_idx, 0,
            "Down from 1 with 2 items should wrap to 0, got {}",
            ui.highlight_idx
        );
    }

    #[test]
    fn on_key_multiple_chars_build_query_incrementally() {
        let config = named_config(&["Alpha", "Bravo", "Charlie"]);
        let mut ui = LaunchLineUI::new(&config);

        ui.on_key(char_key('c'));
        ui.on_key(char_key('h'));

        assert_eq!(
            ui.query, "ch",
            "Typing 'c' then 'h' should give 'ch', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 2,
            "Cursor should be at 2, got {}",
            ui.cursor_pos
        );
        assert_eq!(
            ui.visible.len(),
            1,
            "Query 'ch' should match only 'Charlie', got {} matches",
            ui.visible.len()
        );
    }

    #[test]
    fn on_key_backspace_then_type_restores_query() {
        let config = named_config(&["Alpha", "Bravo", "Charlie"]);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "ab");

        ui.on_key(plain(KeyCode::Backspace));
        assert_eq!(ui.query, "a", "After backspace, query should be 'a'");

        ui.on_key(char_key('l'));
        assert_eq!(
            ui.query, "al",
            "After typing 'l', query should be 'al', got {:?}",
            ui.query
        );
    }

    #[test]
    fn on_key_ctrl_a_then_type_inserts_at_start() {
        let config = named_config(&["Alpha"]);
        let mut ui = LaunchLineUI::new(&config);
        set_query(&mut ui, "bc");

        ui.on_key(ctrl('a'));
        ui.on_key(char_key('a'));

        assert_eq!(
            ui.query, "abc",
            "Ctrl+A then 'a' should insert at start: 'abc', got {:?}",
            ui.query
        );
        assert_eq!(
            ui.cursor_pos, 1,
            "Cursor should be at 1, got {}",
            ui.cursor_pos
        );
    }
}
