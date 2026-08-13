# -*- coding: utf-8 -*-
"""生成应用图标 icon.ico（用 PIL 绘制）"""

import math

from PIL import Image, ImageDraw, ImageFont


def make_icon(path="assets/icon.ico"):
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角蓝色背景
    radius = 52
    d.rounded_rectangle([4, 4, size - 4, size - 4], radius=radius, fill=(37, 99, 235, 255))

    # 白色 ¥ 符号
    font = None
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"):
        try:
            font = ImageFont.truetype(name, 150)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), "¥", font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    d.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] - 18), "¥",
           font=font, fill=(255, 255, 255, 255))

    # 底部绿色对勾
    cx, cy, r = size / 2, size * 0.66, 40
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(22, 163, 74, 255))
    lw = 12
    d.line([cx - 22, cy, cx - 7, cy + 16, cx + 26, cy - 16],
           fill=(255, 255, 255, 255), width=lw, joint="curve")

    img.save(path, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])


if __name__ == "__main__":
    make_icon()
    print("icon.ico 已生成")
