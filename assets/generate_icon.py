from __future__ import annotations

from pathlib import Path
import shutil

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
WEB = ROOT / "web"
BASE = 1024
SCALE = 2
SIZE = BASE * SCALE
RESAMPLE = Image.Resampling.LANCZOS


def px(value: float) -> int:
    return round(value * SCALE)


def rect(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
    return px(x0), px(y0), px(x1), px(y1)


def point(x: float, y: float) -> tuple[int, int]:
    return px(x), px(y)


def vertical_gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    strip = Image.new("RGBA", (1, SIZE))
    pixels = strip.load()
    for y in range(SIZE):
        t = y / (SIZE - 1)
        pixels[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,)
    return strip.resize((SIZE, SIZE), Image.Resampling.BILINEAR)


def rounded_mask(bounds: tuple[int, int, int, int], radius: int) -> Image.Image:
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(bounds, radius=radius, fill=255)
    return mask


def add_radial_glow(image: Image.Image, cx: float, cy: float, rx: float, ry: float,
                    color: tuple[int, int, int], strength: int) -> None:
    gx, gy = px(cx - rx), px(cy - ry)
    gw, gh = max(1, px(rx * 2)), max(1, px(ry * 2))
    gradient = ImageOps.invert(Image.radial_gradient("L")).point(lambda value: max(0, value - 74) * 255 // 181).resize((gw, gh), RESAMPLE)
    left, top = max(0, gx), max(0, gy)
    right, bottom = min(SIZE, gx + gw), min(SIZE, gy + gh)
    if left >= right or top >= bottom:
        return
    crop = gradient.crop((left - gx, top - gy, right - gx, bottom - gy))
    mask = Image.new("L", (SIZE, SIZE), 0)
    mask.paste(crop, (left, top))
    mask = mask.point(lambda value: value * strength // 255)
    glow = Image.new("RGBA", (SIZE, SIZE), color + (0,))
    glow.putalpha(mask)
    image.alpha_composite(glow)


def draw_round_line(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int],
                    width: int, color: tuple[int, int, int, int]) -> None:
    draw.line((start, end), fill=color, width=width)
    radius = width // 2
    for x, y in (start, end):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)


def create_icon() -> Image.Image:
    outer = rounded_mask(rect(72, 72, 952, 952), px(218))

    # A deep blue-violet glass field with soft cyan and orchid light.
    art = vertical_gradient((27, 37, 82), (30, 53, 124))
    add_radial_glow(art, 250, 235, 520, 500, (82, 173, 255), 100)
    add_radial_glow(art, 820, 800, 480, 440, (142, 99, 255), 75)
    # Quiet outer rim and the faint overlapping sheet behind the main page.
    rim = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle(
        rect(73, 73, 951, 951), radius=px(218),
        outline=(230, 245, 255, 112), width=px(2),
    )
    art.alpha_composite(rim)

    back_bounds = rect(324, 244, 747, 802)
    back_mask = rounded_mask(back_bounds, px(58))
    back_shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(back_shadow).rounded_rectangle(
        rect(324, 260, 747, 818), radius=px(58), fill=(4, 9, 35, 105),
    )
    art.alpha_composite(back_shadow.filter(ImageFilter.GaussianBlur(px(22))))
    back = vertical_gradient((163, 193, 255), (115, 146, 226))
    back.putalpha(back_mask.point(lambda value: value * 175 // 255))
    art.alpha_composite(back)
    back_rim = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(back_rim).rounded_rectangle(
        back_bounds, radius=px(58), outline=(236, 246, 255, 155), width=px(2),
    )
    art.alpha_composite(back_rim)

    # Main paper panel, softly lit and raised from the background.
    page_bounds = rect(258, 176, 691, 756)
    page_mask = rounded_mask(page_bounds, px(61))
    page_shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(page_shadow).rounded_rectangle(
        rect(258, 195, 691, 775), radius=px(61), fill=(3, 8, 30, 148),
    )
    art.alpha_composite(page_shadow.filter(ImageFilter.GaussianBlur(px(25))))

    page = vertical_gradient((255, 255, 255), (220, 230, 252))
    page_draw = ImageDraw.Draw(page)
    # A restrained folded corner makes the page recognizable at favicon size.
    page_draw.polygon(
        [point(529, 177), point(690, 177), point(690, 338), point(529, 338)],
        fill=(222, 231, 250, 255),
    )
    page_draw.line(
        [point(529, 178), point(690, 339)],
        fill=(148, 166, 208, 118), width=px(2),
    )
    page.putalpha(page_mask)
    art.alpha_composite(page)

    page_rim = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(page_rim).rounded_rectangle(
        page_bounds, radius=px(61), outline=(255, 255, 255, 235), width=px(3),
    )
    art.alpha_composite(page_rim)

    # Three calm, generously spaced reading lines.
    text_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)
    line_color = (83, 103, 157, 220)
    draw_round_line(text_draw, point(345, 402), point(578, 402), px(22), line_color)
    draw_round_line(text_draw, point(345, 492), point(606, 492), px(22), line_color)
    draw_round_line(text_draw, point(345, 582), point(520, 582), px(22), line_color)
    art.alpha_composite(text_layer)

    # Small aqua glass seal: readable as a check at small Windows and browser sizes.
    badge_center = (691, 686)
    badge_radius = 119
    badge_bounds = rect(
        badge_center[0] - badge_radius, badge_center[1] - badge_radius,
        badge_center[0] + badge_radius, badge_center[1] + badge_radius,
    )
    badge_shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(badge_shadow).ellipse(
        rect(570, 574, 812, 816), fill=(7, 33, 73, 145),
    )
    art.alpha_composite(badge_shadow.filter(ImageFilter.GaussianBlur(px(18))))

    badge_mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(badge_mask).ellipse(badge_bounds, fill=255)
    badge = vertical_gradient((115, 239, 224), (45, 164, 218))
    add_radial_glow(badge, 652, 622, 140, 140, (236, 255, 255), 100)
    badge.putalpha(badge_mask)
    art.alpha_composite(badge)

    badge_rim = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(badge_rim).ellipse(
        badge_bounds, fill=None, outline=(239, 255, 255, 240), width=px(5),
    )
    art.alpha_composite(badge_rim)

    check = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    check_draw = ImageDraw.Draw(check)
    check_points = [point(635, 686), point(674, 726), point(751, 635)]
    check_width = px(27)
    check_draw.line(check_points, fill=(255, 255, 255, 255), width=check_width, joint="curve")
    radius = check_width // 2
    for x, y in (check_points[0], check_points[-1]):
        check_draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                           fill=(255, 255, 255, 255))
    art.alpha_composite(check)

    art.putalpha(ImageChops.multiply(art.getchannel("A"), outer))
    return art.resize((BASE, BASE), RESAMPLE)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)
    master = create_icon()
    master.save(ASSETS / "CodexMarkDone.png", optimize=True)
    master.save(
        ASSETS / "CodexMarkDone.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    master.resize((64, 64), RESAMPLE).save(WEB / "icon-64.png", optimize=True)
    master.resize((32, 32), RESAMPLE).save(WEB / "favicon-32.png", optimize=True)
    master.resize((180, 180), RESAMPLE).save(WEB / "apple-touch-icon.png", optimize=True)
    shutil.copyfile(ASSETS / "CodexMarkDone.ico", WEB / "favicon.ico")


if __name__ == "__main__":
    main()