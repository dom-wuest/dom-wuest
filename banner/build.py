# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools>=4.50"]
# ///
"""Generate the animated profile banner (one SVG per theme) from banner.toml.

Usage (from the repository root):

    uv run banner/build.py [path/to/banner.toml]

The output is a self-contained SVG: text is converted to outlines, animation
uses SMIL only (no scripts, no external resources), so GitHub can render it
through an <img> tag. Visitors with "reduce motion" enabled get a still frame.
"""

import math
import random
import sys
import tomllib
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent


def num(v: float) -> str:
    """Compact number formatting for SVG attributes."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def times(values: list[float]) -> str:
    return ";".join(f"{v:.4f}".rstrip("0").rstrip(".") or "0" for v in values)


class Font:
    def __init__(self, path: Path):
        self.tt = TTFont(path)
        self.glyphs = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap()
        self.upm = self.tt["head"].unitsPerEm

    def outline(self, text: str, size: float, x: float, y: float) -> tuple[str, list[float]]:
        """Return the SVG path of `text` and the x position after each character."""
        scale = size / self.upm
        pen = SVGPathPen(self.glyphs, ntos=num)
        cursor, advances = x, [x]
        for ch in text:
            name = self.cmap.get(ord(ch))
            if name is None:
                sys.exit(f"error: font has no glyph for {ch!r}")
            glyph = self.glyphs[name]
            glyph.draw(TransformPen(pen, (scale, 0, 0, -scale, cursor, y)))
            cursor += glyph.width * scale
            advances.append(cursor)
        return pen.getCommands(), advances


# --------------------------------------------------------------------------- #
# Typewriter
# --------------------------------------------------------------------------- #

def layout_text(cfg: dict, fonts: dict[str, Font]) -> tuple[list[dict], float]:
    """Compute outlines and reveal times for every line. Returns (lines, cycle length)."""
    typing = cfg["typing"]
    t = typing["start_delay"]
    lines = []
    for i, line in enumerate(cfg["lines"]):
        path, advances = fonts[line["font"]].outline(line["text"], line["size"], line["x"], line["y"])
        reveal = [t + k * line["char_delay"] for k in range(1, len(line["text"]) + 1)]
        lines.append({**line, "id": f"l{i}", "path": path, "advances": advances, "reveal": reveal})
        t = reveal[-1] + typing["line_pause"]
    typed = lines[-1]["reveal"][-1]
    fade_start = typed + typing["hold"]
    fade_end = fade_start + typing["fade"]
    cycle = fade_end + typing["gap"]
    for line in lines:
        line["fade"] = (fade_start, fade_end)
    return lines, cycle


def reveal_clip(line: dict, cycle: float, clip_id: str, pad: float) -> str:
    """Clip rectangle that grows with the typed characters of `line`, padded on every side."""
    x0, size = line["x"], line["size"]
    key_times = [0.0] + [t / cycle for t in line["reveal"]] + [line["fade"][1] / cycle]
    widths = ["0"] + [num(a - x0 + 2 * pad) for a in line["advances"][1:]] + ["0"]
    return (
        f'<clipPath id="{clip_id}"><rect x="{num(x0 - pad)}" y="{num(line["y"] - size * 1.1 - pad)}" '
        f'width="0" height="{num(size * 1.5 + 2 * pad)}">'
        f'<animate attributeName="width" calcMode="discrete" dur="{num(cycle)}s" repeatCount="indefinite" '
        f'keyTimes="{times(key_times)}" values="{";".join(widths)}"/>'
        f"</rect></clipPath>"
    )


def typewriter(lines: list[dict], cycle: float, typing: dict, colors: dict) -> list[str]:
    fade_start, fade_end = lines[0]["fade"]
    out = ["<defs>", *(reveal_clip(line, cycle, f'c{line["id"]}', 2) for line in lines), "</defs>"]

    # Cursor follows the last revealed character.
    steps = [(0.0, lines[0], lines[0]["x"])]
    for line in lines:
        steps += [(t, line, a) for t, a in zip(line["reveal"], line["advances"][1:])]
    key_times = times([t / cycle for t, _, _ in steps])
    xs = ";".join(num(a + 2) for _, _, a in steps)
    ys = ";".join(num(l["y"] - l["size"] * 0.78) for _, l, _ in steps)
    hs = ";".join(num(l["size"] * 0.92) for _, l, _ in steps)
    anim = f'calcMode="discrete" dur="{num(cycle)}s" repeatCount="indefinite" keyTimes="{key_times}"'

    fade = times([0, fade_start / cycle, fade_end / cycle, 1])
    out.append('<g class="motion">')
    out.append(
        f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="{fade}" '
        f'dur="{num(cycle)}s" repeatCount="indefinite"/>'
    )
    for line in lines:
        out.append(f'<use href="#{line["id"]}" fill="{colors[line["color"]]}" clip-path="url(#c{line["id"]})"/>')
    out.append(
        f'<rect width="3" fill="{colors["accent"]}">'
        f'<animate attributeName="x" {anim} values="{xs}"/>'
        f'<animate attributeName="y" {anim} values="{ys}"/>'
        f'<animate attributeName="height" {anim} values="{hs}"/>'
        f'<animate attributeName="opacity" values="1;0" calcMode="discrete" '
        f'dur="{num(typing["cursor_blink"])}s" repeatCount="indefinite"/>'
        f"</rect>"
    )
    out.append("</g>")

    out.append('<g class="still">')
    out += [f'<use href="#{line["id"]}" fill="{colors[line["color"]]}"/>' for line in lines]
    out.append("</g>")
    return out


# --------------------------------------------------------------------------- #
# Network graph
# --------------------------------------------------------------------------- #

def build_graph(g: dict) -> tuple[list[dict], list[tuple[int, int]]]:
    rng = random.Random(g["seed"])
    x0, y0, x1, y1 = g["region"]
    nodes: list[dict] = []
    for _ in range(g["nodes"] * 200):
        if len(nodes) == g["nodes"]:
            break
        p = (rng.uniform(x0, x1), rng.uniform(y0, y1))
        if all(math.dist(p, n["p"]) >= g["min_distance"] for n in nodes):
            nodes.append({
                "p": p,
                "r": rng.uniform(*g["radius"]),
                "a": (rng.uniform(*g["amplitude"]), rng.uniform(*g["amplitude"])),
                "k": (rng.choice((1, 2)), rng.choice((1, 2))),
                "phase": (rng.uniform(0, math.tau), rng.uniform(0, math.tau)),
                "dir": rng.choice((-1, 1)),
            })

    edges = set()
    for i, n in enumerate(nodes):
        nearest = sorted(range(len(nodes)), key=lambda j: math.dist(n["p"], nodes[j]["p"]))[1:]
        for j in nearest[: g["neighbours"]]:
            if math.dist(n["p"], nodes[j]["p"]) <= g["max_edge"]:
                edges.add((min(i, j), max(i, j)))
    return nodes, sorted(edges)


def drift(node: dict, samples: int) -> tuple[list[float], list[float]]:
    """Closed Lissajous loop around the node's base position."""
    (bx, by), (ax, ay), (kx, ky), (px, py) = node["p"], node["a"], node["k"], node["phase"]
    xs, ys = [], []
    for s in range(samples + 1):
        t = node["dir"] * math.tau * s / samples
        xs.append(bx + ax * math.cos(kx * t + px))
        ys.append(by + ay * math.sin(ky * t + py))
    return xs, ys


def graph(g: dict, colors: dict) -> list[str]:
    nodes, edges = build_graph(g)
    paths = [drift(n, g["samples"]) for n in nodes]
    anim = f'dur="{num(g["period"])}s" repeatCount="indefinite"'

    def values(seq):
        return ";".join(num(v) for v in seq)

    out = [f'<g mask="url(#graph-fade)">', '<g class="motion">']
    out.append(f'<g stroke="{colors["edge"]}" stroke-opacity="{g["edge_opacity"]}" stroke-width="1.2">')
    for i, j in edges:
        (xi, yi), (xj, yj) = paths[i], paths[j]
        out.append(
            f'<line x1="{num(xi[0])}" y1="{num(yi[0])}" x2="{num(xj[0])}" y2="{num(yj[0])}">'
            f'<animate attributeName="x1" {anim} values="{values(xi)}"/>'
            f'<animate attributeName="y1" {anim} values="{values(yi)}"/>'
            f'<animate attributeName="x2" {anim} values="{values(xj)}"/>'
            f'<animate attributeName="y2" {anim} values="{values(yj)}"/>'
            f"</line>"
        )
    out.append(f'</g><g fill="{colors["node"]}">')
    for n, (xs, ys) in zip(nodes, paths):
        out.append(
            f'<circle r="{num(n["r"])}" cx="{num(xs[0])}" cy="{num(ys[0])}">'
            f'<animate attributeName="cx" {anim} values="{values(xs)}"/>'
            f'<animate attributeName="cy" {anim} values="{values(ys)}"/>'
            f"</circle>"
        )
    out.append("</g></g>")

    # Still frame for reduced motion.
    out.append(f'<g class="still"><g stroke="{colors["edge"]}" stroke-opacity="{g["edge_opacity"]}" stroke-width="1.2">')
    for i, j in edges:
        out.append(
            f'<line x1="{num(paths[i][0][0])}" y1="{num(paths[i][1][0])}" '
            f'x2="{num(paths[j][0][0])}" y2="{num(paths[j][1][0])}"/>'
        )
    out.append(f'</g><g fill="{colors["node"]}">')
    for n, (xs, ys) in zip(nodes, paths):
        out.append(f'<circle r="{num(n["r"])}" cx="{num(xs[0])}" cy="{num(ys[0])}"/>')
    out.append("</g></g></g>")
    return out


# --------------------------------------------------------------------------- #
# Document
# --------------------------------------------------------------------------- #

def render(cfg: dict, colors: dict, lines: list[dict], cycle: float) -> str:
    c, g = cfg["canvas"], cfg["graph"]
    w, h, r = c["width"], c["height"], c["corner_radius"]
    bg0, bg1 = colors["background"]
    glow, glow_opacity = colors["glow"], colors["glow_opacity"]
    fx0, fx1 = g["fade"]

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="{escape(c["title"], {chr(34): "&quot;"})}">',
        f"<title>{escape(c['title'])}</title>",
        "<style>.still{display:none}"
        "@media (prefers-reduced-motion:reduce){.motion{display:none}.still{display:inline}}</style>",
        "<defs>",
        f'<clipPath id="card"><rect width="{w}" height="{h}" rx="{r}"/></clipPath>',
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{bg0}"/><stop offset="1" stop-color="{bg1}"/></linearGradient>',
        f'<radialGradient id="glow"><stop offset="0" stop-color="{glow}" stop-opacity="{glow_opacity}"/>'
        f'<stop offset="1" stop-color="{glow}" stop-opacity="0"/></radialGradient>',
        f'<linearGradient id="fade-ramp" gradientUnits="userSpaceOnUse" x1="{fx0}" y1="0" x2="{fx1}" y2="0">'
        f'<stop offset="0" stop-color="#fff" stop-opacity="0.12"/><stop offset="1" stop-color="#fff"/></linearGradient>',
    ]
    for line in lines:
        out.append(f'<path id="{line["id"]}" d="{line["path"]}"/>')
    # The graph fades out towards the text and leaves a soft halo around every typed line.
    halo = g["text_halo"]
    out += [reveal_clip(line, cycle, f'h{line["id"]}', halo + 2) for line in lines]
    out.append(f'<mask id="graph-fade"><rect width="{w}" height="{h}" fill="url(#fade-ramp)"/>')
    for cls, clip in (("motion", True), ("still", False)):
        out.append(f'<g class="{cls}">')
        for width, shade in ((halo * 2, "#555"), (halo, "#000")):
            out += [
                f'<use href="#{line["id"]}" fill="{shade}" stroke="{shade}" stroke-width="{num(width)}" '
                f'stroke-linejoin="round"' + (f' clip-path="url(#h{line["id"]})"' if clip else "") + "/>"
                for line in lines
            ]
        out.append("</g>")
    out.append("</mask></defs>")

    out.append('<g clip-path="url(#card)">')
    out.append(f'<rect width="{w}" height="{h}" fill="url(#bg)"/>')
    out.append(
        f'<ellipse cx="{num(w * 0.78)}" cy="{num(h * 0.35)}" rx="{num(w * 0.32)}" ry="{num(h * 0.75)}" fill="url(#glow)">'
        f'<animateTransform attributeName="transform" type="translate" values="0 0;-40 18;0 0" '
        f'dur="{num(g["period"] * 1.5)}s" repeatCount="indefinite"/></ellipse>'
    )
    out.append(
        f'<ellipse cx="{num(w * 0.12)}" cy="{num(h * 0.95)}" rx="{num(w * 0.25)}" ry="{num(h * 0.5)}" '
        f'fill="url(#glow)" opacity="0.6"/>'
    )
    out += graph(g, colors)
    out += typewriter(lines, cycle, cfg["typing"], colors)
    out.append("</g>")
    out.append(
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="{r}" fill="none" stroke="{colors["border"]}"/>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    config_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE / "banner.toml"
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent

    fonts = {key: Font(base / path) for key, path in cfg["fonts"].items()}
    lines, cycle = layout_text(cfg, fonts)

    out_dir = (base / cfg["output"]["dir"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for theme, colors in cfg["themes"].items():
        target = out_dir / cfg["output"]["name"].format(theme=theme)
        target.write_text(render(cfg, colors, lines, cycle), encoding="utf-8", newline="\n")
        print(f"wrote {target} ({target.stat().st_size / 1024:.1f} KiB, loop {cycle:.1f}s)")


if __name__ == "__main__":
    main()
