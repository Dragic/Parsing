"""Recovers the exact listing area from free text.

M2BOMBER and RIELTORUA publish the area rounded to a whole number in the
structured part of the page ("18 м²") while the precise value survives in the
title or the description ("18.6 м²"). A whole-number area cannot be compared
against a source that keeps decimals, so the precise value is preferred
whenever the text carries one.

This module is duplicated per parser, like currency_api.py and ai_repair.py —
this repository has no shared package. Keep the copies in sync.
"""

import re

# "18,6 м²" / "18.6 м2" / "18 кв. м"
_AREA_RE = re.compile(
    r'(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:м²|м2|кв\.?\s*м)',
    re.IGNORECASE,
)

# "60,5/35,2/9 м²" — total / living / kitchen. Only the first number is the
# total area, and the plain _AREA_RE above would otherwise pick up the kitchen.
_AREA_TRIPLET_RE = re.compile(
    r'(\d{1,4}(?:[.,]\d{1,2})?)\s*/\s*\d{1,4}(?:[.,]\d{1,2})?\s*/\s*'
    r'\d{1,4}(?:[.,]\d{1,2})?\s*(?:м²|м2|кв\.?\s*м)',
    re.IGNORECASE,
)


def _to_float(raw):
    try:
        return float(str(raw).replace(',', '.').strip())
    except (TypeError, ValueError):
        return None


def _candidates(text):
    if not text:
        return []
    found = _AREA_TRIPLET_RE.findall(text) + _AREA_RE.findall(text)
    return [v for v in (_to_float(f) for f in found) if v is not None]


def parse_area(text):
    """First area found in `text`, or None.

    Handles the decimal comma and the "total/living/kitchen" triplet, both of
    which a plain float() on a split string gets wrong.
    """
    found = _candidates(text)
    return found[0] if found else None


def refine_area(area, *texts, tolerance=1.0):
    """Return the most precise area found in `texts` that agrees with `area`.

    `area` is returned untouched unless a candidate lies within `tolerance` of
    it and carries a fractional part, so a number picked out of unrelated text
    can never replace a correctly parsed one.
    """
    base = _to_float(area)
    if base is None:
        return area

    fractional = [
        c for text in texts for c in _candidates(text)
        if abs(c - base) <= tolerance and c != int(c)
    ]
    if not fractional:
        return area

    return min(fractional, key=lambda c: abs(c - base))


if __name__ == '__main__':
    # Rounded value replaced by the precise one carried in the title.
    assert refine_area(18, '1-кімн. квартира, 18.6 м², 3/9 поверх') == 18.6
    assert refine_area(18.0, 'Продам 18,6 м² біля метро') == 18.6
    # Triplet form: the total, not the kitchen.
    assert refine_area(60, 'Квартира 60,5/35,2/9 м², Київ') == 60.5
    # Nothing plausible in the text — the parsed value survives.
    assert refine_area(18, 'Квартира біля метро') == 18
    assert refine_area(18, 'Поруч ділянка 42.5 м²') == 18
    # An already precise value is not downgraded, and None stays None.
    assert refine_area(18.6, 'площа 18.6 м²') == 18.6
    assert refine_area(None, 'площа 18.6 м²') is None
    # parse_area: decimal comma and the triplet form.
    assert parse_area('60,5/35,2/9 м²') == 60.5
    assert parse_area('18,6 м²') == 18.6
    assert parse_area('42 м2') == 42.0
    assert parse_area('немає даних') is None
    assert parse_area(None) is None
    print('area_precision self-check ok')
