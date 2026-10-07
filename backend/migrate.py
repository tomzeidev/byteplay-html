"""One-time migration of the 11 JSON posts and 7 legacy HTML articles."""
import html
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth = 0
        self.parts = []
        self.author = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'div' and not self.depth and 'blog-content' in dict(attrs).get('class', '').split():
            self.depth = 1
            return
        if self.depth:
            if tag == 'div': self.depth += 1
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.depth:
            if tag == 'div': self.depth -= 1
            if self.depth: self.parts.append(f'</{tag}>')

    def handle_data(self, data):
        if self.depth: self.parts.append(data)

    def handle_entityref(self, name):
        if self.depth: self.parts.append('&' + name + ';')

    def handle_charref(self, name):
        if self.depth: self.parts.append('&#' + name + ';')


def plain(value):
    return html.unescape(re.sub(r'<[^>]+>', '', value)).strip()


def collect_posts(root):
    root = Path(root)
    collected = {}
    for path in sorted((root / 'posts').glob('*.json')):
        post = json.loads(path.read_text())
        post['date'] = datetime.strptime(post['date'], '%B %d, %Y').date().isoformat()
        post['status'] = 'published'
        collected[post['id']] = post
    listing = (root / 'developer-blog.html').read_text()
    cards = re.findall(r'<div class="post" data-cat="([^"]+)" data-date="([^"]+)">(.*?)<a href="([^"]+)" class="read-more">', listing, re.S)
    for category, day, card, href in cards:
        slug = parse_qs(urlsplit(href).query).get('id', [Path(urlsplit(href).path).stem])[0]
        if slug in collected: continue
        source = (root / (slug + '.html')).read_text()
        parser = ArticleParser(); parser.feed(source)
        body = ''.join(parser.parts)
        # Old articles contain filename casing mistakes; match actual tracked assets.
        def image_path(match):
            path = match.group(1)
            candidate = root / path
            if not candidate.is_file():
                for sibling in candidate.parent.glob('*'):
                    if sibling.name.casefold() == candidate.name.casefold():
                        path = str(sibling.relative_to(root)); break
            return 'src="' + path + '"'
        body = re.sub(r'src="([^"]+)"', image_path, body)
        title = re.search(r'<h2>(.*?)</h2>', card, re.S).group(1)
        excerpt = re.search(r'<p class="excerpt">(.*?)</p>', card, re.S).group(1)
        thumb = re.search(r'<img[^>]+src="([^"]+)"', card).group(1)
        collected[slug] = dict(id=slug, title=plain(title), date=day, category=category, author='BytePlay Devs',
                              excerpt=plain(excerpt), thumb=thumb, status='published', content=[{'type': 'html', 'html': body}])
    if len(collected) != len(cards):
        raise ValueError(f'Migration mismatch: {len(collected)} imported posts for {len(cards)} listing cards.')
    return list(collected.values())
