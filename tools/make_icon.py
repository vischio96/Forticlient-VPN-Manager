"""Generate assets/icon.ico and assets/icon.png (shield + tunnel arc).

Run:  python tools/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
S = 1024  # supersampled canvas


def shield_polygon(cx: float, top: float, w: float, h: float, steps: int = 60):
    """Classic shield: flat-ish top, straight sides, curved point at the bottom."""
    left, right = cx - w / 2, cx + w / 2
    shoulder = top + h * 0.12
    side_end = top + h * 0.52
    bottom = top + h
    def bez(p0, p1, p2, t):
        return ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])

    pts = [(left, shoulder)]
    # top edge: gentle upward curve to the centre and back down
    for i in range(1, steps + 1):
        pts.append(bez((left, shoulder), (cx - w * 0.25, top - h * 0.02), (cx, top), i / steps))
    for i in range(1, steps + 1):
        pts.append(bez((cx, top), (cx + w * 0.25, top - h * 0.02), (right, shoulder), i / steps))
    pts.append((right, side_end))
    # convex lower edges to the point
    for i in range(1, steps + 1):
        pts.append(bez((right, side_end), (right, bottom - h * 0.12), (cx, bottom), i / steps))
    for i in range(1, steps + 1):
        pts.append(bez((cx, bottom), (left, bottom - h * 0.12), (left, side_end), i / steps))
    return pts


def render(size: int, dot=(46, 204, 113, 255)) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # soft shadow
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(shield_polygon(S / 2, 70, 800, 900), fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img.alpha_composite(shadow, (0, 14))

    # shield body: vertical gradient blue
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top_c, bot_c = (41, 121, 255), (16, 52, 140)
    for y in range(S):
        t = y / S
        c = tuple(int(top_c[i] + (bot_c[i] - top_c[i]) * t) for i in range(3)) + (255,)
        gd.line([(0, y), (S, y)], fill=c)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).polygon(shield_polygon(S / 2, 60, 800, 900), fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    # tunnel: three concentric arches (white, fading)
    cx, base = S / 2, 600
    for r, width, alpha in ((260, 56, 255), (170, 50, 225), (82, 44, 200)):
        d.arc([cx - r, base - r, cx + r, base + r], 180, 360, fill=(255, 255, 255, alpha), width=width)
        # vertical legs of the arch
        d.rectangle([cx - r, base - 2, cx - r + width, base + 110], fill=(255, 255, 255, alpha))
        d.rectangle([cx + r - width, base - 2, cx + r, base + 110], fill=(255, 255, 255, alpha))

    # green "online" dot inside the innermost arch
    d.ellipse([cx - 34, base + 10, cx + 34, base + 78], fill=dot)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    big = render(256)
    big.save(ASSETS / "icon.png")
    big.save(ASSETS / "icon.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
                                         (48, 48), (64, 64), (128, 128), (256, 256)])
    # tray variants: green dot = at least one tunnel up, grey dot = idle
    render(64).save(ASSETS / "tray_on.png")
    render(64, dot=(150, 160, 175, 255)).save(ASSETS / "tray_off.png")
    print("written", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
