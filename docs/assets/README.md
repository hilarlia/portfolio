# Artwork and fonts

## Campus panorama

- `stata-center.svg`: the site's banner, a resolution-independent vector drawing with a 6144 × 2304 intrinsic size (8:3 ratio).
- `stata-center-6k.png`: a 6144 × 2304 raster export for downloading. It is not loaded by the home page, so its larger file size does not slow normal page loads.
- `research.svg`, `notebook.svg`, `coffee.svg`: matching spot illustrations for navigation and interior pages.
- `favicon.svg`: a small UK monogram.

The artwork was drawn programmatically for this portfolio. It is an **illustrated interpretation**, not a photograph, a measured architectural rendering, or the work of the reference site's illustrator. SVG scalability alone does not imply photographic detail.

The drawing uses tilted brick and silver façades, projecting windows, a yellow curved volume, golden and rust-red autumn foliage, an ochre lawn scattered with fallen leaves, ink outlines, and a red steel interpretation of *Aesop's Fables, II*. The composition and spatial relationships are simplified for a wide banner.

### References consulted

- [Emmanuel Candès's website](https://candes.su.domains/): visual direction (blue/orange editorial palette, outlined campus illustration, plain academic page layout). That site credits its artwork to **Vincent Mahé**. Its images, scripts, and stylesheet are **not** included or hotlinked here.
- [Stata Center photograph on Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Ray_and_Maria_Stata_Center_(MIT).JPG): architectural reference for Frank Gehry's Stata Center.
- [MIT List Visual Arts Center — Aesop's Fables, II](https://listart.mit.edu/art-artists/aesops-fables-ii-2005): visual reference for Mark di Suvero's sculpture on Hockfield Court.

Reference photographs are not distributed in this repository. The depicted architecture and sculpture are credited to their respective creators; the portfolio does not claim authorship of those designs or endorsement by MIT or the reference site's owner.

### Editing / replacing the image

To rebuild the SVG and spot illustrations using only Python's standard library:

```sh
python3 tools/draw_campus.py
```

This regenerates the vectors, not the PNG snapshot. After changing the panorama, export the updated SVG at **6144 × 2304** using an SVG editor or browser-based renderer, replacing `stata-center-6k.png` as well.

For a more natural, professionally illustrated result, the banner can be replaced with commissioned or externally generated artwork. This session did not have an image-generation model available. A useful art brief is:

> Wide 8:3 editorial campus illustration, 6144 × 2304. View across MIT's Hockfield Court toward the Stata Center: identifiable tilted stainless-steel façades, warm brick towers, projecting windows, and the yellow curved form. Accurately reference Mark di Suvero's Aesop's Fables, II: red steel I-beams, crossed supports, and twisting circular steel elements on the lawn. Crisp dark ink outlines, flat gold, amber, rust-red, and burgundy autumn foliage, fallen leaves on an ochre lawn, a pale warm sky, cool silver and warm brick architecture, restrained print grain. Students reading and walking, an asymmetrical framing tree, and a few small quantum-information diagrams in the sky. Architecture and sculpture fully visible. No lettering, logos, watermark, photographic effects, or text overlay.

Use the real location photographs as references, review architectural and sculpture accuracy, and confirm that you have permission to publish the replacement asset. Update the `<img>` source, dimensions, image links, and credit in `index.html` if the file format changes.

## Source Sans Pro

`fonts/` contains unmodified Latin-subset WOFF2 files from Google Fonts for Source Sans Pro regular, bold, and italic. The font is by Adobe and is distributed under the SIL Open Font License; see `fonts/LICENSE.md`.

The fonts are self-hosted: the site does not need Google Fonts requests, a JavaScript framework, or any remote assets to render. Characters outside the font subset use the browser's fallback font.
