"""Generates screenscope.ico — run once, only if the icon design changes."""
from PIL import Image, ImageDraw

sizes = [16, 32, 48, 64, 128, 256]
images = []
for size in sizes:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    mid = size // 2
    c = (0, 204, 102, 255)
    t = max(1, size // 16)
    draw.rectangle([size // 8, mid - t // 2, size - size // 8, mid + t // 2], fill=c)
    draw.rectangle([mid - t // 2, size // 8, mid + t // 2, size - size // 8], fill=c)
    r = max(1, size // 10)
    draw.ellipse([mid - r, mid - r, mid + r, mid + r], fill=c)
    images.append(img)

# The ICO encoder drops any size larger than the source image, so we save from
# the largest one. append_images supplies the other sizes already drawn, which
# Pillow keeps as they are instead of downscaling them from the 256.
images[-1].save("screenscope.ico", format="ICO",
                sizes=[(s, s) for s in sizes], append_images=images[:-1])
print("screenscope.ico written")
