"""
graphics - every image Facetcast ships, drawn locally with Pillow. No design tool needed.

    linkedin  card      1200 x 627
    x         card      1600 x 900
    instagram slides    1080 x 1350 (4:5), one PNG per slide
    tiktok    cover     1080 x 1920 (9:16), text kept inside the UI-safe zone
    github    preview   1280 x 640  (Settings -> Social preview)

Five themes (the profiler picks one per project; you can switch in the dashboard):
    midnight  dark, calm, technical       paper   light, editorial, academic
    bold      saturated colour block      terminal dark hacker look (dev / security tools)
    pastel    soft, art and education
The profiler's accent colour is applied on top, with an automatic contrast fix.
Fonts: Inter + JetBrains Mono (SIL OFL) ship in assets/fonts, so output looks the same on
every OS. System fonts are the fallback.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from config.settings import FONTS_DIR

THEMES = {
    "midnight": {"bg": "#0B1020", "bg2": "#151D38", "text": "#EEF2FF", "muted": "#9AA4C2", "accent": "#7C9CFF", "dark": True},
    "paper":    {"bg": "#F6F1E7", "bg2": "#ECE3D2", "text": "#1E1B16", "muted": "#6B6457", "accent": "#C2410C", "dark": False},
    "bold":     {"bg": "#FF5A36", "bg2": "#E2401D", "text": "#FFFFFF", "muted": "#FFE4DC", "accent": "#16120F", "dark": True},
    "terminal": {"bg": "#070B10", "bg2": "#0F1720", "text": "#E6EDF3", "muted": "#8B9BB0", "accent": "#3EE6A8", "dark": True},
    "pastel":   {"bg": "#FBF4FF", "bg2": "#F0E2FA", "text": "#2B2140", "muted": "#6E5F86", "accent": "#9B5DE5", "dark": False},
}
SIZES = {"linkedin": (1200, 627), "x": (1600, 900), "instagram": (1080, 1350),
         "tiktok": (1080, 1920), "github": (1280, 640)}

_SYS = {
    "sans": ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "bold": ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
    "mono": ["C:/Windows/Fonts/consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
             "/System/Library/Fonts/Supplemental/Courier New.ttf"],
}
FONT_FILES = {
    "sans": ["Inter-Regular.ttf"], "semi": ["Inter-SemiBold.ttf"], "bold": ["Inter-Bold.ttf"],
    "display": ["InterDisplay-Bold.ttf"], "black": ["InterDisplay-Black.ttf"],
    "mono": ["JetBrainsMono-Regular.ttf"], "monob": ["JetBrainsMono-Bold.ttf"],
}
_FALLBACK = {"sans": "sans", "semi": "bold", "bold": "bold", "display": "bold", "black": "bold",
             "mono": "mono", "monob": "mono"}


def font_path(kind: str) -> str | None:
    for name in FONT_FILES[kind]:
        p = FONTS_DIR / name
        if p.exists():
            return str(p)
    for p in _SYS[_FALLBACK[kind]]:
        if Path(p).exists():
            return p
    return None


_cache: dict = {}


def font(kind: str, size: int):
    from PIL import ImageFont
    key = (kind, size)
    if key not in _cache:
        p = font_path(kind)
        try:
            _cache[key] = ImageFont.truetype(p, size) if p else ImageFont.load_default(size)
        except Exception:
            _cache[key] = ImageFont.load_default(size)
    return _cache[key]


# ---------------------------------------------------------------- colour

def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(c) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(v))) for v in c[:3])


def _lum(h: str) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a: str, b: str, t: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return _hex([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def palette(theme: str | None, accent: str | None = None) -> dict:
    """Theme colours with the project's accent applied and contrast kept readable."""
    t = dict(THEMES.get(theme or "midnight", THEMES["midnight"]))
    t["name"] = theme if theme in THEMES else "midnight"
    if accent and re.match(r"^#[0-9a-fA-F]{6}$", accent):
        if t["name"] == "bold":
            t["bg"] = accent
            t["bg2"] = mix(accent, "#000000", 0.14)
            dark_text = contrast(accent, "#FFFFFF") < 3.0
            t["text"] = "#16120F" if dark_text else "#FFFFFF"
            t["muted"] = mix(t["text"], accent, 0.35)
            t["accent"] = "#16120F" if not dark_text else "#FFFFFF"
            t["dark"] = not dark_text
        else:
            t["accent"] = accent
    for _ in range(10):                                 # keep the accent visible on the background
        if contrast(t["accent"], t["bg"]) >= 3.0:
            break
        t["accent"] = mix(t["accent"], "#FFFFFF" if t["dark"] else "#000000", 0.18)
    t["on_accent"] = "#FFFFFF" if contrast(t["accent"], "#FFFFFF") >= 3.2 else "#0B0B0B"
    return t


# ---------------------------------------------------------------- text layout

def wrap(draw, text: str, f, max_w: float) -> list[str]:
    lines = []
    for para in str(text or "").split("\n"):
        words, cur = para.split(), ""
        for w in words:
            t = f"{cur} {w}".strip()
            if draw.textlength(t, font=f) > max_w and cur:
                lines.append(cur)
                cur = w
            else:
                cur = t
        lines.append(cur)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def fit(draw, text: str, kind: str, max_w: float, max_h: float, start: int, minimum: int,
        leading: float = 1.18, max_lines: int = 99):
    """Largest font size at which the text fits the box. Returns (font, lines, line_height)."""
    size = start
    while True:
        f = font(kind, size)
        lines = wrap(draw, text, f, max_w)
        lh = int(size * leading)
        if (len(lines) * lh <= max_h and len(lines) <= max_lines) or size <= minimum:
            if len(lines) > max_lines or len(lines) * lh > max_h:
                keep = max(1, min(max_lines, int(max_h // lh)))
                lines = lines[:keep]
                lines[-1] = lines[-1].rstrip(" .,;:") + "…"
            return f, lines, lh
        size = max(minimum, int(size * 0.92))


def draw_lines(draw, xy, lines, f, lh, fill, align="left", width=None):
    x, y = xy
    for ln in lines:
        if align == "center" and width:
            w = draw.textlength(ln, font=f)
            draw.text((x + (width - w) / 2, y), ln, font=f, fill=fill)
        else:
            draw.text((x, y), ln, font=f, fill=fill)
        y += lh
    return y


# ---------------------------------------------------------------- shared pieces

def _canvas(W, H, pal):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), pal["bg"])
    return img, ImageDraw.Draw(img)


def _decor(img, pal, W, H, seed: int = 0):
    """Quiet background texture per theme. Never competes with the text."""
    from PIL import Image, ImageDraw, ImageFilter
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    acc = _rgb(pal["accent"])
    name = pal["name"]
    if name in ("midnight", "pastel", "bold"):
        r = int(max(W, H) * 0.42)
        cx, cy = (int(W * 0.86), int(H * 0.12)) if seed % 2 == 0 else (int(W * 0.10), int(H * 0.92))
        alpha = 46 if name == "midnight" else 60 if name == "pastel" else 34
        col = acc if name != "bold" else _rgb(pal["bg2"])
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*col, alpha))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=max(W, H) // 12))
    elif name == "terminal":
        step = max(W, H) // 40
        for x in range(0, W, step):
            for y in range(0, H, step):
                d.point((x, y), fill=(*acc, 38))
    elif name == "paper":
        d.rectangle((0, 0, W, int(H * 0.012)), fill=(*acc, 255))
    img.paste(layer, (0, 0), layer)


def _footer(draw, pal, W, H, brand: dict, pad: int, size: int):
    left = brand.get("handle") or brand.get("name") or brand.get("project") or ""
    right = brand.get("url_short") or ""
    f1, f2 = font("semi", size), font("mono", int(size * 0.82))
    y = H - pad - size
    if left:
        draw.ellipse((pad, y + size * 0.28, pad + size * 0.45, y + size * 0.73), fill=pal["accent"])
        draw.text((pad + size * 0.8, y), left, font=f1, fill=pal["text"])
    if right:
        w = draw.textlength(right, font=f2)
        if w < W * 0.55:
            draw.text((W - pad - w, y + size * 0.1), right, font=f2, fill=pal["muted"])


def _kicker(draw, pal, x, y, text, size):
    if not text:
        return y
    f = font("monob", size)
    t = text.upper()[:48]
    draw.text((x, y), t, font=f, fill=pal["accent"])
    return y + int(size * 1.9)


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- cards (linkedin, x)

def card(graphic: dict, pal: dict, brand: dict, size=(1200, 627)) -> bytes:
    W, H = size
    img, d = _canvas(W, H, pal)
    _decor(img, pal, W, H)
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    s = min(W, H)
    pad = int(s * 0.1)
    style = graphic.get("style") or "headline"
    head, sub = graphic.get("headline") or "", graphic.get("subline")
    foot = int(s * 0.042)
    box_h = H - 2 * pad - foot * 2.6

    if style == "terminal":
        x0, y0, x1, y1 = pad * 0.6, pad * 0.6, W - pad * 0.6, H - pad * 0.6 - foot * 2.2
        d.rounded_rectangle((x0, y0, x1, y1), int(s * 0.03), fill=pal["bg2"])
        for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
            r = s * 0.012
            cx = x0 + s * 0.04 + i * s * 0.035
            d.ellipse((cx - r, y0 + s * 0.04 - r, cx + r, y0 + s * 0.04 + r), fill=c)
        d.text((x0 + s * 0.16, y0 + s * 0.022), brand.get("project", ""), font=font("mono", int(s * 0.03)), fill=pal["muted"])
        tx, ty = x0 + s * 0.06, y0 + s * 0.12
        f, lines, lh = fit(d, head, "monob", x1 - tx - s * 0.12, (y1 - ty) * (0.62 if sub else 0.8), int(s * 0.085), int(s * 0.04), 1.3, 5)
        d.text((tx, ty), "$", font=f, fill=pal["accent"])
        y = draw_lines(d, (tx + f.size * 0.9, ty), lines, f, lh, pal["text"])
        if sub:
            f2, l2, lh2 = fit(d, "# " + sub, "mono", x1 - tx - s * 0.06, y1 - y - s * 0.08, int(s * 0.04), int(s * 0.026), 1.35, 3)
            y = draw_lines(d, (tx, y + s * 0.02), l2, f2, lh2, pal["muted"])
        d.rectangle((tx, min(y + s * 0.03, y1 - s * 0.09), tx + s * 0.03, min(y + s * 0.03, y1 - s * 0.09) + s * 0.055), fill=pal["accent"])
    elif style == "stat":
        stat = graphic.get("stat") or (re.search(r"\$?\d[\d,.%x]*|\b[A-Z]{2,}\b", head) or [""])[0] or "→"
        fs, ls, lhs = fit(d, stat, "black", W - 2 * pad, H * 0.36, int(s * 0.34), int(s * 0.12), 1.0, 1)
        d.text((pad, pad - fs.size * 0.08), ls[0], font=fs, fill=pal["accent"])
        y = pad + lhs * 1.05
        f, lines, lh = fit(d, head, "display", W - 2 * pad, (H - y - pad - foot * 2.6) * (0.75 if sub else 1), int(s * 0.075), int(s * 0.038), 1.15, 3)
        y = draw_lines(d, (pad, y), lines, f, lh, pal["text"])
        if sub:
            f2, l2, lh2 = fit(d, sub, "sans", W - 2 * pad, H - y - pad - foot * 2.6, int(s * 0.038), int(s * 0.026), 1.3, 2)
            draw_lines(d, (pad, y + s * 0.015), l2, f2, lh2, pal["muted"])
    elif style == "quote":
        bar_w = int(s * 0.014)
        f, lines, lh = fit(d, head, "display", W - 2 * pad - bar_w * 3, box_h * (0.74 if sub else 0.92), int(s * 0.1), int(s * 0.045), 1.14, 5)
        y = pad + max(0, (box_h - len(lines) * lh * (1.3 if sub else 1)) * 0.4)
        top = y
        y = draw_lines(d, (pad + bar_w * 3, y), lines, f, lh, pal["text"])
        if sub:
            f2, l2, lh2 = fit(d, sub, "sans", W - 2 * pad - bar_w * 3, box_h - (y - top), int(s * 0.042), int(s * 0.028), 1.3, 2)
            y = draw_lines(d, (pad + bar_w * 3, y + s * 0.02), l2, f2, lh2, pal["muted"])
        d.rectangle((pad, top + s * 0.01, pad + bar_w, y), fill=pal["accent"])
    else:                                                   # headline
        top = _kicker(d, pal, pad, pad, brand.get("project", ""), int(s * 0.03))
        bottom = H - pad - foot * 2.8
        f, lines, lh = fit(d, head, "display", W - 2 * pad, (bottom - top) * (0.74 if sub else 0.95), int(s * 0.13), int(s * 0.045), 1.1, 5)
        f2 = l2 = None
        if sub:
            f2, l2, lh2 = fit(d, sub, "sans", W - 2 * pad, (bottom - top) * 0.24, int(s * 0.044), int(s * 0.028), 1.3, 2)
        block = len(lines) * lh + (len(l2) * lh2 + s * 0.03 if sub else 0)
        y = top + max(0, (bottom - top - block) * 0.42)
        y = draw_lines(d, (pad, y), lines, f, lh, pal["text"])
        if sub:
            draw_lines(d, (pad, y + s * 0.03), l2, f2, lh2, pal["muted"])
    _footer(d, pal, W, H, brand, int(pad * 0.75), foot)
    return _png(img)


# ---------------------------------------------------------------- instagram carousel

def slide(i: int, n: int, s_: dict, pal: dict, brand: dict, size=(1080, 1350)) -> bytes:
    W, H = size
    img, d = _canvas(W, H, pal)
    _decor(img, pal, W, H, seed=i)
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    pad = int(W * 0.09)
    title, body = s_.get("title", ""), s_.get("body", "")
    first, last = i == 1, i == n
    d.text((pad, pad), f"{i:02d}/{n:02d}", font=font("monob", int(W * 0.03)), fill=pal["muted"])
    if brand.get("project"):
        p = brand["project"].upper()[:30]
        f = font("monob", int(W * 0.026))
        d.text((W - pad - d.textlength(p, font=f), pad + 2), p, font=f, fill=pal["accent"])
    avail_top, avail_bot = pad * 2.2, H - pad * 2.2
    if first:
        f, lines, lh = fit(d, title, "black", W - 2 * pad, (avail_bot - avail_top) * 0.68, int(W * 0.12), int(W * 0.06), 1.06, 6)
        block = len(lines) * lh
        y = avail_top + (avail_bot - avail_top - block) * 0.38
        y = draw_lines(d, (pad, y), lines, f, lh, pal["text"])
        if body:
            f2, l2, lh2 = fit(d, body, "semi", W - 2 * pad, avail_bot - y - W * 0.12, int(W * 0.045), int(W * 0.032), 1.3, 3)
            draw_lines(d, (pad, y + W * 0.03), l2, f2, lh2, pal["muted"])
        hint = "swipe  →"
        fh = font("monob", int(W * 0.034))
        bw = d.textlength(hint, font=fh) + W * 0.06
        d.rounded_rectangle((pad, H - pad - W * 0.085, pad + bw, H - pad), int(W * 0.04), fill=pal["accent"])
        d.text((pad + W * 0.03, H - pad - W * 0.066), hint, font=fh, fill=pal["on_accent"])
    else:
        num = f"{i - 1:02d}" if not last else "→"
        fnum = font("black", int(W * 0.15))
        d.text((pad, avail_top - W * 0.02), num, font=fnum, fill=pal["accent"])
        y = avail_top + W * 0.19
        f, lines, lh = fit(d, title, "display", W - 2 * pad, (avail_bot - y) * (0.45 if body else 0.9), int(W * 0.082), int(W * 0.05), 1.12, 5)
        y = draw_lines(d, (pad, y), lines, f, lh, pal["text"])
        if body:
            d.rectangle((pad, y + W * 0.03, pad + W * 0.09, y + W * 0.037), fill=pal["accent"])
            f2, l2, lh2 = fit(d, body, "sans", W - 2 * pad, avail_bot - y - W * 0.08, int(W * 0.047), int(W * 0.032), 1.38, 10)
            draw_lines(d, (pad, y + W * 0.075), l2, f2, lh2, pal["text"] if pal["name"] != "terminal" else pal["muted"])
    # progress dots
    r, gap = W * 0.007, W * 0.026
    x0 = W - pad - (n - 1) * gap
    for k in range(n):
        cx, cy = x0 + k * gap, H - pad - W * 0.04
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=pal["accent"] if k == i - 1 else mix(pal["muted"], pal["bg"], 0.5))
    if brand.get("handle") and not first:
        d.text((pad, H - pad - W * 0.055), brand["handle"], font=font("semi", int(W * 0.03)), fill=pal["muted"])
    return _png(img)


# ---------------------------------------------------------------- tiktok cover

def cover(hook: str, title: str, pal: dict, brand: dict, size=(1080, 1920)) -> bytes:
    W, H = size
    img, d = _canvas(W, H, pal)
    _decor(img, pal, W, H, seed=1)
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    pad = int(W * 0.1)
    top, bottom = H * 0.16, H * 0.70                 # TikTok UI covers the top bar and bottom ~30%
    f, lines, lh = fit(d, hook, "black", W - 2 * pad, (bottom - top) * 0.75, int(W * 0.12), int(W * 0.06), 1.08, 7)
    block = len(lines) * lh
    y = top + (bottom - top - block) / 2
    hl = int(W * 0.018)
    for ln in lines:                                # highlighter bars behind each line
        w = d.textlength(ln, font=f)
        x = (W - w) / 2
        d.rounded_rectangle((x - hl * 1.6, y + lh * 0.12, x + w + hl * 1.6, y + lh * 0.98), hl, fill=pal["accent"])
        d.text((x, y), ln, font=f, fill=pal["on_accent"])
        y += lh * 1.06
    if title:
        f2, l2, lh2 = fit(d, title, "semi", W - 2 * pad, H * 0.08, int(W * 0.045), int(W * 0.032), 1.25, 2)
        draw_lines(d, (pad, y + W * 0.05), l2, f2, lh2, pal["text"], align="center", width=W - 2 * pad)
    lab = brand.get("handle") or brand.get("project") or ""
    if lab:
        fl = font("monob", int(W * 0.036))
        d.text(((W - d.textlength(lab, font=fl)) / 2, top - W * 0.12), lab, font=fl, fill=pal["muted"])
    return _png(img)


# ---------------------------------------------------------------- github social preview

def preview(name: str, headline: str, subline: str | None, topics: list[str], pal: dict,
            brand: dict, size=(1280, 640)) -> bytes:
    W, H = size
    img, d = _canvas(W, H, pal)
    _decor(img, pal, W, H)
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    pad = 80                                         # GitHub crops edges on some surfaces
    owner = brand.get("owner_label") or ""
    if owner:
        d.text((pad, pad), owner, font=font("mono", 28), fill=pal["muted"])
    f, lines, lh = fit(d, name, "black", W - 2 * pad, 150, 110, 52, 1.0, 1)
    y = draw_lines(d, (pad, pad + 44), lines, f, lh, pal["text"])
    d.rectangle((pad, y + 26, pad + 90, y + 34), fill=pal["accent"])
    text = headline if headline and headline.strip().lower() != name.strip().lower() else (subline or "")
    if text:
        f2, l2, lh2 = fit(d, text, "semi", W - 2 * pad, 120, 42, 26, 1.25, 2)
        y = draw_lines(d, (pad, y + 48), l2, f2, lh2, pal["text"])
    if subline and text != subline:
        f3, l3, lh3 = fit(d, subline, "sans", W - 2 * pad, 70, 30, 22, 1.3, 2)
        y = draw_lines(d, (pad, y + 8), l3, f3, lh3, pal["muted"])
    x, yb = pad, H - pad - 40
    ft = font("monob", 22)
    for t in topics[:6]:
        w = d.textlength(t, font=ft) + 32
        if x + w > W - pad:
            break
        d.rounded_rectangle((x, yb, x + w, yb + 40), 20, outline=pal["accent"], width=2)
        d.text((x + 16, yb + 8), t, font=ft, fill=pal["accent"])
        x += w + 12
    return _png(img)


def thumb(png: bytes, width: int) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    im.thumbnail((width, width * 4))
    return _png(im)
