import argparse
import json
import sys
import xml.etree.ElementTree as ET

try:
    import httpx
except ImportError:
    print(
        json.dumps({"error": "httpx is not installed. Please run: pip install httpx"})
    )
    sys.exit(1)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"error": message}))
        raise SystemExit(1)


def get_citations(handle):
    # Base URL for plain citation counts
    url = f"https://citec.repec.org/api/plain/{handle}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = httpx.get(url, headers=headers, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(json.dumps({"error": f"Request failed: {e}"}))
        return 1

    # Parse XML
    try:
        root = ET.fromstring(response.text)

        # CitEc returns this when an IP is blocked or the handle is invalid.
        if root.tag == "errorString":
            print(json.dumps({"error": root.text}))
            return 1

        if root.tag == "citationData":
            cited_by = root.findtext("citedBy", "0")
            cites = root.findtext("cites", "0")
            uri = root.findtext("uri", "")

            try:
                cited_by_count = int(cited_by or 0)
                cites_count = int(cites or 0)
            except ValueError:
                print(json.dumps({"error": "Invalid citation count in CitEc response"}))
                return 1

            result = {
                "handle": handle,
                "cited_by_count": cited_by_count,
                "cites_count": cites_count,
                "citec_url": uri,
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        else:
            print(
                json.dumps(
                    {"error": "Unrecognized XML structure", "raw": response.text[:200]}
                )
            )
            return 1

    except ET.ParseError:
        print(
            json.dumps(
                {"error": "Failed to parse XML response", "raw": response.text[:200]}
            )
        )
        return 1


def main(argv=None):
    parser = JsonArgumentParser(
        description="Get citation counts for a RePEc Handle using CitEc API"
    )
    parser.add_argument("handle", help="RePEc Handle (e.g., RePEc:imf:imfwpa:01/191)")
    args = parser.parse_args(argv)

    return get_citations(args.handle)


if __name__ == "__main__":
    raise SystemExit(main())
