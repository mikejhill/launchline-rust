//! Harmless native child used by subprocess integration tests.
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let output = format!("{}|{}|{}", args[2..].join("\n"), std::env::var("LL_CONTRACT").unwrap(), std::env::current_dir().unwrap().display());
    std::fs::write(&args[1], output).unwrap();
    std::process::exit(7);
}
