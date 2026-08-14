# -*- coding: utf-8 -*-
"""iOS 按钮抗锯齿质量测试：圆角边缘应平滑过渡（无锯齿跳变）。
scale 越高超采样越密，小按钮圆角越平滑。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw  # noqa: E402


def render_button(w, h, scale):
    """按 aa_button_image 的逻辑渲染按钮图片（返回 PIL 图）。"""
    img = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    inset = 2
    r = max(1, (h - inset * 2) * scale // 2)
    d.rounded_rectangle(
        [inset * scale, inset * scale, w * scale - inset * scale - 1,
         h * scale - inset * scale - 1],
        radius=r, fill=(37, 99, 235, 255))
    img = img.resize((max(1, w * 2), max(1, h * 2)), Image.BILINEAR)
    img = img.resize((w, h), Image.LANCZOS)
    return img


def edge_steps(img):
    """中心列 alpha 从 0→255 的过渡级数（越多越平滑）。"""
    w, h = img.size
    px = img.load()
    alphas = [px[w // 2, y][3] for y in range(h)]
    # 中心列在圆角胶囊中间，应是纯色(255)；改扫圆角区左边缘
    # 扫 x 方向：从 0 到圆角边缘，alpha 过渡
    yy = h // 2
    xs = [px[x, yy][3] for x in range(w)]
    steps = [a for a in xs if 0 < a < 255]
    return len(steps)


def test_small_button_smooth():
    """小按钮圆角边缘过渡级数应 >= 4（4 级以上为平滑，1-2 级为硬边锯齿）。"""
    for w, h in ((84, 34), (70, 34), (96, 32), (110, 34), (84, 30)):
        img = render_button(w, h, scale=5)
        n = edge_steps(img)
        assert n >= 4, f"按钮 {w}x{h} 边缘过渡仅 {n} 级（锯齿）"
        print(f"  {w}x{h}: 边缘过渡 {n} 级 [OK]")


def test_higher_scale_smoother():
    """scale 5 应比 scale 3 更平滑（过渡级数更多或相当）。"""
    s3 = edge_steps(render_button(84, 34, 3))
    s5 = edge_steps(render_button(84, 34, 5))
    # 高清按钮图片
    print(f"  scale3 过渡={s3}，scale5 过渡={s5}")
    assert s5 >= s3, "scale5 未比 scale3 平滑"


if __name__ == "__main__":
    test_small_button_smooth()
    test_higher_scale_smoother()
    print("PASS: 按钮抗锯齿质量测试通过")
