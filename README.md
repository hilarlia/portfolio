# Ufuk Keskin — 16.S893 portfolio

Site URL: **https://hilarlia.github.io/portfolio/**

A four-page, static HTML/CSS portfolio for AI for Engineering Research. No build step, package installation, or JavaScript is required to view or publish it.

## Repository organization

```text
portfolio/
├── docs/                 # Website files, served by GitHub Pages
│   ├── index.html        # About Me / homepage
│   ├── project.html
│   ├── sofar.html
│   ├── blog.html
│   ├── style.css
│   ├── .nojekyll
│   └── assets/           # Artwork and local fonts
├── tools/                # Source utilities and static checks
└── README.md
```

All website files live in `docs/`. GitHub Pages publishes **main → /docs**, so the website URL remains unchanged. Make website edits in `docs/`; there are no duplicate HTML, CSS, or asset files at the repository root.

## Preview before publishing

On this Mac, paste this into **Terminal**, not an HTML file:

```sh
open /Users/ufukkeskin/portfolio/docs/index.html
```

Or open `docs/index.html` directly in your browser. All four tabs and the local fonts work from disk.

For an HTTP preview (optional):

```sh
cd /Users/ufukkeskin/portfolio
python3 -m http.server 8000 --bind 127.0.0.1 --directory docs
```

Then visit <http://localhost:8000>. Press **Control-C** in that Terminal window to stop the server.

## Where to edit

| File | Contents |
| --- | --- |
| `docs/index.html` | About Me / landing page, contact details, full-width campus panorama |
| `docs/project.html` | Project overview and latest research update |
| `docs/sofar.html` | Chronological steps and milestones |
| `docs/blog.html` | Informal posts; a commented article template is included |
| `docs/style.css` | Shared fonts, blue navigation, page layout, responsive styles |
| `docs/assets/` | Original vector illustrations, 6K PNG download, local fonts |

Each page includes the same four navigation links. Its own link has `aria-current="page"`, which also controls the active blue tab. If you rename a tab, update its text in all four files.

### Add a project update

Replace the “Research updates to come” note in `docs/project.html` with a **dated, factual** description of the latest work. Link relevant code, notes, or papers. Keep the newest state here and move older steps into `docs/sofar.html`.

### Add a progress entry

Copy a `<li>...</li>` inside the `.timeline` list in `docs/sofar.html`. Give it a title, your actual date or step number, a short explanation, and relevant links. The current entries only describe the initial project direction and portfolio setup; they do not claim completed research experiments.

### Add a blog post

In `docs/blog.html`, remove the visible “No posts yet” section. Copy the commented `<article>` template out of its comment, then replace its title, `id`, date, and text. Put the newest post first. Use a unique `id` for each post so its title link works as a permalink. The sample date inside the comment is not a published entry.

## Publish the revision

Changes made locally do **not** automatically appear on GitHub. Run these commands in Terminal after reviewing the files:

```sh
cd /Users/ufukkeskin/portfolio
git status
git add docs tools README.md
git commit -m "Update portfolio"
git push origin main
```

If the push reports an error, stop and read the error; do not force-push. `working tree clean` alone does not prove a push succeeded. A successful push should appear in the repository's commit history at <https://github.com/hilarlia/portfolio>.

On GitHub, use **Settings → Pages → Deploy from a branch → main → /docs → Save**. The public URL remains **https://hilarlia.github.io/portfolio/**; do not add `/docs/` to the published URL. GitHub serves the contents of `docs/` directly at that URL.

After the Pages deployment completes, visit the live URL and hard-refresh with **Command-Shift-R** if an old stylesheet is cached. `docs/.nojekyll` tells Pages to serve the files without Jekyll processing.

## Design and artwork

The layout follows the visual direction of <https://candes.su.domains/>: Source Sans Pro, cobalt `#1c3ed3`, a white background, a panoramic illustration, plain two-column text, small illustrated links, and a slate footer. It is not a pixel-for-pixel copy.

The home-page banner displays the **entire image**, not a cropped `background-size: cover` image. It is 540 CSS pixels tall on a 1440-pixel-wide screen. On a phone it scales proportionally; click the image to open it at full size. The vector artwork stays sharp as it scales; a separate **6144 × 2304 PNG** is available via the download link.

See [docs/assets/README.md](docs/assets/README.md) for illustration limitations, visual references, credits, font licensing, and replacement guidance.

### Campus breeze animation

Five small leaves drift and turn across the home-page illustration on staggered 22–31 second loops. They are a separate, decorative SVG layer in `docs/index.html`, animated by CSS in `docs/style.css`. The buildings, sculpture, original SVG/PNG downloads, and easter egg are unchanged.

- Check **Pause breeze** to freeze the leaves; uncheck it to resume. The control also works with Tab and Space, with no JavaScript required.
- On phones, the control sits below the picture so it does not obscure the scene.
- With the operating system's **Reduce Motion** preference enabled, the leaves and their control are hidden automatically. Printed pages are static too.
- The animation layer does not intercept clicks: the panorama still links to the full-size artwork.
- To tune the effect, edit the `.breeze-leaf` timing and drift variables in `docs/style.css`.

## Check the static files

Run the dependency-free checks:

```sh
python3 tools/check_site.py
```

They validate the site inside `docs/`: local links and fragments, navigation consistency, image references, SVG parsing, font assets, and the 6K PNG dimensions.

The revision was also browser-tested at 320, 390, 768, and 1440 pixels, with keyboard navigation, direct `file://` opening without JavaScript, and automated WCAG A/AA checks. Automated checks are not a guarantee of complete accessibility; always review new content and test the live Pages deployment too.
