//! Shared menu declaration, cached lifecycle and actual provider execution tests.
use launchline::{
    config::{ConfigLoader, EntryConfig, LaunchLineConfig, ProviderConfig},
    menus::{MenuSession, same_entry},
    providers::{MenuProvider, Provider, ProviderError},
};
use std::{
    cell::Cell,
    collections::VecDeque,
    path::{Path, PathBuf},
    process::Command,
    rc::Rc,
    sync::{Arc, OnceLock, atomic::AtomicBool},
};

fn entry(value: serde_json::Value) -> EntryConfig {
    ConfigLoader::parse_entries(serde_json::json!([value]), 0)
        .unwrap()
        .remove(0)
}
fn config(entries: Vec<EntryConfig>) -> LaunchLineConfig {
    LaunchLineConfig {
        entries,
        title: "Root".into(),
        on_exit: "restart".into(),
        show_exit: true,
        clear_on_launch: false,
        ghost_text: true,
        numeric_trigger: true,
        provider: None,
        refresh_on_return: false,
    }
}
fn provider() -> ProviderConfig {
    ProviderConfig {
        entry: entry(serde_json::json!({"name":"p", "command":"provider"})),
        timeout_seconds: 10,
    }
}
struct RecordedProvider {
    calls: Rc<Cell<usize>>,
    results: VecDeque<Result<Vec<EntryConfig>, ProviderError>>,
}
impl Provider for RecordedProvider {
    fn resolve(
        &mut self,
        _provider: &ProviderConfig,
        depth: usize,
    ) -> Result<Vec<EntryConfig>, ProviderError> {
        assert!(depth < 16, "Provider nesting must be bounded");
        self.calls.set(self.calls.get() + 1);
        self.results
            .pop_front()
            .expect("Only expected provider calls may occur")
    }
}

#[test]
fn child_provider_is_lazy_and_cached_across_reentry() {
    let child = entry(
        serde_json::json!({"id":"projects", "name":"Projects", "menu":{"provider":{"command":"provider"}}}),
    );
    let leaf = entry(serde_json::json!({"name":"Safe", "command":"unused"}));
    let calls = Rc::new(Cell::new(0));
    let boundary = RecordedProvider {
        calls: calls.clone(),
        results: VecDeque::from([Ok(vec![leaf.clone()])]),
    };
    let mut session = MenuSession::new(&config(vec![child.clone()]), boundary);
    session.ensure_loaded().unwrap();
    assert_eq!(
        calls.get(),
        0,
        "Parent load must not execute child providers"
    );
    session.open(&child).unwrap();
    assert_eq!(
        session.current().entries,
        vec![leaf],
        "Selected child must show generated entries"
    );
    assert!(session.back().unwrap(), "Back must retain the parent");
    session.open(&child).unwrap();
    assert_eq!(calls.get(), 1, "Default session cache must survive reentry");
}

#[test]
fn parent_refresh_invalidates_changed_children_and_preserves_id() {
    let previous = entry(serde_json::json!({"id":"projects", "name":"Projects", "menu":{}}));
    let current =
        entry(serde_json::json!({"id":"projects", "name":"Renamed", "menu":{"title":"Changed"}}));
    let mut root = config(vec![]);
    root.provider = Some(Box::new(provider()));
    root.refresh_on_return = true;
    let calls = Rc::new(Cell::new(0));
    let mut session = MenuSession::new(
        &root,
        RecordedProvider {
            calls: calls.clone(),
            results: VecDeque::from([Ok(vec![previous.clone()]), Ok(vec![current.clone()])]),
        },
    );
    session.ensure_loaded().unwrap();
    session.open(&previous).unwrap();
    session.back().unwrap();
    assert_eq!(
        session.current().entries,
        vec![current.clone()],
        "Return policy must regenerate parent"
    );
    assert!(
        session.current().children.is_empty(),
        "Changed declarations must discard cached descendants"
    );
    assert!(
        same_entry(&previous, &current),
        "Stable ids must preserve selection across rename"
    );
    assert_eq!(
        calls.get(),
        2,
        "Refresh must run once per configured return"
    );
}

#[test]
fn failure_retains_snapshot_without_automatic_retry_and_empty_retry_succeeds() {
    let leaf = entry(serde_json::json!({"name":"Safe", "command":"unused"}));
    let mut root = config(vec![]);
    root.provider = Some(Box::new(provider()));
    let calls = Rc::new(Cell::new(0));
    let mut session = MenuSession::new(
        &root,
        RecordedProvider {
            calls: calls.clone(),
            results: VecDeque::from([
                Ok(vec![leaf.clone()]),
                Err(ProviderError::Failure("failed".into())),
                Ok(vec![]),
            ]),
        },
    );
    session.ensure_loaded().unwrap();
    assert!(
        !session.refresh().unwrap(),
        "Failed refresh must report failure"
    );
    assert_eq!(
        session.current().entries,
        vec![leaf],
        "Last good snapshot must survive failure"
    );
    session.ensure_loaded().unwrap();
    assert_eq!(calls.get(), 2, "Failure must wait for explicit retry");
    assert!(session.refresh().unwrap(), "Explicit retry must recover");
    assert!(
        session.current().entries.is_empty(),
        "Successful empty snapshot is valid"
    );
    assert!(
        session.current().error.is_none(),
        "Successful retry must clear error state"
    );
    assert!(!session.back().unwrap(), "Back at root must not underflow");
}

fn native_probe() -> &'static Path {
    static PROBE: OnceLock<PathBuf> = OnceLock::new();
    PROBE.get_or_init(|| {
        let directory = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let output_directory = directory.join("target");
        std::fs::create_dir_all(&output_directory)
            .expect("Provider probe output directory must be available in extracted crates");
        let executable = output_directory.join(if cfg!(windows) {
            "menu-provider-probe.exe"
        } else {
            "menu-provider-probe"
        });
        let result = Command::new("rustc")
            .arg("--edition=2024")
            .arg(directory.join("tests/fixtures/menu_provider_probe.rs"))
            .arg("-o")
            .arg(&executable)
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "Native probe must compile: {}",
            String::from_utf8_lossy(&result.stderr)
        );
        executable
    })
}

#[test]
fn actual_provider_boundaries_reject_failures_and_accept_closed_stdin() {
    let mut service = MenuProvider::new(Arc::new(AtomicBool::new(false)));
    for (mode, expected) in [
        ("success", true),
        ("empty", true),
        ("nonzero", false),
        ("malformed", false),
        ("nonutf8", false),
        ("oversize", false),
        ("timeout", false),
    ] {
        let mut declaration = provider();
        declaration.entry.command = native_probe().to_string_lossy().into_owned();
        declaration.entry.args = vec![mode.into()];
        declaration.timeout_seconds = 1;
        let result = service.resolve(&declaration, 0);
        assert_eq!(
            result.is_ok(),
            expected,
            "Unexpected provider mode {mode}: {result:?}"
        );
    }
}

#[test]
fn json_null_optional_fields_are_not_silently_defaulted() {
    for field in [
        "args",
        "env",
        "description",
        "id",
        "menu",
        "working_directory",
    ] {
        let mut value = serde_json::json!({"name":"Safe", "command":"unused"});
        value[field] = serde_json::Value::Null;
        assert!(
            ConfigLoader::parse_entries(serde_json::json!([value]), 0).is_err(),
            "Declared {field}=null must fail exactly like Python"
        );
    }
}

#[test]
fn check_config_validates_provider_declaration_without_execution() {
    let path =
        std::env::temp_dir().join(format!("launchline-menu-check-{}.toml", std::process::id()));
    std::fs::write(
        &path,
        "[provider]\ncommand='nonexistent-provider-command-91c7'",
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_launchline"))
        .args(["--check-config", "--config"])
        .arg(&path)
        .output()
        .unwrap();
    std::fs::remove_file(path).unwrap();
    assert!(
        output.status.success(),
        "Config validation must not execute providers: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn shared_static_and_provider_fixture_contract_matches_python() {
    let cases: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/menu-contract.json")).unwrap();
    let path = std::env::temp_dir().join(format!(
        "launchline-menu-fixtures-{}.toml",
        std::process::id()
    ));
    for case in cases["static"].as_array().unwrap() {
        std::fs::write(&path, case["toml"].as_str().unwrap()).unwrap();
        assert_eq!(
            ConfigLoader::load(&path).is_ok(),
            case["valid"].as_bool().unwrap(),
            "Static fixture {} must agree",
            case["name"]
        );
    }
    std::fs::remove_file(path).unwrap();
    let mut service = MenuProvider::new(Arc::new(AtomicBool::new(false)));
    for case in cases["providers"].as_array().unwrap() {
        let mut declaration = provider();
        declaration.entry.command = native_probe().to_string_lossy().into_owned();
        declaration.entry.args = vec!["json".into(), case["json"].as_str().unwrap().into()];
        let result = service.resolve(&declaration, 0);
        assert_eq!(
            result.is_ok(),
            case["valid"].as_bool().unwrap(),
            "Provider fixture {} must agree: {result:?}",
            case["name"]
        );
    }
}

#[test]
fn lru_budget_evicts_old_inactive_nodes_without_touching_recent_snapshots() {
    let entries: Vec<_> = (0..130).map(|index| entry(serde_json::json!({"id":index.to_string(), "name":index.to_string(), "menu":{"provider":{"command":"provider"}}}))).collect();
    let calls = Rc::new(Cell::new(0));
    let boundary = RecordedProvider {
        calls: calls.clone(),
        results: (0..131).map(|_| Ok(vec![])).collect(),
    };
    let mut session = MenuSession::new(&config(entries.clone()), boundary);
    session.ensure_loaded().unwrap();
    for item in &entries {
        session.open(item).unwrap();
        session.back().unwrap();
    }
    session.open(&entries[129]).unwrap();
    session.back().unwrap();
    assert_eq!(
        calls.get(),
        130,
        "Recent snapshots must remain cached within the 128-menu budget"
    );
    session.open(&entries[0]).unwrap();
    assert_eq!(
        calls.get(),
        131,
        "Old snapshots regenerate only on explicit reentry after eviction"
    );
}

#[test]
fn large_static_menus_remain_compatible_but_generated_snapshots_are_bounded() {
    let path = std::env::temp_dir().join(format!(
        "launchline-large-static-{}.toml",
        std::process::id()
    ));
    std::fs::write(
        &path,
        "[[entries]]\nname=\"tool\"\ncommand=\"unused\"\n".repeat(1001),
    )
    .unwrap();
    let loaded = ConfigLoader::load(&path);
    std::fs::remove_file(&path).unwrap();
    assert_eq!(loaded.unwrap().entries.len(), 1001);
    let entries = serde_json::Value::Array(vec![
        serde_json::json!({"name":"tool","command":"unused"});
        1001
    ]);
    assert!(ConfigLoader::parse_entries(entries.clone(), 0).is_err());
    assert!(
        ConfigLoader::parse_entries(
            serde_json::json!([{"name":"child","menu":{"entries":entries}}]),
            0
        )
        .is_err()
    );
}
