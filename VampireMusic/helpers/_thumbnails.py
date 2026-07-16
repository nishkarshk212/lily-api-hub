import asyncio
import os

import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from VampireMusic import config
from VampireMusic.helpers import Track


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
        # Background
        bg = Image.open(thumb_path).convert("RGB").resize((self.WIDTH, self.HEIGHT))

        bg = bg.filter(ImageFilter.GaussianBlur(60))
        bg = ImageEnhance.Brightness(bg).enhance(0.35)

        # Create glass-morphism container
        container_width = 1100
        container_height = 400
        container_x = (self.WIDTH - container_width) // 2
        container_y = (self.HEIGHT - container_height) // 2

        # Container with semi-transparent background
        container = Image.new("RGBA", (container_width, container_height), (255, 255, 255, 40))
        container_draw = ImageDraw.Draw(container)
        
        # Rounded rectangle for container
        container_draw.rounded_rectangle(
            (0, 0, container_width, container_height),
            radius=40,
            outline=(255, 255, 255, 60),
            width=3,
        )
        
        # Paste container onto background
        bg.paste(container, (container_x, container_y), container)
        
        # Album art
        cover_size = 280
        cover_x = container_x + 60
        cover_y = container_y + 60
        cover = Image.open(thumb_path).convert("RGB").resize((cover_size, cover_size))
        
        # Rounded cover
        cover_mask = Image.new("L", (cover_size, cover_size), 0)
        ImageDraw.Draw(cover_mask).rounded_rectangle(
            (0, 0, cover_size, cover_size),
            radius=30,
            fill=255,
        )
        cover.putalpha(cover_mask)
        bg.paste(cover, (cover_x, cover_y), cover)
        
        draw = ImageDraw.Draw(bg)
        
        # Text
        title = (song.title or "Unknown")[:40]
        channel = (song.channel_name or "Unknown")[:35]
        
        text_x = cover_x + cover_size + 60
        text_y = container_y + 120
        
        draw.text(
            (text_x, text_y),
            title,
            fill="white",
            font=self.title_font,
        )
        
        draw.text(
            (text_x, text_y + 70),
            channel,
            fill=(220, 220, 220),
            font=self.small_font,
        )
        
        # Brand badge (like Dolby Atmos style)
        from pathlib import Path
        try:
            help_dir = Path(__file__).parent
            brand_font = ImageFont.truetype(str(help_dir / "Raleway-Bold.ttf"), 26)
        except Exception:
            brand_font = ImageFont.load_default()
        
        brand_text = "Vampire Music"
        bbox = draw.textbbox((0, 0), brand_text, font=brand_font)
        brand_w = bbox[2] - bbox[0]
        brand_h = bbox[3] - bbox[1]
        
        brand_container_w = brand_w + 40
        brand_container_h = brand_h + 30
        brand_container_x = container_x + container_width - brand_container_w - 60
        brand_container_y = container_y + container_height - brand_container_h - 60
        
        # Badge background
        badge_bg = Image.new("RGBA", (brand_container_w, brand_container_h), (0, 0, 0, 180))
        badge_draw = ImageDraw.Draw(badge_bg)
        badge_draw.rounded_rectangle(
            (0, 0, brand_container_w, brand_container_h),
            radius=15,
            outline=(255, 255, 255, 50),
            width=2,
        )
        
        # Paste badge
        bg.paste(badge_bg, (brand_container_x, brand_container_y), badge_bg)
        
        # Draw brand text
        draw.text(
            (brand_container_x + 20, brand_container_y + (brand_container_h - brand_h) // 2 - 5),
            brand_text,
            fill="white",
            font=brand_font,
        )
        
        # Progress bar inside container
        progress_y = container_y + container_height - 120
        progress_start_x = container_x + 60
        progress_end_x = container_x + container_width - 60
        
        # Background line
        draw.line(
            [(progress_start_x, progress_y), (progress_end_x, progress_y)],
            fill=(200, 200, 200, 150),
            width=8,
        )
        
        # Progress circle
        circle_x = progress_start_x + (progress_end_x - progress_start_x) // 3
        draw.ellipse(
            (circle_x - 12, progress_y - 12, circle_x + 12, progress_y + 12),
            fill="white",
        )
        
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
