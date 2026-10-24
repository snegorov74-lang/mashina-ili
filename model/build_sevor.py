"""
Упрощённая 3D-модель Remo Hobby S-EVOR (RH1661), трагги 1:16.

Запуск (headless):
    /Applications/Blender.app/Contents/MacOS/Blender -b --python model/build_sevor.py

Результат рядом со скриптом:
    sevor.glb    — glTF binary для сайта (без камер и света)
    preview.png  — рендер 3/4 спереди-сбоку, 1200x800

Сцена в метрах, Z вверх, низ колёс на Z=0, перед машины смотрит в +Y,
правый борт — +X. Каждая деталь — отдельный именованный объект,
origin объекта — центр его bbox (у колёс — ось вращения).

Переменные окружения:
    SEVOR_ENGINE=EEVEE|CYCLES|WORKBENCH   движок для превью (по умолчанию EEVEE)
    SEVOR_NO_RENDER=1                     только экспорт GLB
    SEVOR_LIVERY=red|blue                 ливрея: red — красно-синяя (машина Ильи,
                                          по умолчанию), blue — официальная синяя;
                                          blue пишет sevor-blue.glb / preview-blue.png

Размеры по спецификации Remo Hobby RH1661: длина 295 мм, ширина 210 мм,
высота 125 мм, база 185 мм, шина Ø 75 мм.

Кузов, крыло, бамперы и шасси описаны в «эскизной» системе координат
(колесо Ø 85, длина 280) и приводятся к реальным размерам матрицей BODY_FRAME:
сдвиг по Z на DZ и растяжение по Y на LEN_SCALE. Колёса строятся сразу
в реальных размерах.
"""

import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
LIVERY = os.environ.get("SEVOR_LIVERY", "red").lower()
SUFFIX = "" if LIVERY == "red" else "-" + LIVERY
GLB_PATH = os.path.join(HERE, f"sevor{SUFFIX}.glb")
PREVIEW_PATH = os.path.join(HERE, f"preview{SUFFIX}.png")

# ---------------------------------------------------------------- размеры, м
WHEEL_R = 0.0375           # шина Ø 75 мм
WHEEL_HW = 0.018           # полуширина колеса
WHEEL_X = 0.105 - WHEEL_HW # центр колеса по X -> общая ширина 0.210
WHEEL_Y = 0.0925           # половина базы 185 мм
WHEEL_Z = WHEEL_R

# эскизная система -> реальные размеры
DZ = WHEEL_Z - 0.0425      # в эскизе ось колеса на высоте 42.5 мм
LEN_SCALE = 0.1475 / 0.140 # в эскизе бамперы на ±140 мм
BODY_FRAME = Matrix.Translation((0, 0, DZ)) @ Matrix.Diagonal((1, LEN_SCALE, 1, 1))
SUSP_FRAME = Matrix.Translation((0, 0, DZ))
WHEEL_Y0 = WHEEL_Y / LEN_SCALE   # ось колеса в эскизе
WHEEL_Z0 = WHEEL_Z - DZ
ARCH_R = WHEEL_R + 0.0022  # радиус арки кузова над колесом

# ---------------------------------------------------------------- материалы


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))


MAT = {}


def make_material(name, hex_color, metallic=0.0, roughness=0.5,
                  emission=None, emission_strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    rgb = hex_rgb(hex_color)
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*hex_rgb(emission), 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    m.diffuse_color = (*rgb, 1.0)       # для Workbench / вьюпорта
    m.metallic = metallic
    m.roughness = roughness
    MAT[name] = m
    return m


def build_materials():
    main, accent = {"red": ("#d7262e", "#2aa7e0"),
                    "blue": ("#1f5fd0", "#eef3f8")}[LIVERY]
    make_material("Body_Main", main, roughness=0.35)
    make_material("Body_Accent", accent, roughness=0.35)
    make_material("Body_Black", "#16171a", roughness=0.45)
    make_material("Glass_Dark", "#24313f", metallic=0.4, roughness=0.08)
    make_material("Plastic_Black", "#1e1f22", roughness=0.6)
    make_material("Plastic_Dark", "#2c2e33", roughness=0.55)
    make_material("Rubber", "#141414", roughness=0.9)
    make_material("Rim_Black", "#202125", metallic=0.2, roughness=0.3)
    make_material("Rim_Inner", "#09090a", roughness=0.8)
    make_material("Metal_Silver", "#c9ccd1", metallic=1.0, roughness=0.25)
    make_material("Metal_Steel", "#6b6f76", metallic=1.0, roughness=0.4)
    make_material("Alu_Red", "#d0202c", metallic=0.8, roughness=0.3)
    make_material("Light_White", "#ffffff", roughness=0.2,
                  emission="#ffffff", emission_strength=3.0)
    make_material("Light_Bar", "#3b4652", roughness=0.2,
                  emission="#6fb0ff", emission_strength=0.7)
    make_material("Lamp_Clear", "#d9dde3", metallic=0.3, roughness=0.15)
    make_material("Motor_Gold", "#b8913a", metallic=1.0, roughness=0.35)
    make_material("Battery_Blue", "#1f5fa8", roughness=0.5)


# ---------------------------------------------------------------- геометрия


def frame_z_to(p0, p1):
    """Матрица: локальная ось Z из p0 в направлении p1, длина возвращается."""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    rot = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_matrix().to_4x4()
    return Matrix.Translation(p0) @ rot, d.length


class Part:
    """Обёртка над bmesh: примитивы с индексом материала, в конце — объект."""

    def __init__(self, name, mats):
        self.name = name
        self.mats = list(mats)
        self.bm = bmesh.new()

    def mi(self, mat):
        return self.mats.index(mat)

    def _v(self, co, M):
        co = Vector(co)
        return self.bm.verts.new(M @ co if M is not None else co)

    def _face(self, verts, mat):
        f = self.bm.faces.new(verts)
        f.material_index = self.mi(mat)
        return f

    def box(self, lo, hi, mat, M=None):
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        v = [self._v(c, M) for c in (
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
        for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                    (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self._face([v[i] for i in idx], mat)

    def cbox(self, center, size, mat, M=None):
        c, s = Vector(center), Vector(size) / 2
        self.box(c - s, c + s, mat, M)

    def lathe(self, prof, mat, segs=32, closed=False, cap0=False, cap1=False, M=None):
        """Тело вращения вокруг локальной оси X. prof = [(x, r), ...]."""
        rings = []
        for x, r in prof:
            ring = []
            for j in range(segs):
                t = 2 * math.pi * j / segs
                ring.append(self._v((x, r * math.cos(t), r * math.sin(t)), M))
            rings.append(ring)
        n = len(rings)
        pairs = [(i, i + 1) for i in range(n - 1)]
        if closed:
            pairs.append((n - 1, 0))
        for a, b in pairs:
            for j in range(segs):
                k = (j + 1) % segs
                self._face([rings[a][j], rings[b][j], rings[b][k], rings[a][k]], mat)
        if cap0:
            self._face(rings[0][::-1], mat)
        if cap1:
            self._face(rings[-1], mat)

    def cyl(self, p0, p1, r, mat, segs=16, r1=None):
        M, L = frame_z_to(p0, p1)
        # строим вдоль X и поворачиваем X -> Z
        rx = Matrix.Rotation(-math.pi / 2, 4, "Y")
        self.lathe([(0, r), (L, r if r1 is None else r1)], mat, segs=segs,
                   cap0=True, cap1=True, M=M @ rx)

    def prism(self, poly, a0, a1, mat, axis="Z"):
        """Призма: многоугольник в плоскости, выдавленный вдоль axis от a0 до a1.
        axis='Z': poly=(x,y); axis='X': poly=(y,z); axis='Y': poly=(x,z)."""
        def co(p, a):
            u, v = p
            return {"Z": (u, v, a), "X": (a, u, v), "Y": (u, a, v)}[axis]
        bot = [self._v(co(p, a0), None) for p in poly]
        top = [self._v(co(p, a1), None) for p in poly]
        self._face(bot[::-1], mat)
        self._face(top, mat)
        n = len(poly)
        for i in range(n):
            j = (i + 1) % n
            self._face([bot[i], bot[j], top[j], top[i]], mat)

    def tube(self, pts, r, mat, segs=6, M=None):
        """Трубка вдоль ломаной (пружина)."""
        pts = [Vector(p) for p in pts]
        rings = []
        for i, p in enumerate(pts):
            a = pts[max(i - 1, 0)]
            b = pts[min(i + 1, len(pts) - 1)]
            t = (b - a).normalized()
            up = Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0))
            bn = t.cross(up).normalized()
            nn = bn.cross(t)
            ring = []
            for j in range(segs):
                ph = 2 * math.pi * j / segs
                ring.append(self._v(p + r * (math.cos(ph) * nn + math.sin(ph) * bn), M))
            rings.append(ring)
        for a in range(len(rings) - 1):
            for j in range(segs):
                k = (j + 1) % segs
                self._face([rings[a][j], rings[a + 1][j], rings[a + 1][k], rings[a][k]], mat)
        self._face(rings[0][::-1], mat)
        self._face(rings[-1], mat)

    def transform(self, M):
        bmesh.ops.transform(self.bm, matrix=M, verts=self.bm.verts)

    def finish(self, sharp_deg=35.0, recalc=True, frame=None):
        bm = self.bm
        if frame is not None:
            bmesh.ops.transform(bm, matrix=frame, verts=bm.verts)
        if recalc:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        thr = math.radians(sharp_deg)
        for f in bm.faces:
            f.smooth = True
        for e in bm.edges:
            e.smooth = len(e.link_faces) == 2 and e.calc_face_angle(math.pi) < thr
        # origin в центр bbox
        lo = Vector([min(v.co[i] for v in bm.verts) for i in range(3)])
        hi = Vector([max(v.co[i] for v in bm.verts) for i in range(3)])
        c = (lo + hi) / 2
        bmesh.ops.translate(bm, vec=-c, verts=bm.verts)
        me = bpy.data.meshes.new(self.name)
        bm.to_mesh(me)
        bm.free()
        for m in self.mats:
            me.materials.append(MAT[m])
        obj = bpy.data.objects.new(self.name, me)
        obj.location = c
        bpy.context.scene.collection.objects.link(obj)
        return obj


# ---------------------------------------------------------------- кузов

# Ключевые сечения кузова спереди назад:
# y, zb (низ борта), wb, zs (плечо), ws, zo (край крыши/капота), wo, zi, wi
BODY_KEYS = [
    (0.137, 0.048, 0.050, 0.064, 0.054, 0.074, 0.046, 0.076, 0.020),
    (0.128, 0.045, 0.062, 0.078, 0.066, 0.084, 0.058, 0.086, 0.022),
    (0.090, 0.045, 0.072, 0.091, 0.080, 0.094, 0.066, 0.097, 0.024),
    (0.050, 0.045, 0.068, 0.090, 0.070, 0.096, 0.060, 0.098, 0.024),
    (0.015, 0.045, 0.068, 0.091, 0.068, 0.116, 0.046, 0.118, 0.020),
    (-0.038, 0.045, 0.068, 0.091, 0.068, 0.116, 0.046, 0.118, 0.020),
    (-0.052, 0.045, 0.068, 0.091, 0.068, 0.099, 0.062, 0.091, 0.030),
    (-0.090, 0.045, 0.072, 0.092, 0.080, 0.101, 0.068, 0.091, 0.030),
    (-0.125, 0.047, 0.068, 0.092, 0.071, 0.099, 0.064, 0.091, 0.030),
    (-0.137, 0.053, 0.060, 0.088, 0.064, 0.094, 0.058, 0.089, 0.030),
]

Y_WINDSHIELD = (0.015, 0.050)
Y_CAB = (-0.038, 0.015)
Y_REARWIN = (-0.052, -0.038)


def body_station(y):
    keys = BODY_KEYS
    if y >= keys[0][0]:
        k = list(keys[0])
    elif y <= keys[-1][0]:
        k = list(keys[-1])
    else:
        for a, b in zip(keys, keys[1:]):
            if a[0] >= y >= b[0]:
                t = (a[0] - y) / (a[0] - b[0])
                k = [pa + (pb - pa) * t for pa, pb in zip(a, b)]
                break
    _, zb, wb, zs, ws, zo, wo, zi, wi = k
    # колёсные арки: низ борта поднимается по окружности над колесом
    for yw in (WHEEL_Y0, -WHEEL_Y0):
        dy = y - yw
        if abs(dy) < ARCH_R:
            zb = max(zb, WHEEL_Z0 + math.sqrt(ARCH_R ** 2 - dy ** 2))
    zb = min(zb, zs - 0.003)
    return [(-wb, zb), (-ws, zs), (-wo, zo), (-wi, zi),
            (wi, zi), (wo, zo), (ws, zs), (wb, zb)]


def body_face_material(ym, e):
    """e — индекс ребра контура 0..6 (0/6 низ борта, 1/5 верх борта,
    2/4 скос крыши, 3 центр)."""
    inside = lambda r: r[0] < ym < r[1]
    near_wheel = min(abs(ym - WHEEL_Y0), abs(ym + WHEEL_Y0)) < ARCH_R + 0.002
    side = min(e, 6 - e)
    if ym > 0.131 and side < 2:
        return "Body_Black"                      # морда / решётка
    if side == 0:
        if near_wheel:
            return "Body_Black"                  # расширители арок
        if -0.06 < ym < 0.045:
            return "Body_Accent"                   # двери
        return "Body_Main"
    if side == 1:
        if -0.036 < ym < 0.036:
            return "Glass_Dark"                  # боковые окна
        if -0.125 < ym < -0.07:
            return "Body_Accent"                   # задние крылья
        return "Body_Main"
    if inside(Y_WINDSHIELD) or inside(Y_REARWIN):
        return "Glass_Dark"
    if side == 2:
        if 0.055 < ym < 0.125:
            return "Body_Accent"                   # полосы на капоте
        return "Body_Main"
    # центр
    if ym < Y_REARWIN[0]:
        return "Body_Black"                      # кузов-«корыто»
    if inside(Y_CAB):
        return "Body_Accent"                       # крыша
    return "Body_Main"


def build_body():
    p = Part("Body", ["Body_Main", "Body_Accent", "Body_Black", "Glass_Dark"])
    y0, y1 = BODY_KEYS[0][0], BODY_KEYS[-1][0]
    ys = {round(k[0], 5) for k in BODY_KEYS}
    n = 36
    ys |= {round(y0 + (y1 - y0) * i / n, 5) for i in range(n + 1)}
    for yw in (WHEEL_Y0, -WHEEL_Y0):
        for i in range(-6, 7):
            ys.add(round(yw + ARCH_R * 0.999 * i / 6, 5))
    ys = sorted(ys, reverse=True)
    # слишком близкие сечения сливаем
    clean = [ys[0]]
    for y in ys[1:]:
        if clean[-1] - y > 0.0025:
            clean.append(y)
    ys = clean

    rows = []
    for y in ys:
        rows.append([p._v((x, y, z), None) for x, z in body_station(y)])
    for s in range(len(rows) - 1):
        ym = (ys[s] + ys[s + 1]) / 2
        for e in range(7):
            a, b = rows[s], rows[s + 1]
            p._face([a[e], b[e], b[e + 1], a[e + 1]], body_face_material(ym, e))
    p._face(rows[0][::-1], "Body_Black")
    p._face(rows[-1], "Body_Black")
    bmesh.ops.recalc_face_normals(p.bm, faces=p.bm.faces)
    # открытая оболочка: убеждаемся, что крыша смотрит вверх
    roof = max(p.bm.faces, key=lambda f: f.calc_center_median().z)
    if roof.normal.z < 0:
        bmesh.ops.reverse_faces(p.bm, faces=p.bm.faces)
    return p.finish(sharp_deg=30.0, recalc=False, frame=BODY_FRAME)


def build_headlights():
    p = Part("Headlights", ["Light_White", "Light_Bar", "Lamp_Clear"])
    # светящаяся планка под передним бампером
    p.box((-0.038, 0.129, 0.0175), (0.038, 0.1392, 0.0285), "Light_Bar")
    for sx in (-1, 1):
        # две белые LED-фары в планке
        p.cyl((sx * 0.022, 0.1385, 0.023), (sx * 0.022, 0.1400, 0.023), 0.0042,
              "Light_White", segs=12)
        # нарисованные фары в морде кузова
        p.cbox((sx * 0.034, 0.1375, 0.068), (0.018, 0.004, 0.006), "Lamp_Clear")
    return p.finish(frame=BODY_FRAME)


# ---------------------------------------------------------------- антикрыло


def build_wing():
    p = Part("Wing", ["Plastic_Black"])
    tilt = Matrix.Translation((0, -0.116, 0.1185)) @ Matrix.Rotation(math.radians(-12), 4, "X")
    p.cbox((0, 0, 0), (0.186, 0.050, 0.0028), "Plastic_Black", M=tilt)
    # gurney flap на задней кромке
    p.cbox((0, -0.0245, 0.003), (0.186, 0.002, 0.006), "Plastic_Black", M=tilt)
    for sx in (-1, 1):
        x0 = sx * 0.093
        poly = [(-0.090, 0.108), (-0.140, 0.106), (-0.140, 0.129), (-0.098, 0.122)]
        p.prism(poly, x0 - 0.0016, x0 + 0.0016, "Plastic_Black", axis="X")
    return p.finish(frame=BODY_FRAME)


def build_wing_mount():
    p = Part("Wing_Mount", ["Plastic_Black"])
    for sx in (-1, 1):
        x0 = sx * 0.028
        poly = [(-0.104, 0.088), (-0.126, 0.088), (-0.131, 0.121), (-0.111, 0.120)]
        p.prism(poly, x0 - 0.0018, x0 + 0.0018, "Plastic_Black", axis="X")
    return p.finish(frame=BODY_FRAME)


# ---------------------------------------------------------------- колёса


def build_wheel(name, cx, cy):
    p = Part(name, ["Rubber", "Rim_Black", "Rim_Inner", "Metal_Silver"])
    hw = WHEEL_HW
    r_rim = 0.0232
    # шина (кольцо с бортиками), внутренний радиус = радиус диска
    p.lathe([(-hw, r_rim), (-hw, 0.0292), (-hw + 0.004, 0.0322),
             (hw - 0.004, 0.0322), (hw, 0.0292), (hw, r_rim)],
            "Rubber", segs=36, closed=True)
    # крупный протектор «ёлочкой»: два ряда грунтозацепов вразбежку
    lugs = 16
    for row in (-1, 1):
        for i in range(lugs):
            a = 2 * math.pi * (i + (0.5 if row > 0 else 0)) / lugs
            M = (Matrix.Rotation(a, 4, "X")
                 @ Matrix.Translation((row * 0.0085, 0, 0.0333))
                 @ Matrix.Rotation(math.radians(22 * row), 4, "Z"))
            p.cbox((0, 0, 0), (0.0165, 0.0068, 0.0080), "Rubber", M=M)
    # чёрный пятиспицевый диск: наружная сторона +X, утоплена
    p.lathe([(-hw + 0.002, r_rim + 0.0002), (hw - 0.003, r_rim + 0.0002),
             (hw - 0.003, r_rim - 0.0022)], "Rim_Black", segs=30, cap0=True)
    xs = hw - 0.0065
    p.lathe([(hw - 0.003, r_rim - 0.0022), (xs, r_rim - 0.0035)], "Rim_Inner",
            segs=30, cap1=True)
    for i in range(5):
        a = 2 * math.pi * i / 5
        M = Matrix.Rotation(a, 4, "X")
        p.box((xs - 0.001, -0.0032, 0.005), (xs + 0.0035, 0.0032, r_rim - 0.0015), "Rim_Black", M=M)
    p.cyl((xs - 0.001, 0, 0), (xs + 0.005, 0, 0), 0.0068, "Rim_Black", segs=10)
    p.cyl((xs + 0.005, 0, 0), (xs + 0.0075, 0, 0), 0.0038, "Metal_Silver", segs=6)
    if cx < 0:
        p.transform(Matrix.Scale(-1, 4, (1, 0, 0)))
    p.transform(Matrix.Translation((cx, cy, WHEEL_Z)))
    return p.finish(sharp_deg=40.0)


# ---------------------------------------------------------------- подвеска


def build_arm(name, sx, yw):
    """Нижний A-рычаг + верхняя тяга + поворотный кулак."""
    p = Part(name, ["Plastic_Dark"])
    poly = [(sx * 0.026, yw - 0.017), (sx * 0.061, yw - 0.007),
            (sx * 0.061, yw + 0.007), (sx * 0.026, yw + 0.017)]
    if sx < 0:
        poly = poly[::-1]
    p.prism(poly, 0.0235, 0.0295, "Plastic_Dark", axis="Z")
    p.cyl((sx * 0.030, yw, 0.0585), (sx * 0.060, yw, 0.0575), 0.0022, "Plastic_Dark", segs=8)
    p.cbox((sx * 0.0625, yw, 0.0425), (0.007, 0.012, 0.038), "Plastic_Dark")
    return p.finish(frame=SUSP_FRAME)


def build_driveshaft(name, sx, yw):
    p = Part(name, ["Metal_Steel"])
    p.cyl((sx * 0.018, yw, WHEEL_Z), (sx * (WHEEL_X - WHEEL_HW), yw, WHEEL_Z), 0.0024, "Metal_Steel", segs=10)
    return p.finish()


def build_shock(name, p0, p1):
    p = Part(name, ["Metal_Silver", "Metal_Steel", "Alu_Red", "Plastic_Black"])
    M, L = frame_z_to(p0, p1)
    z = lambda a, b, r, mat, segs=14: p.lathe(
        [(a, r), (b, r)], mat, segs=segs, cap0=True, cap1=True,
        M=M @ Matrix.Rotation(-math.pi / 2, 4, "Y"))
    z(0.0, 0.005, 0.0028, "Plastic_Black", 10)          # нижний наконечник
    z(0.003, 0.48 * L, 0.0017, "Metal_Silver", 8)       # шток
    z(0.0055, 0.0075, 0.0080, "Metal_Silver")           # нижняя тарелка
    z(0.42 * L, L - 0.004, 0.0053, "Metal_Steel")       # корпус
    z(L - 0.0075, L, 0.0064, "Alu_Red", 14)             # красный алюминиевый колпачок
    # пружина
    turns, per = 7, 14
    za, zb_, rr = 0.0078, L - 0.0076, 0.0071
    pts = []
    for i in range(turns * per + 1):
        t = i / (turns * per)
        a = 2 * math.pi * turns * t
        pts.append((rr * math.cos(a), rr * math.sin(a), za + (zb_ - za) * t))
    p.tube(pts, 0.00115, "Metal_Silver", segs=6, M=M)
    return p.finish(sharp_deg=50.0)


def build_suspension(objs):
    corners = {"FL": (-1, 1), "FR": (1, 1), "RL": (-1, -1), "RR": (1, -1)}
    for tag, (sx, sy) in corners.items():
        yw = sy * WHEEL_Y
        objs.append(build_wheel(f"Wheel_{tag}", sx * WHEEL_X, yw))
        objs.append(build_arm(f"Arm_{tag}", sx, yw))
        objs.append(build_driveshaft(f"Driveshaft_{tag}", sx, yw))
        ys = yw + sy * 0.011
        objs.append(build_shock(f"Shock_{tag}", (sx * 0.052, ys, 0.030 + DZ),
                                (sx * 0.033, ys, 0.085 + DZ)))


# ---------------------------------------------------------------- шасси


def build_chassis():
    p = Part("Chassis", ["Plastic_Black"])
    p.box((-0.032, -0.122, 0.015), (0.032, 0.122, 0.024), "Plastic_Black")
    # боковые борта ванны
    for sx in (-1, 1):
        p.box((sx * 0.030 - 0.002, -0.07, 0.024), (sx * 0.030 + 0.002, 0.07, 0.036), "Plastic_Black")
    # редукторы переднего/заднего моста
    for sy in (-1, 1):
        p.cbox((0, sy * WHEEL_Y0, 0.038), (0.038, 0.030, 0.030), "Plastic_Black")
    return p.finish(frame=BODY_FRAME)


def build_shock_tower(name, sy):
    p = Part(name, ["Plastic_Black"])
    y = sy * (WHEEL_Y + 0.011)
    poly = [(-0.024, 0.040), (0.024, 0.040), (0.040, 0.088), (-0.040, 0.088)]
    p.prism(poly, y - 0.002, y + 0.002, "Plastic_Black", axis="Y")
    return p.finish(frame=SUSP_FRAME)


def build_bumper(name, sy):
    p = Part(name, ["Plastic_Black"])
    y_out = sy * 0.140
    y_in = sy * 0.128
    if sy > 0:
        p.box((-0.052, y_in, 0.0285), (0.052, y_out, 0.045), "Plastic_Black")
        # боковые «клыки»
        for sx in (-1, 1):
            p.box((sx * 0.052 - 0.006, y_in - 0.004, 0.022), (sx * 0.052 + 0.006, y_out, 0.048),
                  "Plastic_Black")
        # нижняя защита, наклонная
        poly = [(0.110, 0.015), (0.130, 0.026), (0.130, 0.032), (0.110, 0.024)]
    else:
        p.box((-0.045, y_out, 0.030), (0.045, y_in, 0.047), "Plastic_Black")
        poly = [(-0.130, 0.030), (-0.110, 0.015), (-0.110, 0.024), (-0.130, 0.036)]
    p.prism(poly, -0.034, 0.034, "Plastic_Black", axis="X")
    return p.finish(frame=BODY_FRAME)


def build_motor():
    p = Part("Motor", ["Motor_Gold", "Metal_Steel"])
    p.cyl((-0.014, -0.040, 0.036), (0.020, -0.040, 0.036), 0.0098, "Motor_Gold", segs=18)
    p.cyl((0.020, -0.040, 0.036), (0.026, -0.040, 0.036), 0.0035, "Metal_Steel", segs=10)
    return p.finish(frame=BODY_FRAME)


def build_battery():
    p = Part("Battery", ["Battery_Blue"])
    p.cbox((0, 0.025, 0.036), (0.040, 0.070, 0.022), "Battery_Blue")
    return p.finish(frame=BODY_FRAME)


# ---------------------------------------------------------------- сцена


def build_car():
    objs = [build_body(), build_headlights(), build_wing(), build_wing_mount(),
            build_chassis(), build_shock_tower("ShockTower_F", 1),
            build_shock_tower("ShockTower_R", -1), build_bumper("Bumper", 1),
            build_bumper("Bumper_Rear", -1), build_motor(), build_battery()]
    build_suspension(objs)
    return objs


def export_glb():
    bpy.ops.export_scene.gltf(
        filepath=GLB_PATH, export_format="GLB", export_apply=True,
        export_cameras=False, export_lights=False, export_yup=True,
        use_selection=False)


def setup_render():
    scene = bpy.context.scene
    # пол
    me = bpy.data.meshes.new("Ground")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=20.0)
    bm.to_mesh(me)
    bm.free()
    ground = bpy.data.objects.new("Ground", me)
    me.materials.append(make_material("Ground", "#eceef1", roughness=0.9))
    scene.collection.objects.link(ground)

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.85, 0.87, 0.9, 1.0)
    bg.inputs["Strength"].default_value = 0.9
    scene.world = world

    sun_data = bpy.data.lights.new("Sun", "SUN")
    sun_data.energy = 3.2
    sun_data.angle = math.radians(10)
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.rotation_euler = (math.radians(42), math.radians(8), math.radians(150))
    scene.collection.objects.link(sun)

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 50
    cam = bpy.data.objects.new("Camera", cam_data)
    target = Vector((0.0, 0.0, 0.054))
    az, el, dist = math.radians(38), math.radians(19), 0.64
    cam.location = target + dist * Vector((math.sin(az) * math.cos(el),
                                           math.cos(az) * math.cos(el), math.sin(el)))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam

    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = 1200, 800, 100
    r.image_settings.file_format = "PNG"
    r.filepath = PREVIEW_PATH
    r.film_transparent = False
    scene.view_settings.view_transform = "Standard"

    engine = os.environ.get("SEVOR_ENGINE", "EEVEE").upper()
    if engine == "CYCLES":
        r.engine = "CYCLES"
        scene.cycles.samples = 96
        scene.cycles.use_denoising = True
    elif engine == "WORKBENCH":
        r.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_shadows = True
    else:
        for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                r.engine = name
                break
            except TypeError:
                continue
        scene.eevee.taa_render_samples = 64


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_materials()
    objs = build_car()
    export_glb()
    print("SEVOR objects:", ", ".join(sorted(o.name for o in objs)))
    print("SEVOR glb: %s (%.1f KB)" % (GLB_PATH, os.path.getsize(GLB_PATH) / 1024))
    if os.environ.get("SEVOR_NO_RENDER"):
        return
    setup_render()
    bpy.ops.render.render(write_still=True)
    print("SEVOR preview:", PREVIEW_PATH)


main()
