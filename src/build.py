#!/usr/bin/env python3
"""Builds pencilsdowngame.com.

    python3 src/build.py            # from the repo root; writes the site to the repo root

Inputs (all under src/):
  i18n/<lang>.json      site strings, one file per language (en is the reference)
  i18n/schools.json     school names and kinds, taken from the game's localization
  legal/*.md            privacy policy and terms (EN and TR are authoritative; the rest are translations)
  assets/art/*.png      game art (renders, icon)
  assets/screens/<lang>/NN-name.png   in-game screenshots (optional; see README.md)

Needs Python 3.9+ and Pillow (pip install pillow). Images are only re-encoded when their source changed.
No JavaScript is produced. The only external request a page makes is Google Fonts (not on Japanese pages).
"""
import hashlib
import html
import json
import os
import re
import shutil
import sys

# ============================================================== configuration

SITE = "https://pencilsdowngame.com"
GAME = "Pencils Down: Exam Proctor"
WORDMARK = "Pencils Down"
EMAIL = "support@pencilsdowngame.com"
OWNER = "Arda Kabadayı"
YEAR = "2026"

# Store links. Leave None while the game is not live: the buttons render as "Coming soon".
# Set a URL to turn the button into a real link. If an official badge file exists in
# src/static/badges/ (see README.md) the build uses it for that store; otherwise a styled button.
STORE_LINKS = {
    "android": None,  # e.g. "https://play.google.com/store/apps/details?id=com.example.pencilsdown"
    "ios": None,      # e.g. "https://apps.apple.com/app/id0000000000"
}

# Languages: code (hreflang / file name), URL folder, Open Graph locale.
LANGS = [
    ("en", "", "en_US"),
    ("tr", "tr/", "tr_TR"),
    ("es", "es/", "es_ES"),
    ("fr", "fr/", "fr_FR"),
    ("ja", "ja/", "ja_JP"),
    ("pt-BR", "pt-br/", "pt_BR"),
    ("ru", "ru/", "ru_RU"),
]
DEFAULT_LANG = "en"
AUTHORITATIVE_LEGAL = {"en", "tr"}   # the others show "translation for convenience; English prevails"

PAGES = ["home", "support", "privacy", "terms"]
PAGE_PATH = {"home": "", "support": "support/", "privacy": "privacy/", "terms": "terms/"}
LEGAL_FILE = {"privacy": "PRIVACY-POLICY", "terms": "TERMS-OF-USE"}

# Screenshots. Real captures go in src/assets/screens/<lang>/NN-name.png (portrait, e.g. 1080x2340);
# a language without its own folder uses en/. They are shown in file-name order. The caption comes from
# the i18n key SCREEN_CAPTIONS[name] (name = file name without "NN-" and extension); no key, no caption.
SCREEN_CAPTIONS = {
    "room": "shot_room", "exam": "shot_room", "exam-room": "shot_room", "classroom": "shot_room",
    "hub": "shot_career", "career": "shot_career", "schools": "shot_schools", "school": "shot_schools",
    "wardrobe": "shot_wardrobe", "shop": "shot_shop", "store": "shot_shop",
}
# Until real screenshots exist, these art compositions stand in (scene on top, item tiles below).
FALLBACK_SCREENS = [
    ("01-room", "scene_title_dark", ["tile_signal_detector", "tile_pills", "tile_coins_small",
                                     "tile_coins_medium", "tile_badge_gold", "tile_glasses_round"], "shot_room"),
    ("02-schools", "scene_kingsley_dark", ["tile_crest_maple", "tile_crest_riverside", "tile_crest_standard",
                                           "tile_crest_elite", "tile_crest_state-university", "tile_crest_national"], "shot_schools"),
    ("03-wardrobe", "scene_maple_dark", ["tile_top_blazer", "tile_top_cardigan", "tile_top_tweed",
                                         "tile_hat_bucket", "tile_glasses_round", "tile_wrist_watch"], "shot_wardrobe"),
    ("04-shop", "scene_brightpath_dark", ["tile_coins_small", "tile_coins_medium", "tile_coins_large",
                                          "tile_signal_detector", "tile_pills", "tile_badge_supporter"], "shot_shop"),
]

FONTS_CSS = ("https://fonts.googleapis.com/css2?family=Onest:wght@400;500;700"
             "&family=Unbounded:wght@600;700&display=swap")
NO_WEBFONT_LANGS = {"ja"}   # Japanese uses the system's Japanese fonts (no download)

# ============================================================== paths and helpers

SRC = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(SRC)
ART = os.path.join(SRC, "assets", "art")
IMG_OUT = os.path.join(OUT, "assets", "img")

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required: python3 -m pip install pillow")

LANG_CODES = [l for l, _, _ in LANGS]
LANG_DIR = {l: d for l, d, _ in LANGS}
LANG_OG = {l: o for l, _, o in LANGS}

T = {}
for code in LANG_CODES:
    with open(os.path.join(SRC, "i18n", code + ".json"), encoding="utf-8") as f:
        T[code] = json.load(f)
with open(os.path.join(SRC, "i18n", "schools.json"), encoding="utf-8") as f:
    SCHOOLS = json.load(f)["schools"]


def esc(s):
    return html.escape(s, quote=True)


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s)


def write(rel_path, text):
    full = os.path.join(OUT, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def page_url(lang, page):
    return SITE + "/" + LANG_DIR[lang] + PAGE_PATH[page]


def depth(lang, page):
    return (1 if LANG_DIR[lang] else 0) + (1 if PAGE_PATH[page] else 0)


class Ctx:
    """Everything a page needs to build links relative to itself."""

    def __init__(self, lang, page, absolute=False):
        self.lang, self.page = lang, page
        self.t = T[lang]
        self.root = "/" if absolute else ("../" * depth(lang, page))

    def href(self, lang, page):
        target = LANG_DIR[lang] + PAGE_PATH[page]
        if self.root == "/":
            return "/" + target
        out = self.root + target
        return out or "./"

    def asset(self, path):
        return self.root + "assets/" + path

    def s(self, key, **kw):
        val = self.t.get(key)
        if val is None or (val == "" and key != "legal_translation_notice"):
            val = T[DEFAULT_LANG][key]
        base = dict(email=EMAIL, privacy=self.href(self.lang, "privacy"), support=self.href(self.lang, "support"),
                    terms=self.href(self.lang, "terms"), home=self.href(self.lang, "home"))
        base.update(kw)
        return re.sub(r"\{(\w+)\}", lambda m: str(base.get(m.group(1), m.group(0))), val)


# ============================================================== images

def _stamp(src_paths, out_path):
    """True when out_path is missing or older than any source."""
    if not os.path.exists(out_path):
        return True
    t = os.path.getmtime(out_path)
    return any(os.path.getmtime(p) > t for p in src_paths)


IMAGES = {}   # name -> (w, h, [widths], has_alpha)


def encode(name, im, widths, sources, quality=80, alpha=False):
    """Writes assets/img/<name>-<w>.webp and .jpg (or .png when alpha) for each width."""
    os.makedirs(IMG_OUT, exist_ok=True)
    out_widths = []
    for w in widths:
        w = min(w, im.width)
        if w in out_widths:
            continue
        out_widths.append(w)
        h = round(im.height * w / im.width)
        webp = os.path.join(IMG_OUT, f"{name}-{w}.webp")
        fb = os.path.join(IMG_OUT, f"{name}-{w}." + ("png" if alpha else "jpg"))
        if _stamp(sources, webp) or _stamp(sources, fb):
            r = im.resize((w, h), Image.LANCZOS) if w != im.width else im.copy()
            if alpha:
                r.save(webp, "WEBP", quality=quality, method=6)
                r.save(fb, "PNG", optimize=True)
            else:
                r = r.convert("RGB")
                r.save(webp, "WEBP", quality=quality, method=6)
                r.save(fb, "JPEG", quality=quality + 2, optimize=True, progressive=True)
    IMAGES[name] = (im.width, im.height, out_widths, alpha)


def art(name):
    return os.path.join(ART, name + ".png")


def prepare_art(name, widths, quality=80):
    p = art(name)
    im = Image.open(p)
    im.load()
    alpha = im.mode in ("RGBA", "LA") and im.getextrema()[3][0] < 255
    encode(name, im.convert("RGBA" if alpha else "RGB"), widths, [p], quality, alpha)


def srcset(ctx, name, ext):
    _, _, widths, _ = IMAGES[name]
    return ", ".join(f"{ctx.asset('img/%s-%d.%s' % (name, w, ext))} {w}w" for w in widths)


def picture(ctx, name, alt, sizes, lazy=True, dark=None, cls="", fetch_high=False):
    """<picture> with WebP + JPEG/PNG fallback. dark: an image name used when the system is in dark mode."""
    w, h, widths, alpha = IMAGES[name]
    fb = "png" if alpha else "jpg"
    parts = ["<picture>"]
    if dark:
        parts.append(f'<source media="(prefers-color-scheme: dark)" type="image/webp" srcset="{srcset(ctx, dark, "webp")}" sizes="{sizes}">')
        dfb = "png" if IMAGES[dark][3] else "jpg"
        parts.append(f'<source media="(prefers-color-scheme: dark)" srcset="{srcset(ctx, dark, dfb)}" sizes="{sizes}">')
    parts.append(f'<source type="image/webp" srcset="{srcset(ctx, name, "webp")}" sizes="{sizes}">')
    mid = widths[min(1, len(widths) - 1)]
    attrs = f'src="{ctx.asset("img/%s-%d.%s" % (name, mid, fb))}" srcset="{srcset(ctx, name, fb)}" sizes="{sizes}" width="{w}" height="{h}" alt="{esc(alt)}"'
    attrs += ' loading="lazy" decoding="async"' if lazy else (' fetchpriority="high"' if fetch_high else "")
    if cls:
        attrs += f' class="{cls}"'
    parts.append(f"<img {attrs}></picture>")
    return "".join(parts)


def build_fallback_screen(name, scene, tiles):
    """A portrait art composition standing in for a screenshot: scene on top, item tiles below."""
    W, H = 600, 1300
    sources = [art(scene)] + [art(t) for t in tiles]
    canvas = Image.new("RGB", (W, H), (9, 14, 28))
    sc = Image.open(art(scene)).convert("RGB")
    top_h = 720
    ratio = W / top_h
    cw = min(sc.width, round(sc.height * ratio))
    ch = round(cw / ratio)
    x0 = (sc.width - cw) // 2
    y0 = max(0, (sc.height - ch) // 2)
    sc = sc.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, top_h), Image.LANCZOS)
    canvas.paste(sc, (0, 0))
    # fade the scene into the panel
    fade = Image.new("L", (1, 160))
    for y in range(160):
        fade.putpixel((0, y), int(255 * (y / 159) ** 1.4))
    fade = fade.resize((W, 160))
    canvas.paste(Image.new("RGB", (W, 160), (9, 14, 28)), (0, top_h - 160), fade)
    # tiles, 2 columns x 3 rows, rounded
    gap, margin = 18, 30
    tw = (W - 2 * margin - gap) // 2
    th = round(tw * 230 / 480)
    block = 3 * th + 2 * gap
    y = top_h - 40 + (H - (top_h - 40) - block) // 2 - 10
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, th - 1), 22, fill=255)
    for i, t in enumerate(tiles[:6]):
        tile = Image.open(art(t)).convert("RGB").resize((tw, th), Image.LANCZOS)
        cx = margin + (i % 2) * (tw + gap)
        cy = y + (i // 2) * (th + gap)
        canvas.paste(tile, (cx, cy), mask)
    encode("screen-" + name, canvas, [300, 600], sources, quality=78)


def prepare_screens():
    """Returns {lang: [(image name, caption key or None)]}."""
    base = os.path.join(SRC, "assets", "screens")
    by_folder = {}
    for code in LANG_CODES:
        folder = os.path.join(base, code)
        files = sorted(f for f in os.listdir(folder) if f.lower().endswith((".png", ".jpg", ".jpeg"))) if os.path.isdir(folder) else []
        items = []
        for f in files:
            stem = os.path.splitext(f)[0]
            short = re.sub(r"^\d+[-_ ]*", "", stem).lower()
            name = f"shot-{code.lower()}-{stem}"
            p = os.path.join(folder, f)
            im = Image.open(p).convert("RGB")
            encode(name, im, [300, 600], [p], quality=80)
            items.append((name, SCREEN_CAPTIONS.get(short)))
        if items:
            by_folder[code] = items
    result, fallback = {}, None
    for code in LANG_CODES:
        if code in by_folder:
            result[code] = (by_folder[code], True)
        elif DEFAULT_LANG in by_folder:
            result[code] = (by_folder[DEFAULT_LANG], True)
        else:
            if fallback is None:
                fallback = []
                for name, scene, tiles, cap in FALLBACK_SCREENS:
                    build_fallback_screen(name, scene, tiles)
                    fallback.append(("screen-" + name, cap))
            result[code] = (fallback, False)
    return result


def prepare_icons():
    p = art("app-icon")
    icon = Image.open(p).convert("RGB")
    encode("app-icon", icon, [96, 192, 384], [p], quality=82)
    ico_dir = os.path.join(OUT, "assets", "icons")
    os.makedirs(ico_dir, exist_ok=True)
    out = os.path.join(OUT, "favicon.ico")
    if _stamp([p], out):
        # favicon: rounded so it reads as an app icon in tabs
        def rounded(size):
            im = icon.resize((size, size), Image.LANCZOS).convert("RGBA")
            m = Image.new("L", (size * 4, size * 4), 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), size * 4 // 5, fill=255)
            im.putalpha(m.resize((size, size), Image.LANCZOS))
            return im
        rounded(48).save(out, sizes=[(16, 16), (32, 32), (48, 48)])
        rounded(32).save(os.path.join(ico_dir, "favicon-32.png"), optimize=True)
        rounded(96).save(os.path.join(ico_dir, "favicon-96.png"), optimize=True)
        icon.resize((180, 180), Image.LANCZOS).save(os.path.join(ico_dir, "apple-touch-icon.png"), optimize=True)
        icon.resize((192, 192), Image.LANCZOS).save(os.path.join(ico_dir, "icon-192.png"), optimize=True)
        icon.resize((512, 512), Image.LANCZOS).save(os.path.join(ico_dir, "icon-512.png"), optimize=True)


FONT_CANDIDATES = {
    "latin_black": [os.path.join(SRC, "fonts", "Inter.ttf"), os.path.expanduser("~/Library/Fonts/Inter-VariableFont_opsz,wght.ttf"),
                    "/System/Library/Fonts/Supplemental/Arial Black.ttf"],
    "ja_heavy": ["/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc"],
    "ja_bold": ["/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"],
}


def _font(kind, size, weight=None):
    for p in FONT_CANDIDATES[kind]:
        if os.path.exists(p):
            f = ImageFont.truetype(p, size)
            if weight:
                try:
                    f.set_variation_by_axes([32, weight])
                except Exception:
                    pass
            return f
    return None


def prepare_og():
    """1200x630 share image per language: art, icon, wordmark, subtitle, tagline."""
    og_dir = os.path.join(OUT, "assets", "og")
    os.makedirs(og_dir, exist_ok=True)
    if _font("latin_black", 10) is None:
        print("  (no font for share images; keeping the committed ones)")
        return
    W, H = 1200, 630
    srcs = [art("scene_title_dark"), art("app-icon"), os.path.join(SRC, "i18n", "en.json")]
    for code in LANG_CODES:
        out = os.path.join(og_dir, f"og-{code.lower()}.jpg")
        if not _stamp(srcs + [os.path.join(SRC, "i18n", code + ".json"), __file__], out):
            continue
        t = T[code]
        canvas = Image.new("RGB", (W, H), (7, 11, 22))
        sc = Image.open(art("scene_title_dark")).convert("RGB")
        sc = sc.resize((round(sc.width * H / sc.height * 1.0), H), Image.LANCZOS)
        x = W - sc.width + 140
        canvas.paste(sc, (x, 0))
        # left fade for text
        grad = Image.new("L", (W, 1))
        for i in range(W):
            f = (i - x) / 420
            v = 255 if f <= 0 else (int(255 * (1 - f) ** 1.6) if f < 1 else 0)
            grad.putpixel((i, 0), v)
        grad = grad.resize((W, H))
        canvas.paste(Image.new("RGB", (W, H), (7, 11, 22)), (0, 0), grad)
        d = ImageDraw.Draw(canvas)
        # gold rule along the top
        d.rectangle((0, 0, W, 8), fill=(233, 178, 58))
        icon = Image.open(art("app-icon")).convert("RGB").resize((132, 132), Image.LANCZOS)
        m = Image.new("L", (528, 528), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, 527, 527), 120, fill=255)
        canvas.paste(icon, (72, 78), m.resize((132, 132), Image.LANCZOS))
        title = _font("latin_black", 96, 900)
        d.text((68, 240), WORDMARK.upper(), font=title, fill=(243, 247, 255))
        sub_txt = t.get("game_subtitle") or T["en"]["game_subtitle"]
        tag_txt = t.get("tagline") or T["en"]["tagline"]
        if code == "ja":
            sub = _font("ja_heavy", 50)
            tag = _font("ja_bold", 38)
        else:
            sub = _font("latin_black", 50, 800)
            tag = _font("latin_black", 38, 600)
        d.text((72, 360), sub_txt, font=sub, fill=(233, 178, 58))
        # tagline may need two lines
        words, lines, cur = tag_txt.split(" "), [], ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if d.textlength(trial, font=tag) > 640 and cur:
                lines.append(cur)
                cur = wd
            else:
                cur = trial
        lines.append(cur)
        y = 446
        for ln in lines:
            d.text((72, y), ln, font=tag, fill=(214, 224, 245))
            y += 50
        d.text((72, H - 58), "pencilsdowngame.com", font=_font("latin_black", 24, 600) if code != "ja" else _font("ja_bold", 24), fill=(150, 168, 205))
        canvas.save(out, "JPEG", quality=86, optimize=True, progressive=True)


# ============================================================== markdown subset (legal texts)

def md_inline(text):
    text = text.replace("&", "&amp;")
    text = re.sub(r"<(https?://[^>\s]+)>", lambda m: '<a href="%s">%s</a>' % (m.group(1), m.group(1)), text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w.@/:])(" + re.escape(EMAIL) + r")(?![\w])", r'<a href="mailto:\1">\1</a>', text)
    return text


def md_slug(text, used):
    s = strip_tags(text).lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s.strip()) or "section"
    base, n = s, 2
    while s in used:
        s = f"{base}-{n}"
        n += 1
    used.add(s)
    return s


def md_parse(lines, used):
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        s = line.strip()
        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            text = md_inline(s[level:].strip())
            out.append(("h%d" % level, text, md_slug(text, used)))
            i += 1
        elif s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
            t = ['<div class="table"><table><thead><tr>']
            t += ['<th scope="col">%s</th>' % md_inline(c) for c in head]
            t.append("</tr></thead><tbody>")
            for r in body:
                t.append("<tr>" + "".join('<td data-label="%s">%s</td>' % (esc(re.sub(r"\*", "", head[k])), md_inline(c))
                                          for k, c in enumerate(r)) + "</tr>")
            t.append("</tbody></table></div>")
            out.append(("t", "".join(t), None))
        elif s.startswith("- "):
            items, cur = [], None
            while i < len(lines):
                ln = lines[i]
                if ln.startswith("- "):
                    cur = [ln[2:]]
                    items.append(cur)
                    i += 1
                elif not ln.strip():
                    j = i
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines) and (lines[j].startswith("  ") or lines[j].startswith("- ")):
                        cur.append("")
                        i += 1
                    else:
                        break
                elif len(ln) - len(ln.lstrip(" ")) >= 2:
                    cur.append(ln[2:])
                    i += 1
                else:
                    break
            lis = []
            for it in items:
                blocks = md_parse(it, used)
                if len(blocks) == 1 and blocks[0][0] == "p":
                    lis.append("<li>%s</li>" % blocks[0][1][3:-4])
                else:
                    lis.append("<li>%s</li>" % "".join(render_block(b) for b in blocks))
            out.append(("l", "<ul>%s</ul>" % "".join(lis), None))
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not (para and lines[i].lstrip(" ")[:1] in ("#", "|") or (para and lines[i].lstrip(" ").startswith("- "))):
                para.append(lines[i])
                i += 1
            parts = []
            for k, p in enumerate(para):
                brk = p.endswith("  ") and k < len(para) - 1
                parts.append(md_inline(p.strip()) + ("<br>" if brk else ""))
            out.append(("p", "<p>%s</p>" % "\n".join(parts), None))
    return out


def render_block(b):
    kind, content, anchor = b
    if kind.startswith("h"):
        return '<%s id="%s">%s</%s>' % (kind, anchor, content, kind)
    return content


def load_legal(page, lang):
    name = LEGAL_FILE[page] + ("" if lang == "en" else "." + lang) + ".md"
    path = os.path.join(SRC, "legal", name)
    if not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8").read()
    text = re.sub(r"<!--.*?-->\s*", "", text, flags=re.S)
    blocks = md_parse(text.splitlines(), set())
    return blocks


# ============================================================== icons (inline SVG, decorative)

def svg(path, size=20, cls="i", extra=""):
    return (f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"{extra}>{path}</svg>')


I_GLOBE = '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'
I_CHEV = '<path d="m6 9 6 6 6-6"/>'
I_MENU = '<path d="M4 7h16M4 12h16M4 17h16"/>'
I_CHECK = '<path d="m5 12 4.5 4.5L19 7"/>'
I_MAIL = '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>'
I_ARROW = '<path d="M5 12h14M13 6l6 6-6 6"/>'
I_PLAY = '<path d="M7 4.5v15l12-7.5z"/>'
I_PHONE = '<rect x="6.5" y="2.5" width="11" height="19" rx="2.5"/><path d="M11 18.5h2"/>'
I_RESTORE = '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>'
I_SHIELD = '<path d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6z"/><path d="m9 12 2 2 4-4"/>'
I_TRASH = '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>'
I_REFUND = '<path d="M4 7h13a3 3 0 0 1 0 6H8"/><path d="m8 3-4 4 4 4"/><path d="M4 17h16"/>'
I_INFO = '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>'
I_PLUS = '<path d="M12 5v14M5 12h14"/>'


# ============================================================== page shell

def head_meta(ctx, title, desc, page, og_type="website", noindex=False, extra=""):
    lang = ctx.lang
    canonical = page_url(lang, page) if page else None
    h = [f'<meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
         f"<title>{esc(title)}</title>",
         f'<meta name="description" content="{esc(desc)}">',
         ('<meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'none\'; '
          "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; "
          "connect-src 'none'; base-uri 'self'; form-action 'none'; object-src 'none'\">"),
         '<meta name="referrer" content="strict-origin-when-cross-origin">',
         '<meta name="color-scheme" content="light dark">',
         '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#f5f7fb">',
         '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#070b16">']
    if noindex:
        h.append('<meta name="robots" content="noindex">')
    if canonical:
        h.append(f'<link rel="canonical" href="{canonical}">')
        for code in LANG_CODES:
            h.append(f'<link rel="alternate" hreflang="{code}" href="{page_url(code, page)}">')
        h.append(f'<link rel="alternate" hreflang="x-default" href="{page_url(DEFAULT_LANG, page)}">')
    og_img = SITE + "/assets/og/og-%s.jpg" % lang.lower()
    h += [f'<meta property="og:type" content="{og_type}">',
          f'<meta property="og:site_name" content="{esc(GAME)}">',
          f'<meta property="og:title" content="{esc(title)}">',
          f'<meta property="og:description" content="{esc(desc)}">',
          f'<meta property="og:locale" content="{LANG_OG[lang]}">']
    h += [f'<meta property="og:locale:alternate" content="{LANG_OG[c]}">' for c in LANG_CODES if c != lang]
    if canonical:
        h.append(f'<meta property="og:url" content="{canonical}">')
    h += [f'<meta property="og:image" content="{og_img}">',
          '<meta property="og:image:width" content="1200">', '<meta property="og:image:height" content="630">',
          f'<meta property="og:image:alt" content="{esc(GAME + " · " + strip_tags(ctx.s("tagline")))}">',
          '<meta name="twitter:card" content="summary_large_image">',
          f'<meta name="twitter:title" content="{esc(title)}">',
          f'<meta name="twitter:description" content="{esc(desc)}">',
          f'<meta name="twitter:image" content="{og_img}">']
    root = ctx.root or ""
    h += [f'<link rel="icon" href="{root}favicon.ico" sizes="48x48">',
          f'<link rel="icon" type="image/png" sizes="96x96" href="{root}assets/icons/favicon-96.png">',
          f'<link rel="apple-touch-icon" href="{root}assets/icons/apple-touch-icon.png">',
          f'<link rel="manifest" href="{root}site.webmanifest">']
    if lang not in NO_WEBFONT_LANGS:
        h += ['<link rel="preconnect" href="https://fonts.googleapis.com">',
              '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
              f'<link rel="stylesheet" href="{FONTS_CSS.replace("&", "&amp;")}" referrerpolicy="no-referrer">']
    h.append(f'<link rel="stylesheet" href="{root}assets/site.css?v={CSS_VERSION}">')
    h.append(extra)
    return "\n".join(x for x in h if x)


def lang_switcher(ctx, cls="lang"):
    items = []
    for code in LANG_CODES:
        cur = ' aria-current="true"' if code == ctx.lang else ""
        items.append(f'<li><a href="{ctx.href(code, ctx.page)}" hreflang="{code}" lang="{code}"{cur}>'
                     f'{esc(T[code]["lang_name"])}{svg(I_CHECK, 16, "i tick") if code == ctx.lang else ""}</a></li>')
    return (f'<details class="{cls}"><summary aria-label="{esc(ctx.s("lang_label"))}: {esc(ctx.t["lang_name"])}">'
            f'{svg(I_GLOBE, 18)}<span>{esc(ctx.t["lang_name"])}</span>{svg(I_CHEV, 16, "i chev")}</summary>'
            f'<ul role="list">{"".join(items)}</ul></details>')


def nav_links(ctx):
    home = ctx.href(ctx.lang, "home")
    here_home = ctx.page == "home" and ctx.root != "/"
    anchor = (lambda a: "#" + a) if here_home else (lambda a: home + "#" + a if home != "./" else "./#" + a)
    links = [(anchor("game"), ctx.s("nav_features"), False), (anchor("screens"), ctx.s("nav_screens"), False),
             (anchor("faq"), ctx.s("nav_faq"), False),
             (ctx.href(ctx.lang, "support"), ctx.s("nav_support"), ctx.page == "support")]
    return "".join(f'<li><a href="{h}"{" aria-current=\"page\"" if cur else ""}>{esc(t)}</a></li>' for h, t, cur in links)


def header(ctx):
    home = ctx.href(ctx.lang, "home")
    icon = picture(ctx, "app-icon", "", "36px", lazy=False, cls="brand-icon")
    return f"""<a class="skip" href="#main">{esc(ctx.s("skip"))}</a>
<header class="site-header"><div class="wrap bar">
<a class="brand" href="{home}" aria-label="{esc(GAME)}: {esc(ctx.s("nav_home"))}">{icon}<span class="brand-name">{WORDMARK}</span></a>
<nav class="primary" aria-label="{esc(ctx.s("menu"))}"><ul role="list">{nav_links(ctx)}</ul></nav>
<div class="bar-end">
{lang_switcher(ctx)}
<details class="menu"><summary aria-label="{esc(ctx.s("menu"))}">{svg(I_MENU, 22)}</summary>
<nav aria-label="{esc(ctx.s("menu"))}"><ul role="list">{nav_links(ctx)}</ul></nav></details>
</div>
</div></header>"""


def store_buttons(ctx, cls=""):
    out = []
    for key, label, prefix_key, icon in (("android", "Google Play", "store_get_android", I_PLAY),
                                         ("ios", "App Store", "store_get_ios", I_PHONE)):
        url = STORE_LINKS.get(key)
        if url:
            badge = find_badge(key, ctx.lang)
            if badge:
                rel_path, w, h = badge
                out.append(f'<a class="store-badge" href="{esc(url)}" rel="noopener"><img src="{ctx.root}{rel_path}" '
                           f'width="{w}" height="{h}" alt="{esc(ctx.s(prefix_key))} {label}"></a>')
            else:
                out.append(f'<a class="store" href="{esc(url)}" rel="noopener">{svg(icon, 22)}'
                           f'<span><small>{esc(ctx.s(prefix_key))}</small><b>{label}</b></span></a>')
        else:
            out.append(f'<span class="store soon" role="note" aria-label="{label}: {esc(ctx.s("store_coming_soon"))}">'
                       f'{svg(icon, 22)}<span><b>{label}</b><small>{esc(ctx.s("store_coming_soon"))}</small></span></span>')
    return f'<div class="stores {cls}">{"".join(out)}</div>'


def find_badge(store, lang):
    """src/static/badges/<store>/<lang>.(svg|png), falling back to en. Copied to assets/badges/."""
    folder = os.path.join(SRC, "static", "badges", "google-play" if store == "android" else "app-store")
    for code in (lang, "en"):
        for ext in ("svg", "png"):
            p = os.path.join(folder, f"{code}.{ext}")
            if os.path.exists(p):
                rel = f"assets/badges/{os.path.basename(folder)}-{code}.{ext}"
                os.makedirs(os.path.join(OUT, "assets", "badges"), exist_ok=True)
                shutil.copyfile(p, os.path.join(OUT, rel))
                if ext == "png":
                    with Image.open(p) as im:
                        w, h = im.size
                    return rel, round(w * 54 / h), 54
                return rel, 180, 54
    return None


def footer(ctx):
    langs = "".join(f'<li><a href="{ctx.href(c, ctx.page)}" hreflang="{c}" lang="{c}"'
                    f'{" aria-current=\"true\"" if c == ctx.lang else ""}>{esc(T[c]["lang_name"])}</a></li>' for c in LANG_CODES)
    links = [(ctx.href(ctx.lang, "home"), ctx.s("nav_home")), (ctx.href(ctx.lang, "support"), ctx.s("nav_support")),
             (ctx.href(ctx.lang, "privacy"), ctx.s("nav_privacy_long")), (ctx.href(ctx.lang, "terms"), ctx.s("nav_terms"))]
    links_html = "".join(f'<li><a href="{h}">{esc(t)}</a></li>' for h, t in links)
    return f"""<footer class="site-footer"><div class="wrap">
<div class="foot-grid">
<div class="foot-brand">
<p class="foot-name">{picture(ctx, "app-icon", "", "44px", lazy=True, cls="brand-icon")}<span>{GAME}</span></p>
<p class="foot-tag">{esc(ctx.s("footer_tagline"))}</p>
{store_buttons(ctx, "small")}
</div>
<nav aria-label="{esc(ctx.s("footer_links"))}"><h2 class="foot-h">{esc(ctx.s("footer_links"))}</h2><ul role="list">{links_html}</ul></nav>
<nav aria-label="{esc(ctx.s("lang_label"))}"><h2 class="foot-h">{esc(ctx.s("lang_label"))}</h2><ul role="list" class="foot-langs">{langs}</ul></nav>
<div><h2 class="foot-h">{esc(ctx.s("footer_contact"))}</h2><p><a class="foot-mail" href="mailto:{EMAIL}">{EMAIL}</a></p></div>
</div>
<p class="legal-line">© {YEAR} {OWNER}. {esc(ctx.s("footer_rights"))}</p>
</div></footer>"""


def document(ctx, title, desc, page, body, page_cls, og_type="website", noindex=False, extra_head=""):
    return f"""<!doctype html>
<html lang="{ctx.lang}" dir="ltr">
<head>
{head_meta(ctx, title, desc, page, og_type, noindex, extra_head)}
</head>
<body class="{page_cls}">
{header(ctx)}
<main id="main" tabindex="-1">
{body}
</main>
{footer(ctx)}
</body>
</html>
"""


# ============================================================== pages

def home_page(ctx, screens):
    s = ctx.s
    hero_art = picture(ctx, "scene_title_light", s("hero_art_alt"), "(min-width: 960px) 46vw, 100vw",
                       lazy=False, dark="scene_title_dark", fetch_high=True)
    icon = picture(ctx, "app-icon", s("icon_alt"), "(min-width: 960px) 112px, 84px", lazy=False, cls="hero-icon-img")
    facts = "".join(f"<li>{svg(I_CHECK, 18)}{esc(s(k))}</li>" for k in ("fact_ads", "fact_free", "fact_offline", "fact_langs"))

    hero = f"""<section class="hero" aria-labelledby="hero-title"><div class="wrap hero-grid">
<div class="hero-copy">
<p class="kicker">{esc(s("hero_kicker"))}</p>
<h1 id="hero-title"><span class="wordmark">{WORDMARK}</span><span class="subtitle">{esc(s("game_subtitle"))}</span></h1>
<p class="tagline">{esc(s("tagline"))}</p>
<p class="pitch">{s("hero_pitch")}</p>
{store_buttons(ctx)}
<ul class="facts" role="list">{facts}</ul>
</div>
<figure class="hero-art"><div class="frame">{hero_art}</div><div class="hero-icon">{icon}</div></figure>
</div></section>"""

    def feature(n, art_html, flip=False, wide=False):
        return f"""<article class="feature{' flip' if flip else ''}{' wide' if wide else ''}">
<div class="feature-copy"><p class="num" aria-hidden="true">0{n}</p><h3>{esc(s(f"f{n}_title"))}</h3><p>{s(f"f{n}_text")}</p></div>
<div class="feature-art">{art_html}</div>
</article>"""

    # What a supervisor notices: three desk-level props, stacked like evidence strips.
    strips = "".join(f'<li>{picture(ctx, p, "", "(min-width: 960px) 560px, 100vw")}</li>'
                     for p in ("prop_document", "prop_person", "prop_envelope"))
    f1_art = f'<ul class="art-card strips" role="list">{strips}</ul>'
    f2_art = f'<div class="art-card prop">{picture(ctx, "prop_note", s("f2_alt"), "(min-width: 960px) 560px, 100vw")}</div>'

    school_cards = []
    for i, sc in enumerate(SCHOOLS, 1):
        name = sc["name"].get(ctx.lang) or sc["name"]["en"]
        kind = sc["kind"].get(ctx.lang) or sc["kind"]["en"]
        pic = picture(ctx, f"scene_{sc['art']}_light", "", "(min-width: 960px) 280px, (min-width: 600px) 45vw, 92vw",
                      dark=f"scene_{sc['art']}_dark")
        school_cards.append(f'<li class="school"><div class="school-art">{pic}</div><div class="school-txt">'
                            f'<span class="school-n" aria-hidden="true">{i}</span><h4>{esc(name)}</h4><p>{esc(kind)}</p></div></li>')

    wardrobe = "".join(f'<li>{picture(ctx, t, "", "(min-width: 960px) 120px, 30vw")}</li>' for t in
                       ("tile_top_blazer", "tile_top_cardigan", "tile_hat_bucket", "tile_glasses_round", "tile_wrist_watch", "tile_badge_gold"))

    features = f"""<section class="features" id="game" aria-labelledby="game-title"><div class="wrap">
<header class="section-head"><p class="kicker">{esc(s("features_kicker"))}</p><h2 id="game-title">{esc(s("features_title"))}</h2></header>
{feature(1, f1_art)}
{feature(2, f2_art, flip=True)}
<article class="feature schools-block">
<div class="feature-copy"><p class="num" aria-hidden="true">03</p><h3>{esc(s("f3_title"))}</h3><p>{s("f3_text")}</p></div>
<ol class="schools" role="list" aria-label="{esc(s("schools_title"))}">{"".join(school_cards)}</ol>
</article>
<div class="trio">
<article class="card-feature"><div class="card-art duo">{picture(ctx, "tile_signal_detector", s("f4_alt"), "(min-width: 960px) 180px, 45vw")}{picture(ctx, "tile_pills", "", "(min-width: 960px) 180px, 45vw")}</div>
<p class="num" aria-hidden="true">04</p><h3>{esc(s("f4_title"))}</h3><p>{s("f4_text")}</p></article>
<article class="card-feature"><ul class="card-art mosaic" role="list" aria-label="{esc(s("f5_alt"))}">{wardrobe}</ul>
<p class="num" aria-hidden="true">05</p><h3>{esc(s("f5_title"))}</h3><p>{s("f5_text")}</p></article>
<article class="card-feature"><div class="card-art single">{picture(ctx, "tile_coins_large", s("f6_alt"), "(min-width: 960px) 360px, 92vw")}</div>
<p class="num" aria-hidden="true">06</p><h3>{esc(s("f6_title"))}</h3><p>{s("f6_text")}</p></article>
</div>
</div></section>"""

    items, real = screens[ctx.lang]
    phones = []
    for name, cap_key in items:
        cap = s(cap_key) if cap_key else ""
        pic = picture(ctx, name, cap or GAME, "(min-width: 960px) 250px, 62vw")
        phones.append(f'<li class="shot"><div class="phone">{pic}</div>{f"<p>{esc(cap)}</p>" if cap else ""}</li>')
    note = "" if real else f'<p class="screens-note">{esc(s("screens_note"))}</p>'
    screens_html = f"""<section class="screens" id="screens" aria-labelledby="screens-title"><div class="wrap">
<header class="section-head"><p class="kicker">{esc(s("screens_kicker"))}</p><h2 id="screens-title">{esc(s("screens_title"))}</h2>{note}</header>
<ul class="shots" role="list">{"".join(phones)}</ul>
</div></section>"""

    qa = []
    for k in ("ads", "free", "net", "langs", "devices", "help"):
        qa.append(f'<details class="qa"{" open" if k == "ads" else ""}><summary><span>{esc(s(f"faq_{k}_q"))}</span>{svg(I_PLUS, 20, "i plus")}</summary>'
                  f'<div class="qa-a"><p>{s(f"faq_{k}_a")}</p></div></details>')
    faq = f"""<section class="faq" id="faq" aria-labelledby="faq-title"><div class="wrap faq-grid">
<header class="section-head"><p class="kicker">{esc(s("faq_kicker"))}</p><h2 id="faq-title">{esc(s("faq_title"))}</h2></header>
<div class="qas">{"".join(qa)}</div>
</div></section>"""

    cta = f"""<section class="cta" aria-labelledby="cta-title"><div class="wrap cta-inner">
<h2 id="cta-title">{esc(s("cta_title"))}</h2>
<p class="tagline">{esc(s("tagline"))}</p>
{store_buttons(ctx)}
<p class="cta-note">{esc(s("store_soon_note"))}</p>
</div></section>"""

    ld = {"@context": "https://schema.org", "@type": "VideoGame", "name": GAME, "url": page_url(ctx.lang, "home"),
          "description": strip_tags(s("meta_home_desc")), "inLanguage": LANG_CODES, "genre": "Simulation",
          "gamePlatform": ["Android", "iOS"], "image": SITE + "/assets/og/og-%s.jpg" % ctx.lang.lower(),
          "author": {"@type": "Person", "name": OWNER}, "publisher": {"@type": "Person", "name": OWNER}}
    extra = '<script type="application/ld+json">%s</script>' % json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    body = hero + features + screens_html + faq + cta
    return document(ctx, s("meta_home_title"), strip_tags(s("meta_home_desc")), "home", body, "page-home", extra_head=extra)


def page_head(ctx, title, lead="", kicker="", wrap="narrow", after=""):
    k = f'<p class="kicker">{esc(kicker)}</p>' if kicker else ""
    l = f'<p class="lead">{lead}</p>' if lead else ""
    return f'<section class="page-head"><div class="wrap {wrap}"><div class="head-in">{k}<h1>{title}</h1>{l}{after}</div></div></section>'


def support_page(ctx):
    s = ctx.s
    subj = lambda k: html.escape(s(k)).replace(" ", "%20")
    email_link = f'<a href="mailto:{EMAIL}?subject={subj("support_delete_subject")}">{EMAIL}</a>'
    hl = s("support_google_hl")
    g_url = "https://support.google.com/googleplay/answer/2479637" + ("" if hl == "en" else f"?hl={hl}")

    def sec(anchor, icon, title_key, inner):
        return (f'<section class="s-card" id="{anchor}" aria-labelledby="{anchor}-t">'
                f'<div class="s-ico">{svg(icon, 22)}</div><div class="s-body"><h2 id="{anchor}-t">{esc(s(title_key))}</h2>{inner}</div></section>')

    body = page_head(ctx, esc(s("support_title")), s("support_lead"), GAME) + f"""<div class="wrap narrow support">
<div class="contact">
<div class="contact-main">{svg(I_MAIL, 28, "i big")}
<p class="email" translate="no">{EMAIL}</p></div>
<a class="btn" href="mailto:{EMAIL}?subject={subj("support_mail_subject")}">{esc(s("support_send"))}{svg(I_ARROW, 18)}</a>
<p class="contact-note">{s("support_include")}</p>
</div>
{sec("restore", I_RESTORE, "support_restore_title", f'<p>{s("support_restore_1")}</p><ul><li>{s("support_restore_path_1")}</li><li>{s("support_restore_path_2")}</li></ul><p>{s("support_restore_2")}</p>')}
{sec("analytics", I_SHIELD, "support_analytics_title", f'<p>{s("support_analytics_1")}</p>')}
{sec("delete", I_TRASH, "support_delete_title", f'<p>{s("support_delete_1", email_link=email_link)}</p>')}
{sec("refunds", I_REFUND, "support_refunds_title", f'<p>{s("support_refunds_1")}</p><ul class="links"><li>Apple: <a href="https://reportaproblem.apple.com">reportaproblem.apple.com</a></li><li>Google: <a href="{g_url}">support.google.com/googleplay</a></li></ul>')}
{sec("version", I_INFO, "support_version_title", f'<p>{s("support_version_1")}</p>')}
</div>"""
    title = f'{s("meta_support_title")} · {GAME}'
    return document(ctx, title, strip_tags(s("meta_support_desc")), "support", body, "page-support")


def legal_page(ctx, page):
    s = ctx.s
    blocks = load_legal(page, ctx.lang)
    translated = True
    if blocks is None:
        blocks = load_legal(page, DEFAULT_LANG)
        translated = False
    h1 = next(b for b in blocks if b[0] == "h1")
    rest = [b for b in blocks if b is not h1]
    title_html = h1[1]
    short_title = strip_tags(title_html).split(":")[0].strip()
    first_p = rest[0] if rest and rest[0][0] == "p" else None
    if first_p:
        rest = rest[1:]
    notice = ""
    if ctx.lang not in AUTHORITATIVE_LEGAL:
        en_url = ctx.href(DEFAULT_LANG, page)
        notice = f'<p class="notice" role="note">{svg(I_INFO, 20)}<span>{s("legal_translation_notice", en_url=en_url)}</span></p>'
    toc = "".join(f'<li><a href="#{b[2]}">{strip_tags(b[1])}</a></li>' for b in rest if b[0] == "h2")
    other = "terms" if page == "privacy" else "privacy"
    other_label = s("nav_terms") if other == "terms" else s("nav_privacy_long")
    meta_p = f'<div class="legal-meta">{first_p[1]}</div>' if first_p else ""
    body = page_head(ctx, f'{esc(short_title)}<span class="h1-game">{GAME}</span>', "", "", "legal-head",
                     notice + meta_p) + f"""<div class="wrap legal-wrap">
<aside class="toc" aria-labelledby="toc-t"><h2 id="toc-t">{esc(s("legal_on_page"))}</h2><ol role="list">{toc}</ol>
<p class="toc-other">{esc(s("legal_other_docs"))}: <a href="{ctx.href(ctx.lang, other)}">{esc(other_label)}</a></p></aside>
<article class="prose" lang="{ctx.lang if translated else DEFAULT_LANG}">
{"".join(render_block(b) for b in rest)}
<p class="top-link"><a href="#main">{esc(s("back_to_top"))} ↑</a></p>
</article>
</div>"""
    title = strip_tags(title_html)
    desc = strip_tags(s("meta_privacy_desc" if page == "privacy" else "meta_terms_desc"))
    return document(ctx, title, desc, page, body, "page-legal", og_type="article")


def not_found_page():
    ctx = Ctx(DEFAULT_LANG, "home", absolute=True)
    ctx.page = "home"
    rows = []
    for code in LANG_CODES:
        c = Ctx(code, "home", absolute=True)
        rows.append(f'<li lang="{code}"><span class="nf-t">{esc(c.s("nf_title"))}</span>'
                    f'<a href="/{LANG_DIR[code]}" hreflang="{code}">{esc(c.s("nf_home"))} · {esc(T[code]["lang_name"])}</a></li>')
    body = f"""<section class="page-head nf"><div class="wrap narrow">
<p class="kicker">404</p><h1>{esc(ctx.s("nf_title"))}</h1><p class="lead">{esc(ctx.s("nf_text"))} <a href="/">{esc(ctx.s("nf_home"))}</a>.</p>
</div></section>
<div class="wrap narrow"><ul class="nf-list" role="list">{"".join(rows)}</ul></div>"""
    return document(ctx, f'{ctx.s("nf_title")} · {GAME}', ctx.s("nf_text"), None, body, "page-404", noindex=True)


# ============================================================== extra files

def sitemap():
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for page in PAGES:
        for code in LANG_CODES:
            out.append("<url><loc>%s</loc>" % page_url(code, page))
            for c2 in LANG_CODES:
                out.append('<xhtml:link rel="alternate" hreflang="%s" href="%s"/>' % (c2, page_url(c2, page)))
            out.append('<xhtml:link rel="alternate" hreflang="x-default" href="%s"/>' % page_url(DEFAULT_LANG, page))
            out.append("</url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def manifest():
    return json.dumps({
        "name": GAME, "short_name": WORDMARK, "start_url": "/", "display": "browser",
        "background_color": "#070b16", "theme_color": "#070b16",
        "icons": [{"src": "/assets/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/assets/icons/icon-512.png", "sizes": "512x512", "type": "image/png"}]}, indent=1) + "\n"


# ============================================================== main

def clean_output():
    """Removes generated pages (not src/, .git, CNAME) so renamed pages don't linger."""
    for code in LANG_CODES:
        d = LANG_DIR[code]
        for page in PAGES:
            p = os.path.join(OUT, d + PAGE_PATH[page], "index.html")
            if os.path.exists(p):
                os.remove(p)


def main():
    global CSS_VERSION
    css_src = os.path.join(SRC, "site.css")
    css = open(css_src, encoding="utf-8").read()
    CSS_VERSION = hashlib.sha1(css.encode()).hexdigest()[:10]
    if "--clean" in sys.argv:   # re-encode every image and drop ones no longer used
        for d in (IMG_OUT, os.path.join(OUT, "assets", "og"), os.path.join(OUT, "assets", "badges")):
            shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "assets"), exist_ok=True)
    write("assets/site.css", css)

    print("images…")
    prepare_icons()
    for side in ("light", "dark"):
        prepare_art(f"scene_title_{side}", [640, 960, 1248], 78)
        for sc in SCHOOLS:
            prepare_art(f"scene_{sc['art']}_{side}", [320, 640], 76)
    for t in ("tile_signal_detector", "tile_pills", "tile_coins_large", "tile_top_blazer", "tile_top_cardigan",
              "tile_hat_bucket", "tile_glasses_round", "tile_wrist_watch", "tile_badge_gold"):
        prepare_art(t, [240, 480], 80)
    for p in ("prop_note", "prop_document", "prop_person", "prop_envelope"):
        prepare_art(p, [560, 1120], 80)
    screens = prepare_screens()
    prepare_og()

    print("pages…")
    clean_output()
    for code in LANG_CODES:
        d = LANG_DIR[code]
        write(d + "index.html", home_page(Ctx(code, "home"), screens))
        write(d + "support/index.html", support_page(Ctx(code, "support")))
        for page in ("privacy", "terms"):
            write(d + page + "/index.html", legal_page(Ctx(code, page), page))
    write("404.html", not_found_page())
    write("sitemap.xml", sitemap())
    write("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % SITE)
    write("site.webmanifest", manifest())
    write("CNAME", "pencilsdowngame.com\n")
    write(".nojekyll", "")
    print("built", OUT)


CSS_VERSION = ""
if __name__ == "__main__":
    main()
