"""Build labeled pixel comparisons from original/regressed/captured assets."""

import hashlib
import io
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from terminal_render import _find_font

font = ImageFont.truetype(str(_find_font()), 14)
root = Path(__file__).resolve().parents[1]
images = root / "docs/images"
out = images / "review"
out.mkdir(exist_ok=True)
manifest = json.loads((images / "captures/manifest.json").read_text())
base = manifest.get("comparison_baseline", manifest["source_commit"])


def old(name):
    return Image.open(
        io.BytesIO(
            subprocess.check_output(
                ["git", "show", f"{base}:docs/images/{name}"], cwd=root
            )
        )
    ).convert("RGB")


def sheet(items, path, columns, width):
    tiles = []
    for label, im in items:
        scaled = im.resize(
            (width, round(im.height * width / im.width)), Image.Resampling.LANCZOS
        )
        tile = Image.new("RGB", (width, scaled.height + 32), "#242424")
        ImageDraw.Draw(tile).text((8, 8), label, font=font, fill="white")
        tile.paste(scaled, (0, 32))
        tiles.append(tile)
    height = max(t.height for t in tiles)
    canvas = Image.new(
        "RGB",
        (columns * width, ((len(tiles) + columns - 1) // columns) * height),
        "#242424",
    )
    for i, tile in enumerate(tiles):
        canvas.paste(tile, ((i % columns) * width, (i // columns) * height))
    canvas.save(path)


comparison = [
    ("Original hero.png", old("hero.png")),
    ("Regressed root.png", old("root.png")),
    (
        "Restored actual " + manifest["runtime"],
        Image.open(images / "root.png").convert("RGB"),
    ),
]
sheet(comparison, out / "comparison.png", 3, 380)
sheet(comparison, out / "mobile.png", 3, 375)
stats = {}
for name in ["demo.gif", "launcher.gif", "menus.gif"]:
    animation = Image.open(images / name)
    frames = []
    durations = []
    for i in range(animation.n_frames):
        animation.seek(i)
        duration = animation.info.get("duration")
        durations.append(duration)
        frames.append(
            (f"{name}: {i + 1} / {duration} ms", animation.convert("RGB").copy())
        )
    sheet(frames, out / (name.removesuffix(".gif") + "-frames.png"), 2, 380)
    stats[name] = {
        "size": list(animation.size),
        "frames": animation.n_frames,
        "durations_ms": durations,
        "total_ms": sum(durations),
    }
assert (
    subprocess.check_output(["git", "show", f"{base}:docs/images/demo.gif"], cwd=root)
    == (images / "demo.gif").read_bytes()
)
assert (
    subprocess.check_output(["git", "show", f"{base}:docs/images/hero.png"], cwd=root)
    == (images / "hero.png").read_bytes()
)
(out / "measurements.json").write_text(
    json.dumps(
        {
            "runtime": manifest["runtime"],
            "baseline_commit": base,
            "animations": stats,
            "original_demo_sha256": hashlib.sha256(
                (images / "demo.gif").read_bytes()
            ).hexdigest(),
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(root.name, json.dumps(stats))
