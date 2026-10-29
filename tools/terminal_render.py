"""Original CGA screenshot renderer, extracted from generate_screenshots.py.

Only presentation is shared between runtimes; every cell comes from that
runtime's own ConPTY output. The original generator and historical assets remain.
"""

from __future__ import annotations
import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES: list[Path] = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "CascadiaMono.ttf",
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "consola.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSansMono.ttf"),
]


FONT_SIZE = 15


LINE_HEIGHT_FACTOR = 1.35


def _find_font() -> Path:
    """Locate a monospace TrueType font on the system."""
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    msg = "No monospace TrueType font found. Install Cascadia Mono or DejaVu Sans Mono."
    raise FileNotFoundError(msg)


BG_COLOR = (0, 0, 0)


FG_COLOR = (170, 170, 170)


_ANSI_16: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "red": (170, 0, 0),
    "green": (0, 170, 0),
    "brown": (170, 85, 0),  # pyte calls yellow "brown"
    "blue": (0, 0, 170),
    "magenta": (170, 0, 170),
    "cyan": (0, 170, 170),
    "white": (170, 170, 170),
    "brightblack": (85, 85, 85),
    "brightred": (255, 85, 85),
    "brightgreen": (85, 255, 85),
    "brightyellow": (255, 255, 85),
    "brightbrown": (255, 255, 85),
    "brightblue": (85, 85, 255),
    "brightmagenta": (255, 85, 255),
    "brightcyan": (85, 255, 255),
    "brightwhite": (255, 255, 255),
}


_ANSI_16_BY_INDEX: list[tuple[int, int, int]] = [
    _ANSI_16["black"],
    _ANSI_16["red"],
    _ANSI_16["green"],
    _ANSI_16["brown"],
    _ANSI_16["blue"],
    _ANSI_16["magenta"],
    _ANSI_16["cyan"],
    _ANSI_16["white"],
    _ANSI_16["brightblack"],
    _ANSI_16["brightred"],
    _ANSI_16["brightgreen"],
    _ANSI_16["brightyellow"],
    _ANSI_16["brightblue"],
    _ANSI_16["brightmagenta"],
    _ANSI_16["brightcyan"],
    _ANSI_16["brightwhite"],
]


_CUBE_INTENSITIES = (0, 95, 135, 175, 215, 255)


def _color_256_to_rgb(n: int) -> tuple[int, int, int]:
    """Convert a 256-colour index to an RGB triple."""
    if n < 16:
        return _ANSI_16_BY_INDEX[n]
    if n < 232:
        n -= 16
        return (
            _CUBE_INTENSITIES[n // 36],
            _CUBE_INTENSITIES[(n % 36) // 6],
            _CUBE_INTENSITIES[n % 6],
        )
    v = 8 + (n - 232) * 10
    return (v, v, v)


def _resolve_color(
    raw: str,
    default: tuple[int, int, int],
) -> tuple[int, int, int]:
    """Resolve a pyte colour attribute to an RGB triple.

    Pyte may represent colours as ``"default"``, a named colour
    (``"brightgreen"``), a 256-colour index string (``"69"``), or a
    6-character hex string (``"5f87ff"``).
    """
    if raw == "default":
        return default
    key = raw.replace(" ", "").lower()
    if key in _ANSI_16:
        return _ANSI_16[key]
    with contextlib.suppress(ValueError):
        return _color_256_to_rgb(int(raw))
    # pyte sometimes stores 256-color values as 6-char hex RGB strings
    if len(raw) == 6:
        with contextlib.suppress(ValueError):
            return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    return default


CHROME_PAD_X = 20


CHROME_PAD_Y_TOP = 12


CHROME_PAD_Y_BOTTOM = 16


TITLEBAR_H = 40


CORNER_R = 10


TITLEBAR_BG = (20, 20, 20)


DOT_COLORS = ((255, 95, 86), (255, 189, 46), (39, 201, 63))


@dataclass
class ScreenCell:
    """One character cell with resolved colours."""

    char: str = " "
    fg: tuple[int, int, int] = field(default_factory=lambda: FG_COLOR)
    bg: tuple[int, int, int] = field(default_factory=lambda: BG_COLOR)
    bold: bool = False


class TerminalRenderer:
    """Converts cell grids into PNG images with terminal window chrome."""

    def __init__(self, font_path: Path | None = None) -> None:
        path = font_path or _find_font()
        self.font = ImageFont.truetype(str(path), FONT_SIZE)
        bbox = self.font.getbbox("M")
        self.cw = bbox[2] - bbox[0]  # cell width
        self.ch = int(FONT_SIZE * LINE_HEIGHT_FACTOR)  # cell height
        self.ty_off = max(0, (self.ch - (bbox[3] - bbox[1])) // 2)

    # -- public API ---------------------------------------------------------

    def render_png(
        self,
        grid: list[list[ScreenCell]],
        path: Path,
    ) -> None:
        """Render a single frame to a PNG file."""
        img = self._paint(grid)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(path), "PNG")
        print(f"  Saved {path}  ({img.width}x{img.height})")

    def render_gif(
        self,
        grids: list[list[list[ScreenCell]]],
        path: Path,
        *,
        durations: list[int] | None = None,
    ) -> None:
        """Stitch multiple frames into an animated GIF.

        Args:
            grids: Cell grids for each frame.
            path: Output file path.
            durations: Per-frame durations in milliseconds. If ``None``,
                every frame defaults to 500 ms.
        """
        if not grids:
            return
        frames = [self._paint(g) for g in grids]
        if durations is None:
            durations = [500] * len(frames)

        path.parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(
            str(path),
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
        )
        print(f"  Saved {path}  ({len(frames)} frames)")

    # -- internal -----------------------------------------------------------

    def _paint(self, grid: list[list[ScreenCell]]) -> Image.Image:
        """Render a cell grid to an RGB image with terminal window chrome."""
        rows = len(grid)
        cols = len(grid[0]) if grid else 0

        content_w = cols * self.cw
        content_h = rows * self.ch

        img_w = content_w + 2 * CHROME_PAD_X
        img_h = content_h + TITLEBAR_H + CHROME_PAD_Y_TOP + CHROME_PAD_Y_BOTTOM

        img = Image.new("RGB", (img_w, img_h), BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Rounded window background
        draw.rounded_rectangle(
            [0, 0, img_w - 1, img_h - 1],
            radius=CORNER_R,
            fill=BG_COLOR,
        )

        # Title bar
        draw.rounded_rectangle(
            [0, 0, img_w - 1, TITLEBAR_H],
            radius=CORNER_R,
            fill=TITLEBAR_BG,
        )
        # Square off the bottom edge of the title bar
        draw.rectangle(
            [0, TITLEBAR_H - CORNER_R, img_w - 1, TITLEBAR_H],
            fill=TITLEBAR_BG,
        )

        # Traffic-light dots
        dot_r = 6
        dot_spacing = 20
        dot_y = TITLEBAR_H // 2
        for i, colour in enumerate(DOT_COLORS):
            cx = CHROME_PAD_X + 2 + i * dot_spacing
            draw.ellipse(
                [cx - dot_r, dot_y - dot_r, cx + dot_r, dot_y + dot_r],
                fill=colour,
            )

        # Terminal content
        origin_x = CHROME_PAD_X
        origin_y = TITLEBAR_H + CHROME_PAD_Y_TOP
        for r_idx, row in enumerate(grid):
            y = origin_y + r_idx * self.ch
            for c_idx, cell in enumerate(row):
                x = origin_x + c_idx * self.cw
                if cell.bg != BG_COLOR:
                    draw.rectangle(
                        [x, y, x + self.cw, y + self.ch],
                        fill=cell.bg,
                    )
                if cell.char and cell.char != " ":
                    ty = y + self.ty_off
                    draw.text(
                        (x, ty),
                        cell.char,
                        fill=cell.fg,
                        font=self.font,
                    )
                    if cell.bold:
                        draw.text(
                            (x + 1, ty),
                            cell.char,
                            fill=cell.fg,
                            font=self.font,
                        )
        return img


def capture_cells(screen):
    """Extract actual ANSI colors, reverse and bold from the terminal emulator."""
    grid = []
    for y in range(screen.lines):
        row = []
        for x in range(screen.columns):
            cell = screen.buffer[y][x]
            fg = _resolve_color(cell.fg, FG_COLOR)
            bg = _resolve_color(cell.bg, BG_COLOR)
            if cell.reverse:
                fg, bg = bg, fg
            row.append(ScreenCell(cell.data, fg, bg, cell.bold))
        grid.append(row)
    return grid
