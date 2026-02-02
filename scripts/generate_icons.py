#!/usr/bin/env python3
"""Generate menu bar icon assets for CoreRag.

Creates two 44x44 (22pt @2x retina) PNG icons:
  - menubar_icon.png: "CR" in a thin black circle, transparent background
  - menubar_icon_active.png: "CR" in a neon green filled circle
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ASSETS_DIR.mkdir(exist_ok=True)

SIZE = 44  # 22pt @2x for retina
NEON_GREEN = "#39FF14"
CIRCLE_PADDING = 2
FONT_SIZE = 20


def get_font(size: int):
    """Get a suitable font, falling back to default."""
    # Try system fonts that look good at small sizes
    candidates = [
        "/System/Library/Fonts/SFCompact-Bold.otf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def draw_icon(fill_color=None, text_color="black", outline_color="black"):
    """Draw a CR icon with optional filled circle."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Circle
    circle_bbox = [CIRCLE_PADDING, CIRCLE_PADDING, SIZE - CIRCLE_PADDING, SIZE - CIRCLE_PADDING]
    if fill_color:
        draw.ellipse(circle_bbox, fill=fill_color, outline=outline_color, width=2)
    else:
        draw.ellipse(circle_bbox, fill=None, outline=outline_color, width=2)

    # Text
    font = get_font(FONT_SIZE)
    text = "CR"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (SIZE - tw) // 2 - bbox[0]
    y = (SIZE - th) // 2 - bbox[1]
    draw.text((x, y), text, fill=text_color, font=font)

    return img


def main():
    # Idle icon: black circle outline, black text, transparent bg
    idle = draw_icon(fill_color=None, text_color="black", outline_color="black")
    idle.save(ASSETS_DIR / "menubar_icon.png")
    print(f"Created: {ASSETS_DIR / 'menubar_icon.png'}")

    # Active icon: neon green filled circle, black text
    active = draw_icon(fill_color=NEON_GREEN, text_color="black", outline_color=NEON_GREEN)
    active.save(ASSETS_DIR / "menubar_icon_active.png")
    print(f"Created: {ASSETS_DIR / 'menubar_icon_active.png'}")


if __name__ == "__main__":
    main()
