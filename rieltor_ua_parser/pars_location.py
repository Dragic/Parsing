import json
import time
from settings import settings
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://rieltor.ua/cities/houses-sale/"
TOTAL_PAGES = 53

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    )
}

# Приклад
PROXIES = {
    "http":settings.PROXY,
    "https": settings.PROXY,
}


MAX_RETRIES = 5


def get_page(page: int) -> str:
    if page == 1:
        url = BASE_URL
    else:
        url = f"{BASE_URL}?page={page}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                proxies=PROXIES,
                timeout=30,
            )

            if response.status_code == 200:
                return response.text

            print(
                f"[{attempt}/{MAX_RETRIES}] "
                f"Status {response.status_code} for {url}"
            )

        except requests.RequestException as e:
            print(
                f"[{attempt}/{MAX_RETRIES}] "
                f"Request error: {e}"
            )

        time.sleep(2)

    raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} attempts")


def parse(html: str):
    soup = BeautifulSoup(html, "html.parser")

    wrapper = soup.select_one("div.entity-hub-list__items-wrapper")
    if wrapper is None:
        return []

    result = []

    for a in wrapper.select("a[href]"):
        href = a["href"]

        # /andrushevka/houses-sale/ -> /andrushevka/
        slug = href.replace("houses-sale/", "")

        result.append(
            {
                "name": a.get_text(strip=True),
                "slug": slug,
            }
        )

    return result


def main():
    cities = []

    for page in range(1, TOTAL_PAGES + 1):
        print(f"Page {page}/{TOTAL_PAGES}")

        html = get_page(page)
        cities.extend(parse(html))

        time.sleep(1)

    # прибираємо дублікати
    unique = {}
    for city in cities:
        unique[city["slug"]] = city

    result = sorted(unique.values(), key=lambda x: x["slug"])

    with open("rieltor_locations.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    print(f"Saved {len(result)} locations")


if __name__ == "__main__":
    main()