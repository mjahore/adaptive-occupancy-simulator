# AOS brand artwork

The emblem uses four state nodes, a directed cycle, and a self-loop to evoke a Markov chain. A small amber center suggests an active state. Cyan, teal, violet, and magenta sit on a midnight tile, with transparent outer corners. The same artwork has sufficient contrast on light and dark pages.

## Files

- `aos-markov-icon.png`: 512 × 512 repository artwork.
- `../custom_components/adaptive_occupancy_simulator/brand/icon.png` and `dark_icon.png`: 256 × 256 integration icons.
- `../custom_components/adaptive_occupancy_simulator/brand/icon@2x.png` and `dark_icon@2x.png`: 512 × 512 integration icons.

All PNGs preserve their alpha channel. Built-in image generation produced the master; mechanical downsampling produced the packaged sizes. This artwork is distributed under the repository's MIT license.

## Display support

Home Assistant Core 2026.7.2 supports these local brand files. The `brand/` directory is included when HACS installs the integration. HACS 2.0.5 itself still requests central-catalog icons for its repository list; no repository-level icon URL override is supported in its `hacs.json` schema. This upstream limitation is tracked in [HACS #5171](https://github.com/hacs/integration/issues/5171). The maintainer reports that the later Marketplace implementation addresses it; AOS does not require an upgrade from its documented HA 2026.7.2 target.

See [Home Assistant's branding announcement](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/) and [HACS 2.0.5's manifest schema](https://github.com/hacs/integration/blob/2.0.5/custom_components/hacs/utils/validate.py).

## Generation prompt

Create ONE finished app icon for Adaptive Occupancy Simulator (AOS), a Home Assistant integration inspired by Markov chains. New artwork, not an edit. A beautiful, precise, minimal vector-style emblem: four large circular state nodes arranged as a balanced diamond, connected by thick curved directed arrows forming a recurrent cycle, with one elegant small self-loop at the upper node and a subtle central transition. Cool cyan and teal flowing toward electric violet, one small warm amber active-state dot. Clearly visible arrowheads, crisp geometric contours, excellent recognition at 48 pixels. Deep midnight navy rounded-square tile with generous padding; transparent pixels outside the rounded corners. Use controlled, subtle gradients and luminous color contrast but no bloom or blurry glow. Professional scientific software branding, elegant and memorable, almost an abstract home-shaped constellation. No text, no letters, no numbers, no probability labels, no extra objects, no mockup, no presentation sheet. The icon must be centered and fill approximately 88% of a square canvas. Square PNG suitable for a software repository and Home Assistant integration icon, clean alpha outside the tile.
