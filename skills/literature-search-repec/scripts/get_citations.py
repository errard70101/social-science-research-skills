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


def get_citations(handle):
    # Base URL for plain citation counts
    url = f"https://citec.repec.org/api/plain/{handle}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = httpx.get(url, headers=headers, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.RequestError as e:
        print(json.dumps({"error": f"Request failed: {str(e)}"}))
        return

    # Parse XML
    try:
        root = ET.fromstring(response.text)

        # Check for error string (often returned when IP is blocked or handle is invalid)
        if root.tag == "errorString":
            print(json.dumps({"error": root.text}))
            return

        if root.tag == "citationData":
            cited_by = root.findtext("citedBy", "0")
            cites = root.findtext("cites", "0")
            uri = root.findtext("uri", "")

            result = {
                "handle": handle,
                "cited_by_count": int(cited_by),
                "cites_count": int(cites),
                "citec_url": uri,
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(
                json.dumps(
                    {"error": "Unrecognized XML structure", "raw": response.text[:200]}
                )
            )

    except ET.ParseError:
        print(
            json.dumps(
                {"error": "Failed to parse XML response", "raw": response.text[:200]}
            )
        )


def main():
    parser = argparse.ArgumentParser(
        description="Get citation counts for a RePEc Handle using CitEc API"
    )
    parser.add_argument("handle", help="RePEc Handle (e.g., RePEc:imf:imfwpa:01/191)")
    args = parser.parse_args()

    get_citations(args.handle)


if __name__ == "__main__":
    main()
