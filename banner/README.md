# Profile banner

Generates the animated banner at the top of my GitHub profile: `assets/banner-dark.svg` and `assets/banner-light.svg`. The profile README picks the version that matches the visitor's GitHub theme.

## Rebuild

From the repository root:

```sh
uv run banner/build.py
```

`uv` installs the single dependency (`fonttools`) on the fly. Without `uv`:

```sh
pip install fonttools
python banner/build.py
```

## Customize

Everything lives in [`banner.toml`](banner.toml):

- `[[lines]]`: the text that gets typed, with font, size, position, colour and typing speed
- `[typing]`: timing of the loop (pauses, how long the text stays, fade)
- `[graph]`: the network in the background (random seed, node count, drift, where it fades out)
- `[themes.*]`: colours per theme; every theme produces its own SVG

## How it works

- **Text** is converted to vector outlines with `fontTools`, because SVGs embedded with `<img>` can't load fonts. The font is [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) (SIL Open Font License, see [`fonts/OFL.txt`](fonts/OFL.txt)).
- **Animation** uses SMIL only. GitHub strips scripts, but `<img>` SVGs still animate. The typewriter effect is a clip rectangle that grows one character at a time. The graph nodes drift along closed Lissajous loops, so the animation repeats seamlessly.
- **Reduced motion:** visitors with `prefers-reduced-motion` enabled see a still frame with the full text.
