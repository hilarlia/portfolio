#!/usr/bin/env python3
"""Dependency-free checks for this GitHub Pages site. Run from any directory."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import re
import struct
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1] / 'docs'
PAGES = ['index.html', 'project.html', 'sofar.html', 'blog.html']
LABELS = ['About Me', 'My Project', 'So Far', 'Blog']


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.links, self.images, self.ids, self.nav = [], [], [], []
        self.h1_count = 0
        self.language = None
        self.in_nav = False
        self.active_link = None
        self.feed(path.read_text())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html':
            self.language = attrs.get('lang')
        if tag == 'h1':
            self.h1_count += 1
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        for key in ('href', 'src'):
            if key in attrs:
                self.links.append(attrs[key])
        if tag == 'img':
            self.images.append(attrs)
        if tag == 'nav' and attrs.get('aria-label') == 'Main navigation':
            self.in_nav = True
        if tag == 'a' and self.in_nav:
            self.active_link = {'href': attrs.get('href'), 'current': attrs.get('aria-current'), 'label': ''}
            self.nav.append(self.active_link)

    def handle_endtag(self, tag):
        if tag == 'nav':
            self.in_nav = False
        if tag == 'a':
            self.active_link = None

    def handle_data(self, data):
        if self.active_link is not None:
            self.active_link['label'] += data


class SiteChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {name: Page(ROOT / name) for name in PAGES}

    def test_navigation_and_document_structure(self):
        for name, page in self.pages.items():
            with self.subTest(page=name):
                self.assertEqual(page.language, 'en')
                self.assertEqual(page.h1_count, 1)
                self.assertEqual(len(page.ids), len(set(page.ids)), 'Duplicate IDs')
                self.assertEqual([a['href'] for a in page.nav], PAGES)
                self.assertEqual([a['label'].strip() for a in page.nav], LABELS)
                self.assertEqual([a['href'] for a in page.nav if a['current'] == 'page'], [name])
                self.assertIn('#main', page.links)

    def test_local_links_and_fragments(self):
        for name, page in self.pages.items():
            for href in page.links:
                with self.subTest(page=name, href=href):
                    url = urlsplit(href)
                    if url.scheme or url.netloc:
                        continue
                    self.assertFalse(url.path.startswith('/'), 'Use relative links for /portfolio/ deployment')
                    target = ROOT / unquote(url.path or name)
                    self.assertTrue(target.is_file(), f'Missing local file: {target}')
                    if url.fragment and target.suffix == '.html':
                        linked_page = self.pages.get(target.name) or Page(target)
                        self.assertIn(unquote(url.fragment), linked_page.ids)

    def test_images_have_alternative_text_and_dimensions(self):
        for name, page in self.pages.items():
            for image in page.images:
                with self.subTest(page=name, image=image.get('src')):
                    self.assertIn('alt', image)  # Decorative spot illustrations intentionally have alt="".
                    self.assertGreater(int(image['width']), 0)
                    self.assertGreater(int(image['height']), 0)

    def test_css_assets(self):
        css = (ROOT / 'style.css').read_text()
        for url in re.findall(r'url\([\'"]?([^\'"\)]+)', css):
            self.assertTrue((ROOT / url).is_file(), f'Missing stylesheet asset: {url}')
        for font in (ROOT / 'assets/fonts').glob('*.woff2'):
            self.assertEqual(font.read_bytes()[:4], b'wOF2', f'Invalid WOFF2 font: {font.name}')
        self.assertEqual(len(list((ROOT / 'assets/fonts').glob('*.woff2'))), 3)
        self.assertTrue((ROOT / 'assets/fonts/LICENSE.md').is_file())

    def test_vector_artwork(self):
        for file in (ROOT / 'assets').glob('*.svg'):
            root = ET.parse(file).getroot()
            self.assertTrue(root.tag.endswith('svg'))
            ids = [e.attrib['id'] for e in root.iter() if 'id' in e.attrib]
            self.assertEqual(len(ids), len(set(ids)), f'Duplicate SVG IDs: {file.name}')
        campus = ET.parse(ROOT / 'assets/stata-center.svg').getroot()
        self.assertEqual(campus.attrib['viewBox'], '0 0 2560 960')
        self.assertEqual((campus.attrib['width'], campus.attrib['height']), ('6144', '2304'))

    def test_png_is_a_real_6k_export(self):
        with (ROOT / 'assets/stata-center-6k.png').open('rb') as file:
            header = file.read(24)
        self.assertEqual(header[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(header[12:16], b'IHDR')
        self.assertEqual(struct.unpack('>II', header[16:24]), (6144, 2304))

    def test_campus_breeze_is_decorative_and_pausable(self):
        home = (ROOT / 'index.html').read_text()
        overlay = ET.fromstring(re.search(r'<svg\b.*?</svg>', home, re.S).group())
        self.assertEqual(overlay.attrib['aria-hidden'], 'true')
        self.assertEqual(overlay.attrib['focusable'], 'false')
        self.assertEqual(overlay.attrib['viewBox'], '0 0 2560 960')
        self.assertEqual(len(list(overlay.iter('use'))), 5)
        self.assertIn('type="checkbox" id="pause-breeze"', home)
        self.assertIn('for="pause-breeze">Pause breeze</label>', home)
        css = (ROOT / 'style.css').read_text()
        self.assertIn('prefers-reduced-motion: reduce', css)
        self.assertIn('animation-play-state: paused', css)
        for name in PAGES[1:]:
            self.assertNotIn('campus-breeze', (ROOT / name).read_text())

    def test_no_legacy_root_site_copies(self):
        for name in [*PAGES, 'style.css', 'assets', '.nojekyll']:
            self.assertFalse((ROOT.parent / name).exists(), f'Website files belong in docs/: {name}')

    def test_plain_pages_deployment(self):
        self.assertEqual(ROOT.name, 'docs')
        html_pages = {p.name for p in ROOT.glob('*.html')}
        self.assertTrue(set(PAGES).issubset(html_pages))
        self.assertTrue((ROOT / '.nojekyll').is_file())
        for name in html_pages:
            self.assertNotIn('<script', (ROOT / name).read_text().lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)
