# pencilsdowngame.com: source

The site for *Pencils Down: Exam Proctor*. Everything under `src/` is the source; the built site sits at
the repo root and GitHub Pages serves it from `main`.

## Build

```sh
python3 -m pip install pillow      # once
python3 src/build.py               # writes every page, image and sitemap to the repo root
python3 src/build.py --clean       # same, but re-encodes all images (use after removing or replacing art)
python3 src/check.py               # links, anchors, head tags, no third-party scripts, page weight
```

Commit the source and the built output together. No JavaScript is produced; the only external request
is Google Fonts (Unbounded + Onest), and Japanese pages use the system's Japanese fonts instead.

## What is where

| Path | What |
|---|---|
| `src/build.py` | the generator, with the configuration at the top (`STORE_LINKS`, `LANGS`, screenshots) |
| `src/site.css` | the one stylesheet (light and dark themes from the game's palette) |
| `src/i18n/<lang>.json` | site strings for en, tr, es, fr, ja, pt-BR, ru (`en.json` is the reference; keep keys and `{placeholders}` identical) |
| `src/i18n/schools.json` | school names and kinds, copied from the game's localization |
| `src/legal/` | privacy policy and terms. EN and TR are the authoritative texts (identical to the game repo's `Docs/Release/`); es, fr, ja, pt-BR and ru are translations and show a "the English version prevails" notice |
| `src/assets/art/` | game art used on the site (renders, app icon) |
| `src/assets/screens/` | in-game screenshots (see below) |
| `src/check.py` | the post-build checker |

Pages: `/`, `/support/`, `/privacy/`, `/terms/` in every language (`/tr/`, `/es/`, `/fr/`, `/ja/`,
`/pt-br/`, `/ru/` prefixes), plus a multilingual `404.html`. English is the default; there is no
redirect by browser language.

## Adding the store links

In `src/build.py`, set the URLs:

```python
STORE_LINKS = {
    "android": "https://play.google.com/store/apps/details?id=…",
    "ios": "https://apps.apple.com/app/id…",
}
```

and rebuild. The "Coming soon" buttons (hero, final call to action, footer) become real links.

To show the official badges instead of the styled buttons, add the badge files from Google and Apple
(only once the links are live; both badge guidelines require a working store link):

```
src/static/badges/google-play/<lang>.svg   (or .png; en is the fallback for any language without one)
src/static/badges/app-store/<lang>.svg
```

Google: https://partnermarketinghub.withgoogle.com/brands/google-play/visual-identity/badge-guidelines/ ·
Apple: https://developer.apple.com/app-store/marketing/guidelines/

## Adding screenshots

Put portrait captures (e.g. 1080×2340 PNG) in `src/assets/screens/<lang>/`, named `NN-name.png`
(`01-hub.png`, `02-room.png`, …). They are shown in file-name order; a language without its own folder
uses `en/`. The caption comes from `SCREEN_CAPTIONS` in `build.py` (`room`, `hub`, `career`, `schools`,
`wardrobe`, `shop` are mapped to translated captions); other names get no caption. Rebuild.

Until a folder has images, the section shows four art compositions (scene + item tiles) with a note that
screenshots are coming; that note disappears automatically once real screenshots are present.

Use clean captures only: no "Development Build" watermark, no "(dev)" prices.

## Share images

`assets/og/og-<lang>.jpg` (1200×630) are composed by the build from the classroom render, the app
icon and the localized subtitle and tagline. They need Inter (`~/Library/Fonts`) or Arial Black, and
Hiragino for Japanese (macOS); without those fonts the committed images are kept.
