//! Public API, real-child execution, and CLI contracts.
use launchline::{
    config::{ConfigLoader, EntryConfig, LaunchLineConfig},
    fuzzy::FuzzyMatcher,
    runner::EntryRunner,
};
use std::{
    collections::HashMap,
    fs,
    path::PathBuf,
    process::Command,
    sync::atomic::{AtomicUsize, Ordering},
};

static NEXT: AtomicUsize = AtomicUsize::new(0);
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "launchline-contract-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).expect("unique test directory");
        Self(path)
    }
    fn config(&self, source: &str) -> PathBuf {
        let path = self.0.join("config.toml");
        fs::write(&path, source).expect("write fixture");
        path
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).expect("clean own fixture directory");
    }
}

#[test]
fn invalid_config_types_and_control_characters_are_rejected() {
    for source in [
        "settings = 1",
        "[settings]\nshow_exit = 'yes'",
        "[settings]\ntitle = 123",
        "[[entries]]\nname = 'x'\ncommand = 12",
        "[[entries]]\nname = 'x'\ncommand = 'x'\nargs = [1]",
        "[[entries]]\nname = 'x'\ncommand = 'x'\nenv = {A = false}",
        "[[entries]]\nname = \"x\\u001b]0;bad\"\ncommand = 'x'",
        "[[entries]]\nname = 'x'\ncommand = 'x'\nenv = {'A=B' = 'x'}",
    ] {
        let fixture = Fixture::new();
        assert!(
            ConfigLoader::load(&fixture.config(source)).is_err(),
            "must reject {source}"
        );
    }
}

#[test]
fn exact_search_scores_cover_unicode_and_long_tail() {
    for (query, candidate, expected) in [
        ("", "", Some(0)),
        ("abc", "abc", Some(10)),
        ("ab", "a-b", Some(8)),
        ("ab", "ba", None),
        ("é", "Éclair", Some(4)),
        ("猫", "猫工具", Some(4)),
        ("i\u{307}", "İ", Some(7)),
    ] {
        assert_eq!(
            FuzzyMatcher::score(query, candidate),
            expected,
            "query={query} candidate={candidate}"
        );
    }
    assert_eq!(
        FuzzyMatcher::score("abc", &format!("abc{}", "x".repeat(4096))),
        Some(10)
    );
}

#[test]
fn cli_rejects_invalid_log_level_and_reports_missing_config() {
    let executable = env!("CARGO_BIN_EXE_launchline");
    let result = Command::new(executable)
        .args(["--log-level", "INVALID"])
        .output()
        .unwrap();
    assert_eq!(
        result.status.code(),
        Some(2),
        "invalid CLI choice must return 2"
    );
    let fixture = Fixture::new();
    let result = Command::new(executable)
        .arg("--config-path")
        .arg("--config")
        .arg(fixture.0.join("missing.toml"))
        .output()
        .unwrap();
    assert_eq!(result.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&result.stderr).contains("Config file not found"));
}

#[test]
fn real_child_receives_literal_args_environment_cwd_and_exit() {
    let fixture = Fixture::new();
    let output = fixture.0.join("result.txt");
    let executable = fixture
        .0
        .join(if cfg!(windows) { "probe.exe" } else { "probe" });
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/process_probe.rs");
    let compilation = Command::new("rustc")
        .arg("--edition=2024")
        .arg(source)
        .arg("-o")
        .arg(&executable)
        .output()
        .unwrap();
    assert!(
        compilation.status.success(),
        "Native probe compilation failed: {}",
        String::from_utf8_lossy(&compilation.stderr)
    );
    let command = executable.to_string_lossy().into_owned();
    let args = vec![
        output.to_string_lossy().into_owned(),
        "a b".into(),
        "&literal".into(),
        "猫".into(),
    ];
    let entry = EntryConfig {
        name: "child".into(),
        command,
        args,
        description: String::new(),
        working_directory: Some(fixture.0.clone()),
        env: HashMap::from([("LL_CONTRACT".into(), "a b & literal".into())]),
    };
    let config = LaunchLineConfig {
        entries: vec![entry.clone()],
        title: "test".into(),
        on_exit: "exit".into(),
        show_exit: true,
        clear_on_launch: false,
        ghost_text: true,
        numeric_trigger: true,
    };
    assert_eq!(EntryRunner::new(&config).launch(&entry).unwrap(), 7);
    assert_eq!(
        fs::read_to_string(output).unwrap(),
        format!("a b\n&literal\n猫|a b & literal|{}", fixture.0.display())
    );
    assert!(
        std::env::var_os("LL_CONTRACT").is_none(),
        "parent environment must be unchanged"
    );
}

#[test]
fn existing_file_is_not_a_working_directory() {
    let fixture = Fixture::new();
    let regular_file = fixture.0.join("regular-file");
    fs::write(&regular_file, "fixture").unwrap();
    let source = format!(
        "[[entries]]\nname='safe'\ncommand='unused'\nworking_directory={:?}",
        regular_file.to_string_lossy()
    );
    let config = ConfigLoader::load(&fixture.config(&source)).unwrap();
    assert!(
        config.entries[0].working_directory.is_none(),
        "Regular files must fall back to inherited cwd"
    );
}

#[test]
fn baseline_score_corpus_is_preserved() {
    for line in include_str!("fixtures/fuzzy.tsv").lines() {
        let fields: Vec<_> = line.split('\t').collect();
        let expected: i32 = fields[2].parse().unwrap();
        let expected = if expected == -1 { None } else { Some(expected) };
        assert_eq!(
            FuzzyMatcher::score(fields[0], fields[1]),
            expected,
            "query={} candidate={}",
            fields[0],
            fields[1]
        );
    }
}

#[cfg(unix)]
#[test]
fn child_sigterm_uses_shell_status() {
    let entry = EntryConfig {
        name: "signal fixture".into(),
        command: "sh".into(),
        args: vec!["-c".into(), "kill -TERM $$".into()],
        description: String::new(),
        working_directory: None,
        env: HashMap::new(),
    };
    let config = LaunchLineConfig {
        entries: vec![entry.clone()],
        title: "test".into(),
        on_exit: "exit".into(),
        show_exit: true,
        clear_on_launch: false,
        ghost_text: true,
        numeric_trigger: true,
    };
    assert_eq!(
        EntryRunner::new(&config).launch(&entry).unwrap(),
        143,
        "Only the fixture shell terminates itself"
    );
}
