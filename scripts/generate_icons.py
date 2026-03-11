#!/usr/bin/env python3
"""Generate icon assets for CoreRag.

Creates menu bar icons (44x44 @2x) and a dock icon (512x512):
  - menubar_icon.png: "CR" in a thin black circle, transparent background
  - menubar_icon_active.png: "CR" in a neon green filled circle
  - dock_icon.png: Dark circle with neon green "CR" text (512x512)
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ASSETS_DIR.mkdir(exist_ok=True)

MENUBAR_SIZE = 44  # 22pt @2x for retina
DOCK_SIZE = 512
NEON_GREEN = "#39FF14"
DARK_BG = "#1a1a2e"
CIRCLE_PADDING = 2
MENUBAR_FONT_SIZE = 20
DOCK_FONT_SIZE = 220


def get_font(size: int):
    """Get a suitable font, falling back to default."""
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


def draw_menubar_icon(fill_color=None, text_color="black", outline_color="black"):
    """Draw a 44x44 menu bar CR icon."""
    img = Image.new("RGBA", (MENUBAR_SIZE, MENUBAR_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bbox = [
        CIRCLE_PADDING,
        CIRCLE_PADDING,
        MENUBAR_SIZE - CIRCLE_PADDING,
        MENUBAR_SIZE - CIRCLE_PADDING,
    ]
    if fill_color:
        draw.ellipse(bbox, fill=fill_color, outline=outline_color, width=2)
    else:
        draw.ellipse(bbox, fill=None, outline=outline_color, width=2)

    font = get_font(MENUBAR_FONT_SIZE)
    text = "CR"
    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    x = (MENUBAR_SIZE - tw) // 2 - tb[0]
    y = (MENUBAR_SIZE - th) // 2 - tb[1]
    draw.text((x, y), text, fill=text_color, font=font)

    return img


def draw_dock_icon():
    """Draw a 512x512 dock icon: dark circle with neon green 'CR' text."""
    size = DOCK_SIZE
    padding = 12
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark filled circle with subtle neon green border
    circle_bbox = [padding, padding, size - padding, size - padding]
    draw.ellipse(circle_bbox, fill=DARK_BG, outline=NEON_GREEN, width=6)

    # "CR" text in neon green, centered
    font = get_font(DOCK_FONT_SIZE)
    text = "CR"
    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    x = (size - tw) // 2 - tb[0]
    y = (size - th) // 2 - tb[1]
    draw.text((x, y), text, fill=NEON_GREEN, font=font)

    return img


def main():
    # Menu bar idle icon
    idle = draw_menubar_icon(fill_color=None, text_color="black", outline_color="black")
    idle.save(ASSETS_DIR / "menubar_icon.png")
    print(f"Created: {ASSETS_DIR / 'menubar_icon.png'}")

    # Menu bar active icon
    active = draw_menubar_icon(fill_color=NEON_GREEN, text_color="black", outline_color=NEON_GREEN)
    active.save(ASSETS_DIR / "menubar_icon_active.png")
    print(f"Created: {ASSETS_DIR / 'menubar_icon_active.png'}")

    # Dock icon
    dock = draw_dock_icon()
    dock.save(ASSETS_DIR / "dock_icon.png")
    print(f"Created: {ASSETS_DIR / 'dock_icon.png'}")


if __name__ == "__main__":
    main()
