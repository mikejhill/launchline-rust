#[path = "../src/fuzzy.rs"]
mod fuzzy;
use std::{hint::black_box, time::Instant};
fn main() {
    let tail = format!("abc{}", "x".repeat(4096));
    let sparse = format!("a{}z", "x".repeat(128));
    let miss = "x".repeat(4096);
    for (name, query, candidate) in [
        ("exact", "powershell", "PowerShell"),
        ("prefix-long-tail", "abc", tail.as_str()),
        ("sparse", "az", sparse.as_str()),
        ("miss-long", "z", miss.as_str()),
        ("unicode", "猫é", "猫 café"),
    ] {
        let mut samples = Vec::new();
        let expected = fuzzy::FuzzyMatcher::score(query, candidate);
        for _ in 0..7 {
            let start = Instant::now();
            for _ in 0..1000 {
                assert_eq!(
                    fuzzy::FuzzyMatcher::score(black_box(query), black_box(candidate)),
                    expected
                );
            }
            samples.push(start.elapsed().as_nanos() / 1000);
        }
        println!("{name}: {samples:?}");
    }
}
