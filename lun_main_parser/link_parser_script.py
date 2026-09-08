import re
import requests

from settings import settings

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}

URL_PATTERN = re.compile(r'\\"urlRaw\\":\\"(https://[^"]+)\\"')


def get_source_url(url: str) -> str | None:
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            proxies={
                "http": settings.PROXY,
                "https": settings.PROXY,
            },
            timeout=30,
        )
        print(response.status_code)
        response.raise_for_status()

        match = URL_PATTERN.search(response.text)
        return match.group(1) if match else None

    except requests.RequestException:
        return None


if __name__ == "__main__":
    input_url = "https://lun.ua/realty/4453768170"

    result_url = get_source_url(input_url)
    print(result_url)

    # if result_url:
        # offer = (
        #     session.query(Offer)
        #     .filter(Offer.ad_link == result_url)
        #     .first()
        # )
        #
        # print(offer)
    # else:
    #     TODO: Retry request (наприклад, з іншим проксі або через кілька секунд)
        # pass