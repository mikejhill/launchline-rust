# Rust runtime captures

The README's menus.gif, nested.png and dynamic.png were captured independently
from this repository's actual Rust application. The program ran in an owned
100-column by 24-row Windows ConPTY; no desktop input, clipboard or hooks were
used. The same public fixture is used by both runtimes, but neither runtime's
output is substituted for the other's.

From this repository root on Windows, reproduce with:

```powershell
cargo build --locked
uv run --no-project --python 3.12 --with pywinpty==3.1.0 --with pyte==0.8.2 --with Pillow==13.0.0 python tools/capture_menus.py --runtime Rust --executable target/debug/launchline.exe
```

The provider requires Python on PATH; the capture script adds its own interpreter
directory for the disposable child environment. The provider prints deterministic
JSON and no leaf command is selected. Input opens Development, returns with a
separate Escape event, opens Projects (running the real provider), then exits.

Each `.ansi` file is the cumulative raw terminal output at that checkpoint;
each `.txt` is its decoded terminal screen. `manifest.json` records the source
commit, runtime executable SHA-256, actual command, dependency versions and raw
output hashes. The source commit precedes these documentation-only edits.

PNG/GIF images paint the actual decoded terminal text with Cascadia Mono, using
a uniform foreground/background for readability; ANSI colors are omitted.
No UI strings or menu state are drawn independently of the captured output.
This is terminal/render evidence on Windows, not physical keyboard, screen reader
or other-platform validation. The older demo.gif/search.png/navigate.png assets
are historical and are no longer presented by the README.
