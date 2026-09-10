# LLMtest website assets

Static product site for the LLMtest CLI. It uses plain HTML, CSS, and JavaScript with no build step.

The root `index.html` is the public landing page. This directory contains shared homepage assets and a multi-page documentation site under `docs/`.

## Preview locally

From the repository root, run:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000`.

The site is responsive, keyboard accessible, uses inline SVG icons, and respects the operating system's reduced-motion preference.
