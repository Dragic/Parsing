import json
import time
from urllib.parse import quote

import requests
from lxml import etree
from settings import settings

INPUT_FILE = "rieltor_locations.json"
OUTPUT_FILE = "rieltor_locations_with_regions.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    )
}



API_URL = "https://rieltor.ua/api/search/citiesautocomplete/?query={}"

MAX_RETRIES = 5
PROXIES = {'http': settings.PROXY, 'https': settings.PROXY}

def request_prefix(prefix: str):
    url = API_URL.format(quote(prefix))

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                proxies=PROXIES,
                timeout=30,
            )

            if response.status_code != 200:
                print(
                    f"[{attempt}/{MAX_RETRIES}] "
                    f"{prefix}: status {response.status_code}"
                )
                time.sleep(2)
                continue

            data = response.json()

            items = []

            for item in data.get("data", []):
                index_url = item.get("indexUrl")
                add_label = item.get("addLabel")

                if not index_url or not add_label:
                    continue

                items.append(
                    {
                        "name": item.get("value", ""),
                        "slug": index_url,
                        "label": add_label,
                    }
                )

            print(f"{prefix}: {len(items)} results")

            return items

        except Exception as e:
            print(f"[{attempt}/{MAX_RETRIES}] {prefix}: {e}")
            time.sleep(2)

    raise RuntimeError(f"Cannot load prefix: {prefix}")


def extract_region(label: str) -> str:
    if "," in label:
        return label.split(",")[-1].strip()
    return label.strip()


def main():
    with open(INPUT_FILE, encoding="utf-8") as f:
        cities = json.load(f)

    # словник існуючих міст
    cities_by_slug = {}

    for city in cities:
        city["name"] = (
            city["name"]
            .replace("с. ", "")
            .replace("смт. ", "")
        )
        city["region"] = city.get("region")
        cities_by_slug[city["slug"]] = city

    cities.sort(key=lambda x: x["name"])

    cache = {}

    total = len(cities)

    for i, city in enumerate(cities, 1):
        prefix = city["name"][:3]

        if prefix not in cache:
            cache[prefix] = request_prefix(prefix)
            time.sleep(1)

        for item in cache[prefix]:
            slug = item["slug"]
            region = extract_region(item["label"])

            if slug in cities_by_slug:
                # оновлюємо існуюче місто
                cities_by_slug[slug]["region"] = region
            else:
                # нове місто з autocomplete
                new_city = {
                    "name": None,
                    "slug": slug,
                    "region": region,
                }

                cities_by_slug[slug] = new_city

        print(f"[{i}/{total}] {city['name']}")

    # якщо у нового міста нема назви — беремо її з autocomplete
    for items in cache.values():
        for item in items:
            slug = item["slug"]

            if cities_by_slug[slug]["name"] is None:
                name = item.get("name", "")
                name = (
                    name.replace("м. ", "")
                    .replace("с. ", "")
                    .replace("смт. ", "")
                    .strip()
                )
                cities_by_slug[slug]["name"] = name

    result = sorted(
        cities_by_slug.values(),
        key=lambda x: (x["name"] or "")
    )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    print(f"\nSaved {len(result)} cities to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()