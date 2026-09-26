# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=11"]
# ///
"""Sample background colors from the local issuer card art for the simulated card faces.

The images stay local (gitignored); this writes only colors to web/src/lib/card-face-colors.json,
which is tracked, so the simulated faces also work where the images aren't deployed.

    uv run scripts/card_face_colors.py
"""

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "web" / "public" / "card-art"
OUT = ROOT / "web" / "src" / "lib" / "card-face-colors.json"

# Images that aren't a single flat card: the card's box as fractions (left, top, right, bottom).
CROPS = {
    "discover_it_cash_back": (0.05, 0.38, 0.40, 0.65),
    "discover_it_student_cash_back": (0.38, 0.38, 0.62, 0.59),
    "amex_blue_business_plus": (0.15, 0.12, 0.70, 0.60),
}
INSET = 0.06  # skip edges (rounded corners, borders, shadows)


def _card_box(im: Image.Image, card_id: str) -> Image.Image:
    w, h = im.size
    if card_id in CROPS:
        left, top, right, bottom = CROPS[card_id]
        return im.crop((int(left * w), int(top * h), int(right * w), int(bottom * h)))
    box = im.getchannel("A").getbbox() or (0, 0, w, h)
    im = im.crop(box)
    w, h = im.size
    return im.crop((int(INSET * w), int(INSET * h), int((1 - INSET) * w), int((1 - INSET) * h)))


def _median(im: Image.Image) -> tuple[int, int, int]:
    data = im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()
    px = [p[:3] for p in data if p[3] > 200]
    if not px:
        return (128, 128, 128)
    return tuple(sorted(c[i] for c in px)[len(px) // 2] for i in range(3))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _luminance(rgb: tuple[int, int, int]) -> float:
    return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255


def sample(path: Path, card_id: str) -> dict:
    card = _card_box(Image.open(path).convert("RGBA"), card_id)
    w, h = card.size
    if h > w:  # portrait card: sample along its own diagonal the same way
        card = card.rotate(90, expand=True)
        w, h = card.size
    cell = (w // 3, h // 3)
    stops = [
        _median(card.crop((x, y, x + cell[0], y + cell[1])))
        for x, y in ((0, 0), (w // 3, h // 3), (w - cell[0], h - cell[1]))
    ]
    overall = _median(card)
    return {
        "stops": [_hex(s) for s in stops],
        "ink": "dark" if _luminance(overall) > 0.55 else "light",
    }


def main() -> None:
    manifest = json.loads((ART / "manifest.json").read_text())
    colors = {cid: sample(ART / entry["file"], cid) for cid, entry in sorted(manifest.items())}
    OUT.write_text(json.dumps(colors, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(colors)} cards")


if __name__ == "__main__":
    main()
