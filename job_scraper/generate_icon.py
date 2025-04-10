#!/usr/bin/env python3
from PIL import Image, ImageDraw, ImageFont
import os

# Create a new image with a green background
icon_size = 128
img = Image.new('RGBA', (icon_size, icon_size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Draw a rounded rectangle as background
radius = 20
draw.rounded_rectangle([(10, 10), (icon_size-10, icon_size-10)], 
                      radius=radius, 
                      fill=(46, 139, 87, 255))  # Green

# Draw a building icon in the middle
building_color = (255, 255, 255, 240)
# Building base
draw.rectangle([(42, 60), (86, 100)], fill=building_color)
# Building top/roof
draw.polygon([(35, 60), (64, 35), (93, 60)], fill=building_color)
# Windows
window_color = (200, 230, 255, 255)
draw.rectangle([(50, 70), (58, 78)], fill=window_color)
draw.rectangle([(70, 70), (78, 78)], fill=window_color)
draw.rectangle([(50, 84), (58, 92)], fill=window_color)
draw.rectangle([(70, 84), (78, 92)], fill=window_color)

# Add a Euro symbol to indicate jobs/finance
draw.ellipse([(75, 40), (95, 60)], fill=(255, 215, 0, 230))  # Gold circle
# Try to use a font for the Euro symbol, but fallback to a simple 'E' if no font available
try:
    font = ImageFont.truetype('DejaVuSans.ttf', 16)
    draw.text((80, 43), '€', fill=(0, 0, 0, 255), font=font)
except:
    draw.text((80, 43), 'E', fill=(0, 0, 0, 255))

# Save the image
output_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
img.save(output_path)
print(f"Icon saved to {output_path}")
