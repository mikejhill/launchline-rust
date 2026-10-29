# Rust runtime captures

The README's launcher.gif and menus.gif were captured independently from this
repository's actual Rust application in an owned 80-column by 22-row Windows
ConPTY. No desktop input, clipboard or hooks were used. Both runtimes use the
same fixture and pixel renderer, but each launches its own executable and records
its own raw output. Matching pixels reflect their shared UI contract, not capture
substitution.

The renderer in `tools/terminal_render.py` is extracted from the original Python
[`tools/generate_screenshots.py`](https://github.com/mikejhill/launchline/blob/main/tools/generate_screenshots.py):
CGA ANSI palette, black background, Cascadia Mono 15px, 20px line height,
foreground/background/reverse/bold cells, blue borders, green active entries and
the original terminal chrome. No UI strings or menu state are painted separately
from captured output. The original generator and historical assets remain intact.

From the repository root on Windows:

```powershell
cargo build --locked
uv run --with pywinpty --with pyte --with pillow python tools/capture_menus.py --runtime Rust --executable target/debug/launchline.exe
```

The script removes NO_COLOR and configures an ANSI-capable terminal only for
the child. It copies the committed examples into a disposable home/projects/my-app
fixture, so the displayed working directory is real and short. The original six
tools remain visible alongside Development and Projects. No leaf command is run.
Input exercises incremental fuzzy search, backspace, arrow navigation, static
submenu, zero/Back, the real provider, Ctrl+R refresh, zero/Back again and root Exit. Provider JSON is
produced by the actual provider subprocess.

Each `.ansi` file contains cumulative raw output at that checkpoint; `.txt`
contains decoded terminal cells with trailing blank padding omitted. `manifest.json` records source commit, actual
runtime command and executable hash, capture script/renderer/fixture hashes,
dependencies, input and image/raw-output hashes. The recorded source commit
precedes these documentation edits; application sources were checked unchanged.

Read the [pixel and animation review](visual-review.md), including original,
regressed and restored comparisons and narrow-screen previews. These are Windows
terminal/render captures, not physical-keyboard or other-platform validation.

Submenu captures show `0 Back` and no numbered Exit. Raw `.ansi` files are
stored as binary Git data to preserve terminal newlines; decoded `.txt` uses LF.
