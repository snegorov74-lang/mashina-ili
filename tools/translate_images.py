#!/usr/bin/env python3
"""Заменяет английские/китайские надписи на картинках сайта русскими.

Читает оригиналы из tools/img_orig/ (при первом запуске копирует их туда из
assets/img/), стирает старый текст цветом фона и пишет русский текст.
Результат перезаписывает файлы в assets/img/remo/ и assets/img/manual/
с теми же именами и размерами.

Нужны Pillow, numpy и scipy:
    python3 -m venv /tmp/venv && /tmp/venv/bin/pip install pillow numpy scipy
    /tmp/venv/bin/python tools/translate_images.py [имя-файла ...]
"""
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
ORIG = ROOT / 'tools' / 'img_orig'
DEST = ROOT / 'assets' / 'img'

FONT_DIR = '/System/Library/Fonts/Supplemental/'
FONTS = {
    'arial': 'Arial.ttf',
    'bold': 'Arial Bold.ttf',
    'narrow': 'Arial Narrow Bold.ttf',
    'bolditalic': 'Arial Bold Italic.ttf',
    'impact': 'Impact.ttf',
}
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def font(name, size):
    return ImageFont.truetype(FONT_DIR + FONTS[name], size)


class Box:
    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = int(x0), int(y0), int(x1), int(y1)

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2

    def __repr__(self):
        return f'Box({self.x0}, {self.y0}, {self.x1}, {self.y1})'


class Canvas:
    def __init__(self, rel):
        self.rel = rel
        src = ORIG / rel
        self.img = Image.open(src).convert('RGB')
        self.a = np.array(self.img).astype(np.int16)

    # ---------- стирание ----------
    def ring_color(self, x0, y0, x1, y1):
        """Медианный цвет по рамке шириной 2 px вокруг прямоугольника."""
        h, w = self.a.shape[:2]
        x0, y0 = max(x0 - 2, 0), max(y0 - 2, 0)
        x1, y1 = min(x1 + 2, w), min(y1 + 2, h)
        sub = self.a[y0:y1, x0:x1]
        ring = np.concatenate([sub[:2].reshape(-1, 3), sub[-2:].reshape(-1, 3),
                               sub[:, :2].reshape(-1, 3), sub[:, -2:].reshape(-1, 3)])
        return tuple(int(v) for v in np.median(ring, axis=0))

    def fill(self, rect, color=None):
        x0, y0, x1, y1 = rect
        color = color or self.ring_color(*rect)
        self.a[y0:y1, x0:x1] = color
        return Box(*rect)

    def wipe(self, rect, bg=None, thr=60, grow=2, whole=False, inpaint=None, fg=None,
             flat=False):
        """Стирает текст в прямоугольнике.

        По умолчанию убирает только связные компоненты «не фона», целиком
        лежащие внутри rect, — линии схемы, выходящие за его границы, остаются.
        whole=True стирает все «не фоновые» пиксели внутри rect.
        fg — функция (массив пикселей) -> маска текста вместо сравнения с фоном.
        Стёртое заливается цветом bg, а если он не задан — диффузией от краёв
        (подходит для фото и градиентного фона). flat=True заливает весь rect
        одним цветом фона — для однотонного фона, где у букв остаётся ореол.
        Возвращает рамку стёртого текста.
        """
        h, w = self.a.shape[:2]
        x0, y0, x1, y1 = rect
        m = 3
        X0, Y0, X1, Y1 = max(x0 - m, 0), max(y0 - m, 0), min(x1 + m, w), min(y1 + m, h)
        sub = self.a[Y0:Y1, X0:X1]
        bgc = bg or self.ring_color(*rect)
        if fg is not None:
            mask = fg(sub)
        else:
            mask = np.abs(sub - np.array(bgc)).max(axis=2) > thr
        inside = np.zeros_like(mask)
        inside[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = True
        if whole:
            mask &= inside
        else:
            lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
            keep = np.zeros(n + 1, bool)
            for i, sl in enumerate(ndimage.find_objects(lab), 1):
                ys, xs = sl
                if (ys.start >= y0 - Y0 and ys.stop <= y1 - Y0 and
                        xs.start >= x0 - X0 and xs.stop <= x1 - X0):
                    keep[i] = True
            mask = keep[lab]
        if not mask.any():
            print(f'  ! {self.rel}: в {rect} нечего стирать')
            return Box(*rect)
        ys, xs = np.nonzero(mask)
        box = Box(xs.min() + X0, ys.min() + Y0, xs.max() + 1 + X0, ys.max() + 1 + Y0)
        if flat:
            sub[inside] = bgc
            return box
        if grow:
            mask = ndimage.binary_dilation(mask, iterations=grow)
        if inpaint is None:
            inpaint = bg is None
        if inpaint:
            self._inpaint(sub, mask)
        else:
            sub[mask] = bgc
        return box

    @staticmethod
    def _inpaint(sub, mask, iters=400):
        f = sub.astype(np.float32)
        known = ~mask
        f[mask] = f[known].mean(axis=0)
        for _ in range(iters):
            avg = (np.roll(f, 1, 0) + np.roll(f, -1, 0) + np.roll(f, 1, 1) + np.roll(f, -1, 1)) / 4
            f[mask] = avg[mask]
        sub[mask] = f[mask].round().astype(np.int16)

    # ---------- текст ----------
    def text(self, lines, box=None, x=None, y=None, face='arial', size=20, color=BLACK,
             halign='l', valign='m', lh=None, maxw=None, stroke=0, stroke_color=None,
             shear=0.0):
        """Пишет строки текста.

        Позиция — либо box (+ halign l/m/r, valign t/m/b: верх заглавных,
        центр блока или базовая линия последней строки), либо x/y, где y —
        базовая линия первой строки. lh — межстрочный шаг в долях кегля.
        maxw — уменьшать кегль, пока самая длинная строка не влезет.
        """
        if isinstance(lines, str):
            lines = lines.split('\n')
        while True:
            f = font(face, size)
            widths = [f.getlength(s) + 2 * stroke for s in lines]
            if not maxw or max(widths) <= maxw or size <= 8:
                break
            size -= 1
        cap = -f.getbbox('Н', anchor='ls')[1]
        step = round(size * (lh or 1.2))
        block = cap + step * (len(lines) - 1)
        if box is not None:
            if x is None:
                x = {'l': box.x0, 'm': box.cx, 'r': box.x1}[halign]
            if y is None:
                y = {'t': box.y0 + cap,
                     'm': box.cy - block / 2 + cap,
                     'b': box.y1 - step * (len(lines) - 1)}[valign]
        anchor = {'l': 'ls', 'm': 'ms', 'r': 'rs'}[halign]
        layer = Image.new('RGBA', self.img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for i, s in enumerate(lines):
            d.text((x, y + i * step), s, font=f, fill=color + (255,), anchor=anchor,
                   stroke_width=stroke, stroke_fill=(stroke_color or color) + (255,))
        if shear:
            yc = y + block / 2 - cap
            layer = layer.transform(layer.size, Image.AFFINE,
                                    (1, shear, -shear * yc, 0, 1, 0), Image.BICUBIC)
        base = Image.fromarray(self.a.clip(0, 255).astype(np.uint8)).convert('RGBA')
        base.alpha_composite(layer)
        self.a = np.array(base.convert('RGB')).astype(np.int16)
        return size

    # ---------- составные операции ----------
    def header(self, x0, x1, text, size=None, y_max=140):
        """Тёмная плашка-заголовок инструкции: белый текст в [x0, x1)."""
        lum = self.a[:y_max, x0:x1].mean(axis=2)
        is_dark = (lum < 80).mean(axis=1) > 0.4
        top = int(np.argmax(is_dark))
        bottom = top
        while bottom + 1 < y_max and is_dark[bottom + 1]:
            bottom += 1
        bottom += 1
        bar = self.a[top:bottom, x0:x1]
        dark = bar.mean(axis=2) < 80
        color = tuple(int(v) for v in np.median(bar[dark], axis=0))
        bright = bar.mean(axis=2) > 110
        ys = np.nonzero(bright.sum(axis=1) >= 3)[0]
        xs = np.nonzero(bright.any(axis=0))[0]
        tx0, tx1 = xs.min() + x0, xs.max() + 1 + x0
        ty0, ty1 = ys.min() + top, ys.max() + 1 + top
        self.a[top + 2:bottom - 2, max(tx0 - 4, x0):min(tx1 + 4, x1)] = color
        # кегль и середина — по старому тексту (вместе с китайскими иероглифами)
        size = size or round((ty1 - ty0) * 0.95)
        self.text(text, box=Box(tx0, ty0 - 1, tx1, ty1 - 1), face='arial', size=size,
                  color=WHITE, maxw=x1 - tx0 - 6)

    def callout(self, rect, lines, size, new=None, face='impact', pad=10):
        """Серая плашка-выноска постера: перекрасить и написать белым."""
        x0, y0, x1, y1 = rect
        sub = self.a[y0:y1, x0:x1]
        lum = sub.mean(axis=2)
        color = tuple(int(v) for v in np.median(sub[(lum > 90) & (lum < 200)], axis=0))
        nx0, ny0, nx1, ny1 = new or rect
        self.a[ny0 + 1:ny1 - 1, nx0 + 1:nx1 - 1] = color
        self.text(lines, box=Box(nx0 + pad, ny0, nx1 - pad, ny1), face=face, size=size,
                  color=WHITE, lh=1.12, maxw=nx1 - nx0 - 2 * pad)

    def badge_new2(self, rect, size, inpaint=False, maxw=None):
        """Красная курсивная плашка «NEW II» -> «Версия II»."""
        def red_or_white(px):
            r, g, b = px[..., 0], px[..., 1], px[..., 2]
            red = (r > 150) & (g < 110) & (b < 110)
            white = (r > 200) & (g > 200) & (b > 200)
            return red | white if inpaint else red
        x0, y0, x1, y1 = rect
        b = self.wipe(rect, fg=red_or_white, whole=True, grow=2, inpaint=inpaint,
                      bg=None if inpaint else WHITE)
        self.text('Версия II', x=b.x0, y=b.y1 - 1, face='bolditalic', size=size,
                  color=(220, 0, 20), stroke=2 if inpaint else 0, stroke_color=WHITE,
                  maxw=maxw)

    def save(self):
        out = DEST / self.rel
        img = Image.fromarray(self.a.clip(0, 255).astype(np.uint8))
        orig = Image.open(ORIG / self.rel)
        assert img.size == orig.size
        if orig.mode == 'L':
            img = img.convert('L')
        if out.suffix == '.jpg':
            img.save(out, quality=90, optimize=True)
        else:
            img.save(out, optimize=True)
        print('  ->', out.relative_to(ROOT))


# ======================================================================
# Описания правок по файлам
# ======================================================================
JOBS = {}


def job(rel):
    def reg(fn):
        JOBS[rel] = fn
        return fn
    return reg


# ---------------------------- remo ----------------------------
@job('remo/chassis-top.jpg')
def _(c):
    c.callout((268, 68, 506, 110), 'Шасси: литая ванна\nиз нейлонового композита', 16)
    c.callout((432, 121, 670, 164), 'Коллекторный мотор 390', 17)
    c.callout((170, 185, 292, 221), 'Стальные приводные\nвалы (дог-боны)', 16,
              new=(120, 185, 292, 221))
    c.callout((403, 221, 506, 248), '5-проводной сервопривод', 16,
              new=(403, 221, 597, 248), pad=7)
    c.callout((787, 191, 940, 234), 'Передний и задний\nдифференциалы', 16)
    c.callout((137, 331, 255, 368), 'Светодиодные\nфары', 16)
    c.callout((780, 540, 910, 576), 'Аккумулятор Li-Ion 2S,\n7,4 В, разъём T-plug', 16,
              new=(780, 540, 958, 576))
    c.callout((680, 633, 888, 691), 'Регулятор хода 3 в 1,\nвлагозащищённый', 17)
    c.callout((436, 692, 617, 735), 'Амортизаторы\nс алюминиевыми колпачками', 16,
              new=(436, 692, 660, 735))


@job('remo/charger.jpg')
def _(c):
    c.fill((30, 460, 1080, 703), WHITE)
    ink = (35, 25, 25)
    lines = [(38, 'а) USB-зарядка включена в блок питания —'),
             (80, 'индикатор горит.'),
             (38, 'б) Аккумулятор подключён к зарядке —'),
             (80, 'индикатор мигает (идёт зарядка).'),
             (38, 'в) Аккумулятор полностью заряжен — индикатор гаснет.'),
             (38, 'Лучше использовать USB-блок питания на 2 А.')]
    for i, (x, s) in enumerate(lines):
        c.text(s, x=x, y=497 + i * 38.6, size=33, color=ink, maxw=1060 - x)


@job('remo/battery-install.jpg')
def _(c):
    ink = (35, 25, 25)
    b = c.wipe((300, 15, 800, 70), bg=WHITE)
    c.text('Подключение аккумулятора', box=b, halign='m', face='bold', size=40, color=ink)
    b = c.wipe((30, 370, 625, 425), bg=WHITE)
    c.text('Соедините разъёмы аккумулятора\nи машины, как на рисунке', box=Box(28, 330, 628, 440),
           halign='m', size=30, color=ink, lh=1.25)
    b = c.wipe((660, 345, 1075, 440), bg=WHITE)
    c.text('Нажмите кнопку питания\nна регуляторе —\nможно ехать', box=b, size=25, color=ink,
           lh=1.15)
    b = c.wipe((665, 160, 775, 200), bg=WHITE)
    c.text('СЕРВО', box=b, size=24, color=ink)
    b = c.wipe((972, 100, 1040, 135), bg=WHITE)
    c.text('Индикатор', box=Box(970, b.y0, 1072, b.y1), halign='r', size=21, color=ink)


@job('remo/tx-rh1.jpg')
def _(c):
    b = c.wipe((15, 25, 200, 80), bg=WHITE)
    c.text('Пульт RH1', box=b, size=40, color=BLACK)
    ink = (75, 75, 75)
    c.wipe((763, 495, 1100, 688), flat=True)
    legend = ['Выключатель', 'Индикатор: красный / зелёный', 'Переключатель Mode 1 / Mode 2',
              'Руль', 'Курок газа', 'Регулировка нейтрали газа', 'Отсек с регулировками']
    for i, s in enumerate(legend):
        c.text(s, x=766, y=519 + i * 26.6, size=22, color=ink, maxw=328)
    b = c.wipe((590, 533, 702, 556), bg=WHITE)
    c.text('НЕЙТРАЛЬ', box=b, face='bold', size=17, color=BLACK)
    c.wipe((590, 557, 712, 668), bg=WHITE)
    for i, s in enumerate(['A — вперёд', 'B — тормоз', 'C — назад', 'L — влево', 'R — вправо']):
        c.text(s, x=593, y=573 + i * 21.6, size=16, color=BLACK)


@job('remo/tx-batteries.jpg')
def _(c):
    b = c.wipe((40, 55, 580, 145), flat=True)
    c.text('БАТАРЕЙКИ\nВ ПУЛЬТ', box=b, halign='m', face='bold', size=44, color=(85, 85, 85),
           lh=1.1)
    b = c.wipe((50, 925, 570, 1008), flat=True)
    c.text('Нужны 4 батарейки АА по 1,5 В\n(не входят в комплект)', box=b, halign='m',
           face='bold', size=33, color=(40, 30, 30), maxw=540, lh=1.15)


@job('remo/tx-mode.jpg')
def _(c):
    for rect, s in [((35, 277, 295, 357), 'Из Mode 1\nв Mode 2'),
                    ((612, 277, 878, 357), 'Из Mode 2\nв Mode 1')]:
        b = c.wipe(rect, flat=True)
        c.text(s, box=b, face='impact', size=36, color=(20, 20, 20), lh=1.08)


@job('remo/dimensions.jpg')
def _(c):
    ink = (25, 25, 25)
    for rect, s, cy in [((450, 160, 545, 232), '125 мм', None),
                        ((205, 350, 305, 412), '210 мм', 379),
                        ((748, 350, 852, 412), '185 мм', 379),
                        ((757, 450, 853, 515), '295 мм', 486)]:
        b = c.wipe(rect, grow=3)
        if cy:
            b = Box(b.x0, cy - 10, b.x1, cy + 10)
        c.text(s, box=b, halign='m', size=27, color=ink)


@job('remo/upgrade-kit.jpg')
def _(c):
    # заголовок: красный с тёмной обводкой
    def title_ink(px):
        r, g, b = px[..., 0], px[..., 1], px[..., 2]
        return ((r > 120) & (g < 90)) | (px.max(axis=2) < 120)
    c.wipe((355, 8, 750, 106), fg=title_ink, whole=True, grow=3)
    c.wipe((350, 5, 755, 110), whole=True, thr=10, grow=2)  # остатки тени
    c.text('Апгрейды', x=550, y=56, halign='m', face='impact', size=50, color=(225, 10, 30),
           stroke=3, stroke_color=(30, 0, 0), shear=0.18)
    c.text('(продаются отдельно)', x=550, y=96, halign='m', face='impact', size=32,
           color=(225, 10, 30), stroke=2, stroke_color=(30, 0, 0), shear=0.18)
    ink = (75, 75, 75)
    caps = [((115, 738, 350, 772), 'Стойка амортизаторов\n(алюминий)'),
            ((410, 738, 690, 772), 'Рычаги подвески\n(алюминий)'),
            ((745, 738, 985, 800), 'Поворотные опоры,\nС-хабы (алюминий)'),
            ((40, 1003, 225, 1068), 'Главная шестерня\nиз закалённой стали'),
            ((258, 1003, 522, 1038), 'Поворотные кулаки\n(алюминий)'),
            ((565, 1003, 795, 1068), 'Задние ступицы\n(алюминий)'),
            ((825, 1003, 1068, 1068), 'Масляные амортизаторы\n(алюминий)')]
    for rect, s in caps:
        b = c.wipe(rect, thr=45, grow=3)
        c.text(s, box=Box(b.x0, b.y0, b.x1, b.y0), halign='m', valign='t', face='impact',
               size=25, color=ink, lh=1.15, maxw=max(b.x1 - b.x0 + 30, 262),
               stroke=1, stroke_color=(245, 245, 245))


@job('remo/motor.jpg')
def _(c):
    c.badge_new2((10, 12, 162, 68), 40, inpaint=True)
    b = c.wipe((150, 498, 292, 538), bg=WHITE)
    c.text('Подшипники', box=b, size=22, color=BLACK)


@job('remo/led.jpg')
def _(c):
    c.badge_new2((20, 25, 165, 75), 36, maxw=140)


@job('remo/diff-gears.jpg')
def _(c):
    c.badge_new2((20, 25, 165, 75), 36, maxw=160)
    ink = (75, 75, 75)
    b = c.wipe((170, 222, 400, 268), bg=WHITE, thr=40)
    c.text('Металлическая главная шестерня', box=b, halign='m', face='impact', size=31,
           color=ink, maxw=520)
    b = c.wipe((128, 478, 452, 528), bg=WHITE, thr=40)
    c.text('Шестерни дифференциала', box=b, halign='m', face='impact', size=36, color=ink,
           maxw=520)


# ---------------------------- manual ----------------------------
@job('manual/monster-assembly.png')
def _(c):
    c.header(10, 880, 'Общая сборка', size=25)


@job('manual/monster-chassis.png')
def _(c):
    c.header(10, 1280, 'Сборка шасси и подвески', size=25)
    b = c.wipe((45, 68, 300, 148), bg=WHITE)
    c.text('Рычаги можно переставить\nна другую сторону', box=b, size=20, color=BLACK,
           lh=1.25)
    b = c.wipe((622, 318, 702, 350), bg=WHITE)
    c.text('Мотор', box=b, halign='m', face='bold', size=21, color=BLACK)
    b = c.wipe((470, 422, 540, 455), bg=WHITE)
    c.text('Сервопривод', box=Box(456, 428, 554, 448), halign='m', size=16, color=BLACK,
           maxw=96)


@job('manual/chassis-assembly.png')
def _(c):
    c.header(400, 880, 'Шасси и трансмиссия', size=24)


@job('manual/diff-gearbox.png')
def _(c):
    c.header(10, 1270, 'Передний и задний дифференциал', size=22)


@job('manual/servo-saver.png')
def _(c):
    c.header(5, 600, 'Сервосейвер и рулевое', size=26)


@job('manual/steering-hubs.png')
def _(c):
    c.header(5, 700, 'Передние поворотные кулаки', size=26)


@job('manual/rear-carriers.png')
def _(c):
    c.header(5, 525, 'Задние ступицы', size=24)


@job('manual/shock-absorber.png')
def _(c):
    c.header(5, 240, 'Амортизатор', size=21)


@job('manual/wheel-p6973.png')
def _(c):
    c.header(5, 330, 'Колесо', size=26)


@job('manual/motor-pinion.png')
def _(c):
    c.header(10, 1280, 'Шестерня мотора', size=24)
    b = c.wipe((78, 158, 205, 205), bg=WHITE)
    c.text('Мотор', box=b, face='bold', size=34, color=BLACK)
    b = c.wipe((1050, 350, 1330, 512), bg=WHITE)
    c.text('При замене шестерни мотора\nсверьтесь со схемой.\nНа моторной пластине\n'
           'три пары отверстий:\nдля 13T, 15T и 17T.', box=b, valign='t', face='bold',
           size=20, color=BLACK, lh=1.3, maxw=330)


@job('manual/electronics.png')
def _(c):
    c.header(10, 1280, 'Схема подключения электроники', size=24)
    k = BLACK
    b = c.wipe((520, 50, 900, 102), bg=WHITE)
    c.text('Вход 5-проводного сервопривода\nРегулятор 3 в 1', box=b, halign='m', size=19,
           color=k, lh=1.3)
    b = c.wipe((90, 180, 248, 210), bg=WHITE)
    c.text('5-проводной\nсервопривод', box=Box(90, 165, 248, 225), halign='m', size=19,
           color=k, lh=1.25)
    b = c.wipe((95, 485, 248, 515), bg=WHITE)
    c.text('Обычный\nсервопривод', box=Box(90, 470, 248, 530), halign='m', size=19, color=k,
           lh=1.25)
    # NOTICE: слово и три строки, треугольник оставляем
    b = c.wipe((110, 280, 216, 308), bg=WHITE)
    c.text('ВНИМАНИЕ!', box=Box(80, b.y0, 214, b.y1), halign='r', size=21, color=k)
    b = c.wipe((42, 312, 326, 388), bg=WHITE)
    c.text('Этот выход не для зарядки\nаккумулятора, только для\n3-проводного сервопривода.',
           box=b, size=18, color=k, lh=1.3, maxw=280)
    b = c.wipe((500, 118, 538, 145), bg=WHITE)
    c.text('Верно', box=Box(b.x0 - 30, b.y0, b.x1, b.y1), halign='r', size=19, color=k)
    b = c.wipe((460, 188, 588, 215), bg=WHITE)
    c.text('Правильно', box=b, halign='m', size=19, color=k)
    b = c.wipe((722, 188, 882, 215), bg=WHITE)
    c.text('Неправильно', box=b, halign='m', size=19, color=k)
    b = c.wipe((478, 264, 526, 290), bg=WHITE)
    c.text('ВЫКЛ', box=b, halign='r', size=16, color=k)
    b = c.wipe((598, 264, 636, 290), bg=WHITE)
    c.text('ВКЛ', box=b, size=19, color=k)
    b = c.wipe((700, 315, 855, 342), bg=WHITE)
    c.text('Разъём\nаккумулятора', box=Box(700, 312, 855, 352), halign='m', size=18, color=k,
           lh=1.15)
    b = c.wipe((860, 356, 943, 383), bg=WHITE)
    c.text('К зарядке', box=b, halign='m', size=19, color=k)
    b = c.wipe((1030, 238, 1248, 266), bg=WHITE)
    c.text('Аккумулятор Li-Ion 7,4 В', box=b, halign='m', size=19, color=k)
    b = c.wipe((1024, 510, 1110, 540), bg=WHITE)
    c.text('Мотор', box=b, halign='m', size=19, color=k)


@job('manual/tools.png')
def _(c):
    c.header(10, 395, 'В комплекте', size=24)
    c.header(500, 1290, 'Полезные инструменты', size=24)
    ink = (35, 35, 35)
    b = c.wipe((32, 86, 262, 116), bg=WHITE)
    c.text('Шестигранные ключи', box=b, face='bold', size=17, color=ink)
    b = c.wipe((35, 322, 220, 348), bg=WHITE)
    c.text('Крестовой ключ', box=b, face='bold', size=14, color=ink)
    b = c.wipe((510, 68, 640, 103), bg=WHITE)
    c.wipe((510, 130, 640, 178), bg=WHITE)
    c.text('Шестигранные отвёртки', box=b, face='bold', size=14, color=ink)
    b = c.wipe((510, 310, 665, 356), bg=WHITE)
    c.text('Крестовая отвёртка', box=b, face='bold', size=14, color=ink)
    b = c.wipe((508, 355, 668, 420), bg=WHITE)
    c.text('Модельный нож', box=b, valign='t', face='bold', size=14, color=ink)
    b = c.wipe((1002, 66, 1110, 128), bg=WHITE)
    c.text('Бокорезы', box=b, valign='t', face='bold', size=14, color=ink)
    b = c.wipe((1121, 66, 1220, 128), bg=WHITE)
    c.text('Изогнутые\nножницы', box=b, valign='t', face='bold', size=14, color=ink)
    b = c.wipe((1247, 66, 1380, 128), bg=WHITE)
    c.text('Длинногубцы', box=b, valign='t', face='bold', size=14, color=ink)
    b = c.wipe((1032, 372, 1106, 410), bg=WHITE)
    c.text('Клей\nдля моделей', box=Box(1000, b.y0, b.x1, b.y1), halign='r', face='bold',
           size=13, color=ink, lh=1.15)


def main(names):
    for rel in JOBS:
        src, dst = ORIG / rel, DEST / rel
        if not src.exists():
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, src)
    for rel, fn in JOBS.items():
        if names and Path(rel).stem not in names and rel not in names:
            continue
        print(rel)
        c = Canvas(rel)
        fn(c)
        c.save()


if __name__ == '__main__':
    main(sys.argv[1:])
