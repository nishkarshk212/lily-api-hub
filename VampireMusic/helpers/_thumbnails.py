import asyncio
import os
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from VampireMusic import config
from VampireMusic.helpers import Track

_HELP_DIR = Path(__file__).parent


def _font(name: str, size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(_HELP_DIR / name), size)
    except Exception:
        return ImageFont.load_default()


def draw_text_bbox(font, text: str):
    return ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)


def wrap_text(text: str, font, max_w: int, max_lines: int = 2) -> str:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur:
        lines.append(cur)
    return "\n".join(lines[:max_lines])


def _fmt(sec: int) -> str:
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return "0:00"
    m, s = divmod(sec, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
class Thumbnail:
    WIDTH = 1280
    HEIGHT = 720

    def __init__(self):
        from pathlib import Path
        try:
            help_dir = Path(__file__).parent
            self.title_font = ImageFont.truetype(str(help_dir / "Raleway-Bold.ttf"), 48)
            self.small_font = ImageFont.truetype(str(help_dir / "Inter-Light.ttf"), 28)
            self.time_font = ImageFont.truetype(str(help_dir / "Raleway-Bold.ttf"), 24)
        except Exception as e:
            print(f"Error loading fonts: {e}")
            self.title_font = ImageFont.load_default()
            self.small_font = ImageFont.load_default()
            self.time_font = ImageFont.load_default()

        self.session = None

    async def start(self):
        self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()

    async def download_thumb(self, url: str, path: str):
        async with self.session.get(url) as resp:
            resp.raise_for_status()
            with open(path, "wb") as f:
                f.write(await resp.read())

    def create_image(self, thumb_path, output, song):
        # Background (blurred + darkened)
        bg = Image.open(thumb_path).convert("RGB").resize((self.WIDTH, self.HEIGHT))
        bg = bg.filter(ImageFilter.GaussianBlur(55))
        bg = ImageEnhance.Brightness(bg).enhance(0.30)
        bg = ImageEnhance.Contrast(bg).enhance(1.15)
        bg = ImageEnhance.Color(bg).enhance(1.10)

        # Top-down dark gradient for text legibility
        grad = Image.new("L", (self.WIDTH, self.HEIGHT), 0)
        gdraw = ImageDraw.Draw(grad)
        for y in range(self.HEIGHT):
            gdraw.line([(0, y), (self.WIDTH, y)], fill=int(150 * (y / self.HEIGHT)))
        shadow = Image.new("RGB", (self.WIDTH, self.HEIGHT), (0, 0, 0))
        bg = Image.composite(shadow, bg, grad)

        # Glass container
        container_w, container_h = 1140, 420
        cx = (self.WIDTH - container_w) // 2
        cy = (self.HEIGHT - container_h) // 2
        container = Image.new("RGBA", (container_w, container_h), (20, 20, 30, 90))
        cdraw = ImageDraw.Draw(container)
        cdraw.rounded_rectangle(
            (0, 0, container_w, container_h), radius=45,
            outline=(255, 255, 255, 70), width=3,
        )
        bg.paste(container, (cx, cy), container)

        # Album art (rounded)
        cover = 300
        ax, ay = cx + 60, cy + 60
        art = Image.open(thumb_path).convert("RGB").resize((cover, cover))
        mask = Image.new("L", (cover, cover), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cover, cover), radius=32, fill=255)
        art.putalpha(mask)
        bg.paste(art, (ax, ay), art)

        # "NOW PLAYING" pill
        pill_font = _font("Raleway-Bold.ttf", 22)
        pill = "▶ NOW PLAYING"
        pb = draw_text_bbox(pill_font, pill)
        pw, ph = pb[2] - pb[0] + 36, pb[3] - pb[1] + 22
        px, py = ax, ay - 46
        pimg = Image.new("RGBA", (pw, ph), (255, 60, 90, 220))
        pdraw = ImageDraw.Draw(pimg)
        pdraw.rounded_rectangle((0, 0, pw, ph), radius=ph // 2, outline=(255, 255, 255, 80), width=2)
        bg.paste(pimg, (px, py), pimg)
        ImageDraw.Draw(bg).text(
            (px + 18, py + (ph - (pb[3] - pb[1])) // 2 - 2), pill,
            fill="white", font=pill_font,
        )

        draw = ImageDraw.Draw(bg)
        tx = ax + cover + 55
        ty = cy + 95

        title = wrap_text((song.title or "Unknown"), self.title_font, container_w - (tx - cx) - 70, 2)
        draw.multiline_text((tx, ty), title, fill="white", font=self.title_font, spacing=8)

        cy1 = ty + 2 * 60 + 16
        channel = (song.channel_name or "Unknown")
        if len(channel) > 34:
            channel = channel[:33] + "…"
        draw.text((tx, cy1), channel, fill=(200, 210, 230), font=self.small_font)

        meta = []
        if getattr(song, "view_count", None):
            meta.append(f"▶ {song.view_count}")
        if getattr(song, "duration", None):
            meta.append(f"⏱ {song.duration}")
        if meta:
            draw.text((tx, cy1 + 40), "  •  ".join(meta), fill=(170, 180, 200), font=self.small_font)

        # Brand badge
        brand_font = _font("Raleway-Bold.ttf", 26)
        brand = "Vampire Music"
        bb = draw_text_bbox(brand_font, brand)
        bw, bh = (bb[2] - bb[0]) + 40, (bb[3] - bb[1]) + 30
        bx, by = cx + container_w - bw - 55, cy + container_h - bh - 55
        badge = Image.new("RGBA", (bw, bh), (0, 0, 0, 180))
        bdraw = ImageDraw.Draw(badge)
        bdraw.rounded_rectangle((0, 0, bw, bh), radius=15, outline=(255, 255, 255, 50), width=2)
        bg.paste(badge, (bx, by), badge)
        draw.text((bx + 20, by + (bh - (bb[3] - bb[1])) // 2 - 5), brand, fill="white", font=brand_font)

        # Labeled progress bar
        py2 = cy + container_h - 70
        sx, ex = cx + 60, cx + container_w - 60
        draw.line([(sx, py2), (ex, py2)], fill=(200, 200, 200, 150), width=8)
        frac = min(max(getattr(song, "time", 0) / max(getattr(song, "duration_sec", 1) or 1, 1), 0), 1)
        knx = sx + int((ex - sx) * frac)
        draw.ellipse((knx - 12, py2 - 12, knx + 12, py2 + 12), fill="white")
        tfont = _font("Raleway-Bold.ttf", 22)
        cur = _fmt(getattr(song, "time", 0))
        tot = _fmt(getattr(song, "duration_sec", 0))
        draw.text((sx, py2 + 18), cur, fill=(210, 210, 210), font=tfont)
        tb = draw_text_bbox(tfont, tot)
        draw.text((ex - (tb[2] - tb[0]), py2 + 18), tot, fill=(210, 210, 210), font=tfont)

        bg.save(output, quality=95)
        return output

    async def generate(self, song: Track):
        try:
            if not self.session:
                await self.start()

            temp = f"cache/temp_{song.id}.jpg"
            output = f"cache/{song.id}.png"

            if os.path.exists(output):
                return output

            await self.download_thumb(song.thumbnail, temp)

            await asyncio.to_thread(
                self.create_image,
                temp,
                output,
                song,
            )

            if os.path.exists(temp):
                os.remove(temp)

            return output

        except Exception:
            return config.DEFAULT_THUMB
