import os
from PIL import Image, ImageDraw

icons_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(icons_dir, exist_ok=True)

def create_icon(size: int, filename: str):
    # Dark gradient background with purple/indigo theme
    img = Image.new('RGBA', (size, size), color=(15, 23, 42, 255))
    draw = ImageDraw.Draw(img)
    
    # Draw vibrant circle logo
    margin = int(size * 0.1)
    draw.ellipse([margin, margin, size - margin, size - margin], fill=(99, 102, 241, 255))
    
    # Inner accent
    inner_m = int(size * 0.22)
    draw.ellipse([inner_m, inner_m, size - inner_m, size - inner_m], fill=(139, 92, 246, 255))
    
    # Play triangle icon
    poly_p1 = (int(size * 0.42), int(size * 0.32))
    poly_p2 = (int(size * 0.42), int(size * 0.68))
    poly_p3 = (int(size * 0.68), int(size * 0.50))
    draw.polygon([poly_p1, poly_p2, poly_p3], fill=(255, 255, 255, 255))
    
    out_path = os.path.join(icons_dir, filename)
    img.save(out_path, 'PNG')
    print(f"Generated PWA Icon: {out_path}")

if __name__ == '__main__':
    create_icon(192, 'icon-192.png')
    create_icon(512, 'icon-512.png')
