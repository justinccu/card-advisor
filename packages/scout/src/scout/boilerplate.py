"""Strip navigation/footer lines shared across an Issuer's pages before sending text to the LLM.

Pure token saving: evidence is still checked against the full page text.
"""

from collections import Counter

SHARED_FRACTION = 0.6  # a line on >= 60% of an issuer's pages is site chrome, not card content
MIN_PAGES = 3  # with fewer pages we can't tell chrome from content


def shared_lines(pages: list[str]) -> set[str]:
    if len(pages) < MIN_PAGES:
        return set()
    counts = Counter(line for page in pages for line in set(page.splitlines()))
    return {line for line, n in counts.items() if n / len(pages) >= SHARED_FRACTION}


def strip(page: str, chrome: set[str]) -> str:
    return "\n".join(line for line in page.splitlines() if line not in chrome)
