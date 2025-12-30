# -*- coding: utf8 -*-
from __future__ import unicode_literals

import os
import random
import time
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from PIL.Image import Transform
from PIL.ImageFont import Layout

random.seed(time.time() * 1000)


class Captcha(object):
    LOWER_LETTERS = 'abcdefghjkmnpqrstuvwxy'  # 小写字母，去除可能干扰的i，l，o，z
    UPPER_LETTERS = LOWER_LETTERS.upper()
    NUMBERS = '2345689'
    INIT_CHARS = ''.join((LOWER_LETTERS, UPPER_LETTERS, NUMBERS))

    def __init__(
        self,
        img_type='GIF',
        mode='RGB',
        bg_color=(255, 255, 255),
        fg_color=(0, 0, 255),
        init_chars=INIT_CHARS,
        char_length=4,
        size=(120, 30),
        font_size=18,
        n_line=(1, 2),
        point_chance=2,
    ):  # pylint:disable=too-many-positional-arguments
        """
        :param size: 图片的大小，格式（宽，高），默认为(120, 30)
        :param chars: 允许的字符集合，格式字符串
        :param img_type: 图片保存的格式，默认为GIF，可选的为GIF，JPEG，TIFF，PNG
        :param mode: 图片模式，默认为RGB
        :param bg_color: 背景颜色，默认为白色
        :param fg_color: 前景色，验证码字符颜色，默认为蓝色#0000FF
        :param font_size: 验证码字体大小
        :param font_type: 验证码字体，默认为 ae_AlArabiya.ttf
        :param length: 验证码字符个数
        :param draw_lines: 是否划干扰线
        :param n_lines: 干扰线的条数范围，格式元组，默认为(1, 2)，只有draw_lines为True时有效
        :param draw_points: 是否画干扰点
        :param point_chance: 干扰点出现的概率，大小范围[0, 100]
        :return Image, code_text
        """
        self.img_type = img_type
        self.mode = mode
        self.init_chars = init_chars
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.char_length = char_length
        self.size = size
        self.width, self.height = self.size
        self.n_line = n_line
        self.point_chance = point_chance
        self.font = os.path.abspath(os.path.join(os.path.dirname(__file__), 'MONACO.TTF'))
        self.font_size = font_size

        self.img = Image.new(mode, size, bg_color)  # 创建图形
        self.draw = ImageDraw.Draw(self.img)  # 创建画笔

    def get_chars(self):
        return random.sample(self.init_chars, self.char_length)

    def create_lines(self):
        """绘制干扰线"""
        line_num = random.randint(*self.n_line)  # 干扰线条数
        for i in range(line_num):
            # 起始点
            begin = (random.randint(0, self.size[0]), random.randint(0, self.size[1]))
            # 结束点
            end = (random.randint(0, self.size[0]), random.randint(0, self.size[1]))
            self.draw.line([begin, end], fill=(0, 0, 0))

    def create_points(self):
        """绘制干扰点"""
        chance = min(100, max(0, int(self.point_chance)))  # 大小限制在[0, 100]

        for width_ in range(self.width):
            for height_ in range(self.height):
                tmp = random.randint(0, 100)
                if tmp > 100 - chance:
                    self.draw.point((width_, height_), fill=(0, 0, 0))

    def create_code(self):
        """绘制字符"""
        c_chars = self.get_chars()
        strs = ' %s ' % ' '.join(c_chars)  # 每个字符前后以空格隔开

        font = ImageFont.truetype(self.font, self.font_size, layout_engine=Layout.RAQM)
        _, _, font_width, font_height = font.getbbox(strs)

        self.draw.text(((self.width - font_width) / 3, (self.height - font_height) / 3), strs, font=font, fill=self.fg_color)

        return ''.join(c_chars)

    def generate(self):
        self.create_lines()
        self.create_points()
        code = self.create_code()

        # 图形扭曲参数
        params = [
            1 - float(random.randint(1, 2)) / 100,
            0,
            0,
            0,
            1 - float(random.randint(1, 10)) / 100,
            float(random.randint(1, 2)) / 500,
            0.001,
            float(random.randint(1, 2)) / 500,
        ]
        img = self.img.transform(self.size, Transform.PERSPECTIVE, params)  # 创建扭曲

        img = img.filter(ImageFilter.EDGE_ENHANCE_MORE)  # 滤镜，边界加强（阈值更大）

        return img, code
