import json
import time
from urllib.parse import quote

import requests
from settings import settings

INPUT_FILE = "rieltor_locations_with_regions.json"
OUTPUT_FILE = "rieltor_locations_with_regions_fixed.json"

API_URL = "https://rieltor.ua/api/search/citiesautocomplete/?query={}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    )
}

PROXIES = {
    "http": settings.PROXY,
    "https": settings.PROXY,
}

MAX_RETRIES = 5


def extract_region(label: str) -> str:
    if "," in label:
        return label.split(",")[-1].strip()
    return label.strip()


def request(query: str):
    url = API_URL.format(quote(query))

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                proxies=PROXIES,
                timeout=30,
            )

            if response.status_code != 200:
                print(f"{query}: status {response.status_code}")
                time.sleep(2)
                continue

            return response.json().get("data", [])

        except Exception as e:
            print(f"{query}: {e}")
            time.sleep(2)

    return []


def main():
    with open(INPUT_FILE, encoding="utf-8") as f:
        cities = json.load(f)

    need_fix = [c for c in cities if not c.get("region")]

    print(f"Need fix: {len(need_fix)}")

    fixed = 0

    for city in need_fix:
        print(f"Searching: {city['name']}")

        # шукаємо по повній назві
        items = request(city["name"])

        found = False

        for item in items:
            if item.get("indexUrl") == city["slug"]:
                city["region"] = extract_region(item["addLabel"])
                fixed += 1
                found = True
                print(f"  OK -> {city['region']}")
                break

        if not found:
            print("  NOT FOUND")

        time.sleep(1)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(cities, f, ensure_ascii=False, indent=4)

    print(f"\nFixed {fixed} regions")


if __name__ == "__main__":
    main()