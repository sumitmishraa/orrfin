"""Make the synthetic photo invoices for Step 27 (photos of paper and handwritten bills).

Writes evals/extraction-photos/{13-photo-printed,14-photo-handwritten}.{png,json}: images of an invoice
against PO-1 (Shreeji), drawn with Pillow, tilted and noised like a phone photo, plus their answer keys.
All data is fictional. Run:  backend\\.venv\\Scripts\\python backend\\scripts\\make_photo_invoices.py
"""

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "evals" / "extraction" / "01-clean-match.json"
OUT = ROOT / "evals" / "extraction-photos"
HAND_FONT = Path("C:/Windows/Fonts/segoepr.ttf")  # Segoe Print, a handwriting-style font, when present


def _font(size: int, hand: bool) -> ImageFont.ImageFont:
    for path in ([HAND_FONT] if hand else []) + [Path("C:/Windows/Fonts/arial.ttf")]:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def render(key: dict, hand: bool) -> Image.Image:
    img = Image.new("RGB", (1240, 1650), (250, 248, 242) if hand else (255, 255, 255))
    d = ImageDraw.Draw(img)
    big, small = _font(40, hand), _font(28, hand)
    y = 70
    for text, font in [(key["vendor_name"], big), (f"GSTIN: {key['vendor_gstin']}", small),
                       ("TAX INVOICE", big), (f"Invoice No: {key['invoice_no']}", small),
                       (f"Date: {key['invoice_date']}", small), (f"Buyer PO: {key['po_reference']}", small),
                       (f"Buyer GSTIN: {key['buyer_gstin']}   Place of supply: {key['place_of_supply']}", small)]:
        d.text((80, y), text, fill=(20, 20, 60), font=font)
        y += 60 if font is big else 46
    y += 30
    d.text((80, y), "Item code   HSN    Qty   Rate     Amount", fill=(20, 20, 20), font=small)
    y += 50
    for line in key["lines"]:
        d.text((80, y), f"{line.get('item_code') or ''}  {line.get('hsn') or ''}  {line['qty']}  {line['rate']}  {line['amount']}",
               fill=(10, 10, 10), font=small)
        y += 44
        d.text((100, y), line["description"][:60], fill=(60, 60, 60), font=small)
        y += 56
    y += 30
    for label in ("subtotal", "cgst", "sgst", "igst", "total"):
        d.text((700, y), f"{label.upper():<9} {key[label]}", fill=(10, 10, 10), font=small)
        y += 46
    # A phone photo: slightly rotated, a little blur, some grain.
    img = img.rotate(-1.8 if hand else 1.2, expand=True, fillcolor=(205, 200, 190))
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    rnd = random.Random(27 if hand else 13)
    pixels = img.load()
    for _ in range(25000):
        x, yy = rnd.randrange(img.width), rnd.randrange(img.height)
        r, g, b = pixels[x, yy]
        n = rnd.randint(-35, 35)
        pixels[x, yy] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
    return img


def main() -> None:
    base = json.loads(SOURCE.read_text(encoding="utf-8"))["expected_extraction"]
    OUT.mkdir(exist_ok=True)
    for stem, number, day, hand in [("13-photo-printed", "SOS/2026-27/0231", "2026-09-24", False),
                                    ("14-photo-handwritten", "SOS/2026-27/0232", "2026-09-26", True)]:
        key = {**base, "invoice_no": number, "invoice_date": day, "evidence": []}
        render(key, hand).save(OUT / f"{stem}.png", optimize=True)
        (OUT / f"{stem}.json").write_text(json.dumps({
            "about": "Synthetic photo of a paper bill (Step 27). Same PO-1 lines as 01, a new number and date.",
            "expected_extraction": key}, indent=2), encoding="utf-8")
        print("wrote", stem)


if __name__ == "__main__":
    main()
