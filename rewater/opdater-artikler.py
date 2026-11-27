"""Tilføj nye artikler fra artikler.txt til ReWater-modulets indlejrede liste."""
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DIRECTORY = Path(__file__).resolve().parent
ARTICLE_BLOCK = re.compile(r'(<script type="application/json" id="articles">)(.*?)(</script>)', re.S)
ARTICLE_PATH = re.compile(r"/[^/]+/ECE(\d+)(?:/|$)")
IMAGE_HOST = "billeder.lokalavisen.dk"


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            attrs = dict(attrs)
            if attrs.get("property") and attrs.get("content"):
                self.values.setdefault(attrs["property"], attrs["content"].strip())


def article_id(url):
    parts = urlsplit(url)
    match = ARTICLE_PATH.match(parts.path)
    if parts.scheme != "https" or parts.netloc not in {"dinavis.dk", "www.dinavis.dk"} or not match:
        raise ValueError(f"Forventede et Din Avis-artikellink: {url}")
    return match[1]


def fetch_article(url, identifier):
    request = Request(url, headers={"User-Agent": "DinAvis-ReWater/1.0", "Accept": "text/html"})
    with urlopen(request, timeout=20) as response:
        final_url = response.geturl()
        if article_id(final_url) != identifier:
            raise ValueError("Linket fører til en anden artikel")
        page = response.read().decode("utf-8")
    parser = Metadata()
    parser.feed(page)
    fields = parser.values
    title = fields.get("og:title")
    image = fields.get("og:image", "")
    published = fields.get("article:published_time", "")
    if not title or not image or not published:
        raise ValueError("Rubrik, billede eller publiceringstid mangler i artiklens metadata")
    image_url = urlsplit(image)
    if image_url.scheme != "https" or image_url.netloc != IMAGE_HOST:
        raise ValueError(f"Billedet ligger på en ukendt billedserver: {image_url.netloc}")
    if datetime.fromisoformat(published.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("Publiceringstid mangler tidszone")
    canonical = fields.get("og:url") or final_url
    if article_id(canonical) != identifier:
        raise ValueError("Artiklens kanoniske link har et andet artikel-id")
    return dict(url=canonical, title=title, image=image, id=identifier, published=published)


def main():
    html_path = DIRECTORY / "index.html"
    html = html_path.read_text(encoding="utf-8")
    block = ARTICLE_BLOCK.search(html)
    if not block:
        raise SystemExit("Fandt ikke artikellisten i index.html")
    articles = json.loads(block[2])
    identifiers = {article["id"] for article in articles}
    additions = []
    failures = []
    for number, line in enumerate((DIRECTORY / "artikler.txt").read_text(encoding="utf-8-sig").splitlines(), 1):
        url = line.strip()
        if not url or url.startswith("#"):
            continue
        try:
            identifier = article_id(url)
            if identifier in identifiers:
                continue
            additions.append(fetch_article(url, identifier))
            identifiers.add(identifier)
        except (ValueError, URLError, TimeoutError) as error:
            failures.append(f"Linje {number} ({url}): {error}")
    if failures:
        raise SystemExit("\n".join(failures))
    if not additions:
        print("Ingen nye artikler.")
        return
    articles = sorted(articles + additions, key=lambda article: article["published"], reverse=True)
    payload = json.dumps(articles, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    html_path.write_text(html[:block.start(2)] + "\n" + payload + "\n" + html[block.end(2):], encoding="utf-8")
    print(f"Tilføjede {len(additions)} artikler. Nu er der {len(articles)} artikler.")


if __name__ == "__main__":
    main()
