//! Harmless actual executable for provider boundary and descendant cleanup tests.
use std::io::{Read, Write};
fn main() {
    let arguments: Vec<String> = std::env::args().collect();
    match arguments.get(1).map(String::as_str).unwrap_or("success") {
        "success" => {
            let mut input = String::new();
            std::io::stdin().read_to_string(&mut input).unwrap();
            assert!(input.is_empty(), "Provider stdin must be closed");
            std::io::stdout().write_all(br#"{"entries":[{"id":"tool","name":"Safe tool","command":"unused"}]}"#).unwrap();
        }
        "json" => std::io::stdout().write_all(arguments[2].as_bytes()).unwrap(),
        "empty" => std::io::stdout().write_all(br#"{"entries":[]}"#).unwrap(),
        "malformed" => std::io::stdout().write_all(b"not JSON").unwrap(),
        "nonutf8" => std::io::stdout().write_all(&[255]).unwrap(),
        "oversize" => {
            let _ = std::io::stdout().write_all(br#"{"entries":[],"padding":""#);
            let _ = std::io::stdout().write_all(&vec![b'x'; 1_100_000]);
            let _ = std::io::stdout().write_all(br#""}"#);
        }
        "nonzero" => std::process::exit(7),
        "timeout" => { std::thread::sleep(std::time::Duration::from_secs(3)); std::io::stdout().write_all(br#"{"entries":[]}"#).unwrap(); },
        "descendant" => {
            let child = std::process::Command::new(std::env::current_exe().unwrap()).arg("timeout").spawn().unwrap();
            std::fs::write(&arguments[2], child.id().to_string()).unwrap();
            std::io::stdout().write_all(br#"{"entries":[]}"#).unwrap();
        }
        _ => panic!("Unknown fixture scenario"),
    }
}
