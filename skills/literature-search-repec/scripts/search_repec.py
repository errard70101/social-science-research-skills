import argparse
import httpx
from bs4 import BeautifulSoup
import json
import sys

def search_ideas_repec(query, limit=10):
    url = f"https://ideas.repec.org/cgi-bin/htsearch2"
    data = {"q": query}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = httpx.post(url, data=data, headers=headers, timeout=30.0)
        response.raise_for_status()
    except httpx.RequestError as e:
        print(json.dumps({"error": f"Request failed: {str(e)}"}))
        sys.exit(1)

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    
    # Typically, IDEAS search results are in <ol> -> <li>
    ol = soup.find("ol")
    if not ol:
        print(json.dumps({"results": [], "message": "No results found or unrecognized HTML structure."}))
        return
        
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
            "snippet": snippet
        }
        results.append(result_item)
        
    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))

def main():
    parser = argparse.ArgumentParser(description="Search IDEAS RePEc database")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of results to return")
    args = parser.parse_args()
    
    search_ideas_repec(args.query, args.limit)

if __name__ == "__main__":
    main()
