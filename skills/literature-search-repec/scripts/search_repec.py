import argparse
import json
import sys

try:
    import httpx
    from bs4 import BeautifulSoup
except ImportError as err:
    print(json.dumps({"error": f"Missing dependency: {err.name}"}))
    sys.exit(1)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)


def print_error(message):
    print(json.dumps({"error": message}))


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print_error(message)
        raise SystemExit(1)


def search_ideas_repec(query, limit=10):
    url = "https://ideas.repec.org/cgi-bin/htsearch2"
    data = {"q": query}
    headers = {"User-Agent": USER_AGENT}

    try:
        response = httpx.post(url, data=data, headers=headers, timeout=30.0)
        response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print_error(f"Request failed: {e}")
        return 1

    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    # Typically, IDEAS search results are in <ol> -> <li>
    ol = soup.find("ol")
    if not ol:
        print(
            json.dumps(
                {
                    "results": [],
                    "message": "No results found or unrecognized HTML structure.",
                }
            )
        )
        return 0

    for li in ol.find_all("li", recursive=False):
        if len(results) >= limit:
            break

        a_tag = li.find("a")
        if not a_tag:
            continue

        title = a_tag.get_text(strip=True)
        href = a_tag.get("href", "")
        link = "https://ideas.repec.org" + href if href.startswith("/") else href

        # Extract authors - usually in <i> tags
        authors = [i.get_text(strip=True) for i in li.find_all("i")]

        # Extract abstract/snippet if available
        # The text snippet is often mixed in the li string elements
        snippet = ""
        text_nodes = [text for text in li.stripped_strings]
        # Skip the title and authors part to get a snippet
        for text in text_nodes:
            if text not in title and text not in authors and len(text) > 30:
                snippet = text
                break

        result_item = {
            "title": title,
            "link": link,
            "authors": authors,
            "snippet": snippet,
        }
        results.append(result_item)

    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    return 0


def fetch_latest_journal_articles(handle, limit=10):
    # handle format: RePEc:ucp:jpolec
    parts = handle.split(":")
    if len(parts) >= 3:
        provider = parts[1]
        journal = parts[2]
    else:
        print(
            json.dumps(
                {
                    "error": (
                        "Invalid journal handle format. "
                        "Expected RePEc:provider:journal"
                    )
                }
            )
        )
        return 1

    url = f"https://ideas.repec.org/s/{provider}/{journal}.html"
    headers = {"User-Agent": USER_AGENT}
    try:
        response = httpx.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print_error(f"Request failed: {e}")
        return 1

    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    list_group = soup.find("ul", class_="list-group")
    if not list_group:
        print(
            json.dumps(
                {
                    "results": [],
                    "message": "No articles found or unrecognized structure.",
                }
            )
        )
        return 0

    for li in list_group.find_all("li"):
        if len(results) >= limit:
            break

        a_tag = li.find("a")
        if not a_tag:
            continue

        href = a_tag.get("href", "")
        if "/a/" not in href and "/p/" not in href:
            continue

        title = a_tag.get_text(strip=True)
        link = "https://ideas.repec.org" + href if href.startswith("/") else href

        result_item = {"title": title, "link": link}
        results.append(result_item)

    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = JsonArgumentParser(description="Search IDEAS RePEc database")
    parser.add_argument(
        "query",
        nargs="?",
        default="",
        help="Search query (optional if using --journal-handle)",
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Maximum number of results to return"
    )
    parser.add_argument(
        "--journal-handle", help="RePEc journal/series handle (e.g., RePEc:ucp:jpolec)"
    )
    args = parser.parse_args(argv)

    if args.journal_handle and not args.query:
        return fetch_latest_journal_articles(args.journal_handle, args.limit)
    elif args.query:
        return search_ideas_repec(args.query, args.limit)
    else:
        print_error("Must provide either a query or a --journal-handle")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
