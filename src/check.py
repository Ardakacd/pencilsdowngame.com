#!/usr/bin/env python3
"""Checks the built site: internal links and anchors resolve, every page has the required head tags,
no third-party requests besides Google Fonts, and the home page's first-load weight.

    python3 src/check.py
"""
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlparse, unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://pencilsdowngame.com"
ALLOWED_EXTERNAL_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}   # for resources, not links


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.resources, self.ids, self.meta, self.alts = [], [], set(), {}, []
        self.lang = None
        self.title = ""
        self._in_title = False
        self.hreflangs, self.canonical, self.scripts = [], None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "title":
            self._in_title = True
        if tag == "a" and "href" in a:
            self.links.append(a["href"])
        if tag == "link":
            rel = a.get("rel", "")
            if rel == "canonical":
                self.canonical = a.get("href")
            elif rel == "alternate" and a.get("hreflang"):
                self.hreflangs.append((a["hreflang"], a["href"]))
            elif rel in ("stylesheet", "icon", "apple-touch-icon", "manifest", "preconnect"):
                self.resources.append((rel, a.get("href")))
        if tag in ("img", "source"):
            if a.get("src"):
                self.resources.append(("img", a["src"]))
            for part in (a.get("srcset") or "").split(","):
                if part.strip():
                    self.resources.append(("img", part.strip().split(" ")[0]))
            if tag == "img":
                self.alts.append(("alt" in a, a.get("width"), a.get("height"), a.get("loading")))
        if tag == "script":
            self.scripts.append(a.get("type"))
        if tag == "meta":
            k = a.get("name") or a.get("property")
            if k:
                self.meta[k] = a.get("content")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def html_files():
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in (".git", "src")]
        for f in fn:
            if f.endswith(".html"):
                yield os.path.join(dp, f)


def resolve(page_path, href):
    u = urlparse(href)
    if u.scheme or href.startswith("//"):
        return None, u.fragment
    path = unquote(u.path)
    if path.startswith("/"):
        target = os.path.join(ROOT, path.lstrip("/"))
    elif path == "":
        target = page_path
    else:
        target = os.path.normpath(os.path.join(os.path.dirname(page_path), path))
    if os.path.isdir(target) or path.endswith("/"):
        target = os.path.join(target, "index.html")
    return target, u.fragment


def main():
    errors, pages = [], {}
    for p in html_files():
        pg = Page()
        pg.feed(open(p, encoding="utf-8").read())
        pages[p] = pg
    for p, pg in pages.items():
        rel = os.path.relpath(p, ROOT)
        is404 = rel == "404.html"
        if not pg.title.strip():
            errors.append(f"{rel}: no <title>")
        if not pg.meta.get("description"):
            errors.append(f"{rel}: no description")
        if not pg.lang:
            errors.append(f"{rel}: no html lang")
        if not is404:
            if not pg.canonical:
                errors.append(f"{rel}: no canonical")
            langs = {h for h, _ in pg.hreflangs}
            if len(langs) != 8 or "x-default" not in langs:
                errors.append(f"{rel}: hreflang set {sorted(langs)}")
            for k in ("og:title", "og:description", "og:image", "og:url", "twitter:card"):
                if not pg.meta.get(k):
                    errors.append(f"{rel}: no {k}")
        for has_alt, w, h, _ in pg.alts:
            if not has_alt or not w or not h:
                errors.append(f"{rel}: <img> without alt/width/height")
        for t in pg.scripts:
            if t != "application/ld+json":
                errors.append(f"{rel}: executable <script> found")
        for kind, href in pg.resources:
            u = urlparse(href or "")
            if u.scheme in ("http", "https"):
                if u.hostname not in ALLOWED_EXTERNAL_HOSTS:
                    errors.append(f"{rel}: external resource {href}")
                continue
            target, _ = resolve(p, href)
            if target and not os.path.exists(target):
                errors.append(f"{rel}: missing resource {href}")
        for href in pg.links:
            if href.startswith(("mailto:", "http://", "https://")):
                continue
            if href.startswith("/") and not is404:
                errors.append(f"{rel}: root-absolute link {href} (use relative links)")
            target, frag = resolve(p, href)
            if not os.path.exists(target):
                errors.append(f"{rel}: broken link {href}")
                continue
            if frag:
                tp = pages.get(target)
                if tp is None or frag not in tp.ids:
                    errors.append(f"{rel}: missing anchor {href}")
        # canonical / hreflang targets must exist as built pages
        for _, url in pg.hreflangs + ([("c", pg.canonical)] if pg.canonical else []):
            if not url.startswith(SITE + "/"):
                errors.append(f"{rel}: bad absolute URL {url}")
                continue
            t = os.path.join(ROOT, url[len(SITE) + 1:], "index.html")
            if not os.path.exists(t):
                errors.append(f"{rel}: hreflang/canonical target missing {url}")

    # first-load weight of the home page (HTML + CSS + eager images, WebP, widest candidate <= 1248px)
    home = os.path.join(ROOT, "index.html")
    src = open(home, encoding="utf-8").read()
    total = os.path.getsize(home) + os.path.getsize(os.path.join(ROOT, "assets", "site.css"))
    all_imgs = 0
    seen = set()
    for m in re.finditer(r"<picture>(.*?)</picture>", src, re.S):
        block = m.group(1)
        eager = 'loading="lazy"' not in block
        cands = re.findall(r'srcset="([^"]+)"', block)
        webp = [c for c in cands if ".webp" in c and "prefers-color-scheme" not in block.split(c)[0][-120:]]
        pick = (webp or cands)[0].split(",")[-1].strip().split(" ")[0]
        if pick in seen:
            continue
        seen.add(pick)
        size = os.path.getsize(os.path.normpath(os.path.join(ROOT, pick)))
        all_imgs += size
        if eager:
            total += size
    print(f"pages checked: {len(pages)}")
    print(f"home first load (HTML+CSS+eager images, largest candidates): {total / 1024:.0f} KB")
    print(f"home with every image scrolled into view (largest candidates): {(total + all_imgs) / 1024:.0f} KB")
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
