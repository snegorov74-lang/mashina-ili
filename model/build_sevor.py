"""
Детализированная 3D-модель Remo Hobby S-EVOR (RH1661), трагги 1:16.

Запуск (headless):
    /Applications/Blender.app/Contents/MacOS/Blender -b --python model/build_sevor.py

Результат рядом со скриптом:
    sevor.glb           — glTF binary для сайта (extras на узлах, без камер и света)
    parts.json          — каталог деталей: id, part, name_ru, group, term, parent, center
    preview.png         — рендер 3/4 спереди-сбоку, 1200x800
    preview_nobody.png  — то же без кузова и крыла, вид сверху-сбоку

Сцена в метрах, Z вверх, низ колёс на Z=0, перед машины смотрит в +Y,
правый борт — +X. Размеры по спецификации RH1661: длина 295 мм,
ширина 210 мм, высота 125 мм, база 185 мм, шина Ø 75 мм.

Каждая деталь — отдельный mesh-объект с custom properties part / name_ru /
group / term. Корень: пустышки grp_<group>; узлы (амортизатор, дифференциал,
колесо, сервосейвер) — пустышки-сборки внутри группы. Origin детали — центр bbox.

Переменные окружения:
    SEVOR_ENGINE=EEVEE|CYCLES|WORKBENCH   движок для превью (по умолчанию EEVEE)
    SEVOR_NO_RENDER=1                     только GLB и parts.json
    SEVOR_LIVERY=blue|red                 blue — синяя (машина Ильи, по умолчанию),
                                          red — красно-синяя (файлы с суффиксом -red)
"""

import json
import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
LIVERY = os.environ.get("SEVOR_LIVERY", "blue").lower()
SUFFIX = "" if LIVERY == "blue" else "-" + LIVERY
GLB_PATH = os.path.join(HERE, f"sevor{SUFFIX}.glb")
JSON_PATH = os.path.join(HERE, f"parts{SUFFIX}.json")
PREVIEW_PATH = os.path.join(HERE, f"preview{SUFFIX}.png")
PREVIEW_NOBODY_PATH = os.path.join(HERE, f"preview_nobody{SUFFIX}.png")

# ---------------------------------------------------------------- размеры, м
WR = 0.0375            # радиус шины (Ø 75)
WHW = 0.021            # полуширина колеса
WX = 0.105 - WHW       # центр колеса по X (ширина 210)
WY = 0.0925            # половина базы 185
WZ = WR                # ось колеса
AZ = WZ                # ось дифференциалов и центрального вала
ARM_Z = 0.0215         # оси нижних рычагов
ARM_XI, ARM_XO = 0.022, 0.058
SHOCK_DY = 0.0115      # смещение амортизатора от оси колеса (наружу по Y)
TOWER_Y = 0.1125       # внутренняя грань стойки амортизаторов
MOTOR_X, MOTOR_Z = 0.0195, 0.0446   # ось мотора (межосевое до вала 20.8 мм)
CORNERS = {"FL": (-1, 1), "FR": (1, 1), "RL": (-1, -1), "RR": (1, -1)}
SIDE_RU = {"FL": "передний левый", "FR": "передний правый",
           "RL": "задний левый", "RR": "задний правый"}
SIDE_RU_F = {"FL": "передняя левая", "FR": "передняя правая",
             "RL": "задняя левая", "RR": "задняя правая"}
END_RU = {"F": "передний", "R": "задний"}
END_RU_F = {"F": "передняя", "R": "задняя"}
END_RU_G = {"F": "переднего", "R": "заднего"}

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
    m.diffuse_color = (*rgb, 1.0)
    m.metallic = metallic
    m.roughness = roughness
    MAT[name] = m
    return m


def build_materials():
    main, accent, logo = {"blue": ("#1d4fc4", "#2aa7e0", "#d81f2a"),
                          "red": ("#d7262e", "#2aa7e0", "#f2f2f2")}[LIVERY]
    # кузов и крыло — свои материалы (просмотрщик делает их прозрачными)
    make_material("Body_Main", main, roughness=0.3)
    make_material("Body_Accent", accent, roughness=0.3)
    make_material("Body_Black", "#16171a", roughness=0.4)
    make_material("Body_Logo", logo, roughness=0.3)
    make_material("Body_Glass", "#26323f", metallic=0.4, roughness=0.08)
    make_material("Body_Light", "#e8edf3", roughness=0.15,
                  emission="#ffffff", emission_strength=0.4)
    make_material("Wing_Black", "#1c1d20", roughness=0.5)
    # пластик
    make_material("Plastic_Black", "#1b1c1f", roughness=0.55)
    make_material("Plastic_Dark", "#2b2d31", roughness=0.5)
    make_material("Nylon_Gray", "#4a4d52", roughness=0.5)
    make_material("Gear_Nylon", "#202124", roughness=0.45)
    # металл
    make_material("Steel", "#b7bbc1", metallic=1.0, roughness=0.3)
    make_material("Steel_Dark", "#5d6168", metallic=1.0, roughness=0.4)
    make_material("Chrome", "#dfe2e6", metallic=1.0, roughness=0.12)
    make_material("Alu_Red", "#c81f2a", metallic=1.0, roughness=0.32)
    make_material("Alu_Silver", "#a9adb3", metallic=1.0, roughness=0.35)
    make_material("Brass", "#c9a24a", metallic=1.0, roughness=0.3)
    make_material("Motor_Can", "#c5c8cd", metallic=1.0, roughness=0.28)
    # колёса
    make_material("Rubber", "#151515", roughness=0.85)
    make_material("Rim_Black", "#18191c", roughness=0.35)
    # электрика
    make_material("Wire_Red", "#d2141e", roughness=0.4)
    make_material("Wire_Black", "#101012", roughness=0.4)
    make_material("Wire_White", "#ecebe6", roughness=0.4)
    make_material("Wire_Yellow", "#e0b21a", roughness=0.4)
    make_material("Plug_Red", "#c8161f", roughness=0.4)
    make_material("Plug_White", "#efece3", roughness=0.4)
    make_material("Battery_Blue", "#1e6ed6", roughness=0.35)
    make_material("Label_Black", "#111215", roughness=0.4)
    make_material("Label_Orange", "#f08a1c", roughness=0.4)
    make_material("LED_White", "#ffffff", roughness=0.1,
                  emission="#ffffff", emission_strength=4.0)
    make_material("LED_Bar", "#2e3742", roughness=0.15,
                  emission="#6fb0ff", emission_strength=0.6)
    make_material("Ground", "#eceef1", roughness=0.9)


# ---------------------------------------------------------------- геометрия


def frame_z_to(p0, p1):
    """Матрица с локальной осью Z из p0 в сторону p1 и длина отрезка."""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    rot = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_matrix().to_4x4()
    return Matrix.Translation(p0) @ rot, d.length


ROT_X2Y = Matrix.Rotation(math.pi / 2, 4, "Z")      # локальная X -> мировая Y
ROT_X2Z = Matrix.Rotation(-math.pi / 2, 4, "Y")     # локальная X -> мировая Z
ROT_Z2X = ROT_X2Z.inverted()                        # локальная Z -> X


def axis_m(center, axis):
    """Матрица для примитивов, построенных вдоль локальной X."""
    T = Matrix.Translation(Vector(center))
    return {"X": T, "-X": T @ Matrix.Rotation(math.pi, 4, "Z"),
            "Y": T @ ROT_X2Y, "-Y": T @ Matrix.Rotation(-math.pi / 2, 4, "Z"),
            "Z": T @ ROT_X2Z}[axis]


def gear_pts(n, r_root, r_tip, tip=0.36, flank=0.12):
    """Контур шестерни: 4 точки на зуб."""
    pts = []
    w = 2 * math.pi / n
    for i in range(n):
        a = w * i
        for da, r in ((0, r_root), (flank, r_tip), (flank + tip, r_tip),
                      (2 * flank + tip, r_root)):
            t = a + w * da
            pts.append((r * math.cos(t), r * math.sin(t)))
    return pts


def circle_pts(n, r, a0=0.0):
    return [(r * math.cos(a0 + 2 * math.pi * i / n),
             r * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)]


def catmull(pts, sub=6):
    """Сглаживание ломаной (Catmull-Rom) для проводов."""
    P = [Vector(p) for p in pts]
    P = [P[0]] + P + [P[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(sub):
            t = k / sub
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t
                              + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t))
    out.append(P[-2])
    return out


class Part:
    """Обёртка над bmesh: примитивы с материалом, в конце — объект."""

    def __init__(self, name, mats):
        self.name = name
        self.mats = list(mats)
        self.bm = bmesh.new()

    def mi(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def _v(self, co, M=None):
        co = Vector(co)
        return self.bm.verts.new(M @ co if M is not None else co)

    def _face(self, verts, mat):
        f = self.bm.faces.new(verts)
        f.material_index = self.mi(mat)
        return f

    # --- примитивы
    def box(self, lo, hi, mat, M=None):
        x0, x1 = sorted((lo[0], hi[0]))
        y0, y1 = sorted((lo[1], hi[1]))
        z0, z1 = sorted((lo[2], hi[2]))
        v = [self._v(c, M) for c in (
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
        for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                    (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self._face([v[i] for i in idx], mat)

    def cbox(self, center, size, mat, M=None):
        c, s = Vector(center), Vector(size) / 2
        self.box(c - s, c + s, mat, M)

    def bar(self, p0, p1, w, h, mat, up=(0, 0, 1)):
        """Брусок сечением w x h от p0 до p1 (h — вдоль up)."""
        p0, p1 = Vector(p0), Vector(p1)
        d = p1 - p0
        L = d.length
        x = d.normalized()
        z = Vector(up)
        y = z.cross(x).normalized()
        z = x.cross(y).normalized()
        M = Matrix(((x.x, y.x, z.x, p0.x), (x.y, y.y, z.y, p0.y),
                    (x.z, y.z, z.z, p0.z), (0, 0, 0, 1)))
        self.box((0, -w / 2, -h / 2), (L, w / 2, h / 2), mat, M)

    def lathe(self, prof, mat, segs=32, closed=False, cap0=False, cap1=False,
              M=None, a0=0.0, a1=2 * math.pi):
        """Тело вращения вокруг локальной X. prof = [(x, r), ...]."""
        full = abs(a1 - a0 - 2 * math.pi) < 1e-6
        n_ang = segs if full else segs + 1
        rings = []
        for x, r in prof:
            ring = []
            for j in range(n_ang):
                t = a0 + (a1 - a0) * j / segs
                ring.append(self._v((x, r * math.cos(t), r * math.sin(t)), M))
            rings.append(ring)
        n = len(rings)
        pairs = [(i, i + 1) for i in range(n - 1)]
        if closed:
            pairs.append((n - 1, 0))
        for a, b in pairs:
            for j in range(segs):
                k = (j + 1) % n_ang
                self._face([rings[a][j], rings[b][j], rings[b][k], rings[a][k]], mat)
        if full:
            if cap0:
                self._face(rings[0][::-1], mat)
            if cap1:
                self._face(rings[-1], mat)

    def cyl(self, p0, p1, r, mat, segs=16, r1=None, hole=0.0):
        """Цилиндр (или трубка при hole>0) между двумя точками."""
        M, L = frame_z_to(p0, p1)
        M = M @ ROT_X2Z
        r1 = r if r1 is None else r1
        if hole > 0:
            self.lathe([(0, hole), (0, r), (L, r1), (L, hole)], mat, segs=segs,
                       closed=True, M=M)
        else:
            self.lathe([(0, r), (L, r1)], mat, segs=segs, cap0=True, cap1=True, M=M)

    def ring_extrude(self, outer, r_in, z0, z1, mat, M=None, scale1=1.0):
        """Плоский контур outer (звёздный относительно центра), выдавленный
        по локальной Z от z0 до z1, с отверстием r_in (0 — без отверстия).
        scale1 — масштаб контура на z1 (конические шестерни)."""
        n = len(outer)
        ob = [self._v((x, y, z0), M) for x, y in outer]
        ot = [self._v((x * scale1, y * scale1, z1), M) for x, y in outer]
        for i in range(n):
            j = (i + 1) % n
            self._face([ob[i], ob[j], ot[j], ot[i]], mat)
        if r_in > 0:
            ang = [math.atan2(y, x) for x, y in outer]
            ib = [self._v((r_in * math.cos(a), r_in * math.sin(a), z0), M) for a in ang]
            it = [self._v((r_in * math.cos(a), r_in * math.sin(a), z1), M) for a in ang]
            for i in range(n):
                j = (i + 1) % n
                self._face([ib[j], ib[i], it[i], it[j]], mat)
                self._face([ob[j], ob[i], ib[i], ib[j]], mat)
                self._face([ot[i], ot[j], it[j], it[i]], mat)
        else:
            cb = self._v((0, 0, z0), M)
            ct = self._v((0, 0, z1), M)
            for i in range(n):
                j = (i + 1) % n
                self._face([ob[j], ob[i], cb], mat)
                self._face([ot[i], ot[j], ct], mat)

    def gear(self, M, n, r_root, r_tip, z0, z1, mat, r_in=0.0, scale1=1.0):
        self.ring_extrude(gear_pts(n, r_root, r_tip), r_in, z0, z1, mat, M=M,
                          scale1=scale1)

    def prism(self, poly, a0, a1, mat, axis="Z", M=None):
        """Многоугольник, выдавленный вдоль оси от a0 до a1.
        axis='Z': poly=(x,y); 'X': poly=(y,z); 'Y': poly=(x,z)."""
        def co(p, a):
            u, v = p
            return {"Z": (u, v, a), "X": (a, u, v), "Y": (u, a, v)}[axis]
        bot = [self._v(co(p, a0), M) for p in poly]
        top = [self._v(co(p, a1), M) for p in poly]
        self._face(bot[::-1], mat)
        self._face(top, mat)
        n = len(poly)
        for i in range(n):
            j = (i + 1) % n
            self._face([bot[i], bot[j], top[j], top[i]], mat)

    def tube(self, pts, r, mat, segs=8, M=None, caps=True):
        """Трубка вдоль ломаной (провода, пружины, проволока)."""
        pts = [Vector(p) for p in pts]
        rings = []
        prev_n = None
        for i, p in enumerate(pts):
            a = pts[max(i - 1, 0)]
            b = pts[min(i + 1, len(pts) - 1)]
            t = (b - a).normalized()
            if prev_n is None:
                up = Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0))
                nn = (up - t * up.dot(t)).normalized()
            else:
                nn = (prev_n - t * prev_n.dot(t)).normalized()
            prev_n = nn
            bn = t.cross(nn)
            ring = []
            for j in range(segs):
                ph = 2 * math.pi * j / segs
                ring.append(self._v(p + r * (math.cos(ph) * nn + math.sin(ph) * bn), M))
            rings.append(ring)
        for a in range(len(rings) - 1):
            for j in range(segs):
                k = (j + 1) % segs
                self._face([rings[a][j], rings[a + 1][j], rings[a + 1][k], rings[a][k]], mat)
        if caps:
            self._face(rings[0][::-1], mat)
            self._face(rings[-1], mat)

    def helix(self, z0, z1, r, wire, turns, mat, M=None, per=18, segs=8):
        """Цилиндрическая пружина с поджатыми крайними витками."""
        n = int(turns * per)
        pts = []
        for i in range(n + 1):
            u = i / n
            f = u - 0.75 * math.sin(2 * math.pi * u) / (2 * math.pi)
            a = 2 * math.pi * turns * u
            pts.append((r * math.cos(a), r * math.sin(a), z0 + (z1 - z0) * f))
        self.tube(pts, wire, mat, segs=segs, M=M)

    def eyelet(self, M, r_out, r_in, half, mat, segs=16):
        """Проушина: кольцо с осью по локальной Y матрицы M."""
        self.lathe([(-half, r_in), (-half, r_out), (half, r_out), (half, r_in)], mat,
                   segs=segs, closed=True, M=M @ ROT_X2Y)

    def bearing(self, M, r_out, r_in, w, segs=24):
        """Подшипник вдоль локальной X: стальные кольца + чёрный пыльник."""
        h = w / 2
        rm1, rm2 = r_in + (r_out - r_in) * 0.28, r_in + (r_out - r_in) * 0.72
        self.lathe([(-h, r_in), (-h, rm1), (h, rm1), (h, r_in)], "Steel",
                   segs=segs, closed=True, M=M)
        self.lathe([(-h, rm2), (-h, r_out), (h, r_out), (h, rm2)], "Steel",
                   segs=segs, closed=True, M=M)
        self.lathe([(-h * 0.85, rm1), (-h * 0.85, rm2), (h * 0.85, rm2), (h * 0.85, rm1)],
                   "Plastic_Black", segs=segs, closed=True, M=M)

    def transform(self, M):
        bmesh.ops.transform(self.bm, matrix=M, verts=self.bm.verts)

    def finish(self, sharp_deg=35.0, recalc=True, bevel=0.0, bevel_deg=50.0, segs=2):
        bm = self.bm
        if recalc:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        if bevel > 0:
            thr = math.radians(bevel_deg)
            edges = [e for e in bm.edges if e.is_manifold and e.calc_face_angle(0) > thr]
            if edges:
                bmesh.ops.bevel(bm, geom=edges, offset=bevel, offset_type="OFFSET",
                                segments=segs, profile=0.5, affect="EDGES",
                                clamp_overlap=True)
        thr = math.radians(sharp_deg)
        for f in bm.faces:
            f.smooth = True
        for e in bm.edges:
            e.smooth = len(e.link_faces) == 2 and e.calc_face_angle(math.pi) < thr
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


# ---------------------------------------------------------------- каталог

PARTS = []        # mesh-детали в порядке создания
ASSEMBLIES = {}   # id -> {name_ru, group, part, term}
GROUP_RU = {
    "chassis": "Шасси", "drive": "Трансмиссия", "diff": "Дифференциалы",
    "suspension": "Подвеска", "steering": "Рулевое управление",
    "hubs": "Ступицы и оси", "wheels": "Колёса", "electric": "Электроника",
    "body": "Кузов и антикрыло",
}


def make(p, part, name_ru, group, term="", parent=None, **kw):
    obj = p.finish(**kw)
    assert obj.name == p.name, f"duplicate id {p.name}"
    obj["part"] = part
    obj["name_ru"] = name_ru
    obj["group"] = group
    obj["term"] = term
    PARTS.append({"obj": obj, "parent": parent or f"grp_{group}"})
    return obj


def assembly(aid, name_ru, group, part="", term=""):
    ASSEMBLIES[aid] = {"name_ru": name_ru, "group": group, "part": part, "term": term}
    return aid


def lr(sx, fem=False):
    if fem:
        return "левая" if sx < 0 else "правая"
    return "левый" if sx < 0 else "правый"


# ---------------------------------------------------------------- шасси


def build_tub():
    p = Part("P2501", ["Plastic_Black"])
    # пол центрального отсека с фасками углов
    poly = [(-0.050, -0.064), (-0.042, -0.072), (0.042, -0.072), (0.050, -0.064),
            (0.050, 0.064), (0.042, 0.072), (-0.042, 0.072), (-0.050, 0.064)]
    p.prism(poly, 0.0190, 0.0215, "Plastic_Black")
    # борта ванны
    t = 0.0022
    for i in range(len(poly)):
        a, b = Vector((*poly[i], 0)), Vector((*poly[(i + 1) % len(poly)], 0))
        d = (b - a).normalized()
        n = Vector((d.y, -d.x, 0))
        quad = [tuple(a.xy), tuple(b.xy), tuple((b - n * t).xy), tuple((a - n * t).xy)]
        h = 0.034 if abs(d.y) > 0.5 else 0.030
        p.prism(quad, 0.0215, h, "Plastic_Black")
    # шейки под редукторами
    for sy in (-1, 1):
        p.box((-0.024, sy * 0.072, 0.0165), (0.024, sy * 0.114, 0.0195), "Plastic_Black")
    # рёбра жёсткости
    for x in (-0.030, 0.030):
        p.box((x - 0.001, -0.068, 0.0215), (x + 0.001, 0.068, 0.0245), "Plastic_Black")
    for y in (-0.040, 0.0, 0.040):
        p.box((-0.048, y - 0.001, 0.0215), (0.048, y + 0.001, 0.0240), "Plastic_Black")
    # бобышки: стойки сервосейвера, опора подшипника вала, ложементы сервопривода
    for sx in (-1, 1):
        p.cyl((sx * 0.020, 0.066, 0.0215), (sx * 0.020, 0.066, 0.034), 0.0035,
              "Plastic_Black", segs=14)
    p.box((-0.006, -0.0615, 0.0215), (0.006, -0.0585, 0.034), "Plastic_Black")
    for y in (0.014, 0.050):
        p.box((0.011, y - 0.003, 0.0215), (0.039, y + 0.003, 0.025), "Plastic_Black")
    return make(p, "P2501", "Ванна шасси (нижняя рама)", "chassis", "chassis",
                bevel=0.0006)


def build_top_plate():
    p = Part("P2502", ["Plastic_Black"])
    z0, z1 = 0.058, 0.0615
    for sx in (-1, 1):
        p.box((sx * 0.0045, -0.074, z0), (sx * 0.0070, 0.074, z1), "Plastic_Black")
    for i in range(6):     # шевроны
        y = -0.060 + i * 0.024
        for sx in (-1, 1):
            p.bar((0, y, z0 + 0.0015), (sx * 0.0058, y + 0.009, z0 + 0.0015),
                  0.0022, 0.003, "Plastic_Black")
    for sy in (-1, 1):     # накладки на редукторы
        p.box((-0.0215, sy * 0.074, z0), (0.0215, sy * 0.098, z1), "Plastic_Black")
    return make(p, "P2502", "Верхняя пластина (центральная распорка)", "chassis",
                "chassis", bevel=0.0005)


def build_gearbox(end):
    sy = 1 if end == "F" else -1
    yc = sy * WY
    p = Part(f"GEARBOX_{end}", ["Plastic_Dark"])
    p.box((-0.0225, yc - 0.0185, 0.0170), (0.0225, yc + 0.0185, 0.0580), "Plastic_Dark")
    for sx in (-1, 1):
        # бобышки подшипников выходных чашек
        p.cyl((sx * 0.0215, yc, AZ), (sx * 0.0255, yc, AZ), 0.0085, "Plastic_Dark",
              segs=24, hole=0.0045)
        # проушины осей рычагов
        for dy in (-0.0165, 0.0165):
            p.box((sx * 0.0195, yc + dy - 0.0025, 0.0165),
                  (sx * 0.0255, yc + dy + 0.0025, 0.0265), "Plastic_Dark")
        # крепление верхней тяги
        p.cyl((sx * 0.0235, yc - 0.0045, 0.0555), (sx * 0.0235, yc + 0.0045, 0.0555),
              0.0030, "Plastic_Dark", segs=14)
    # тоннель вала
    p.cyl((0, yc - sy * 0.0185, AZ), (0, yc - sy * 0.025, AZ), 0.0065, "Plastic_Dark",
          segs=20, hole=0.0040)
    return make(p, "", f"Корпус {END_RU_G[end]} редуктора", "chassis", "diff",
                bevel=0.0012)


def build_shock_tower(end):
    sy = 1 if end == "F" else -1
    p = Part(f"P2504_{end}", ["Plastic_Black", "Steel"])
    y0, y1 = sy * TOWER_Y, sy * (TOWER_Y + 0.0028)
    poly = [(-0.022, 0.040), (0.022, 0.040), (0.034, 0.067), (0.047, 0.083),
            (0.047, 0.0885), (-0.047, 0.0885), (-0.047, 0.083), (-0.034, 0.067)]
    p.prism(poly, y0, y1, "Plastic_Black", axis="Y")
    for sx in (-1, 1):
        p.bar((sx * 0.012, y0, 0.042), (sx * 0.040, y0, 0.085), 0.004, 0.003,
              "Plastic_Black", up=(0, 1, 0))
        # пальцы верхнего крепления амортизаторов
        p.cyl((sx * 0.031, y0, 0.086), (sx * 0.031, sy * (WY + SHOCK_DY - 0.0018), 0.086),
              0.0014, "Steel", segs=10)
    p.box((-0.016, sy * (WY + 0.0185), 0.030), (0.016, y0, 0.054), "Plastic_Black")
    return make(p, "P2504", f"Стойка амортизаторов {END_RU_F[end]}", "chassis",
                "chassis", bevel=0.0006)


def build_body_post(end):
    sy = 1 if end == "F" else -1
    p = Part(f"P2517_{end}", ["Plastic_Black"])
    top_y, top_z = (0.100, 0.104) if end == "F" else (-0.104, 0.103)
    p.box((-0.017, sy * TOWER_Y, 0.0840), (0.017, sy * (TOWER_Y + 0.004), 0.0885),
          "Plastic_Black")
    for sx in (-1, 1):
        p.cyl((sx * 0.014, sy * (TOWER_Y + 0.002), 0.0860), (sx * 0.014, top_y, top_z),
              0.0026, "Plastic_Black", segs=12)
    return make(p, "P2517", f"Стойка кузова {END_RU_F[end]}", "chassis", "body",
                bevel=0.0004)


def build_bumper_front():
    p = Part("P2503", ["Plastic_Black"])
    prof = [(0.1270, 0.0270), (0.1385, 0.0280), (0.1395, 0.0500), (0.1330, 0.0525),
            (0.1300, 0.0490), (0.1350, 0.0475), (0.1345, 0.0315), (0.1270, 0.0305)]
    p.prism(prof, -0.056, 0.056, "Plastic_Black", axis="X")
    for sx in (-1, 1):     # «клыки» по краям
        p.box((sx * 0.050, 0.124, 0.022), (sx * 0.060, 0.1395, 0.052), "Plastic_Black")
    skid = [(0.1060, 0.0160), (0.1290, 0.0230), (0.1290, 0.0280), (0.1060, 0.0200)]
    p.prism(skid, -0.030, 0.030, "Plastic_Black", axis="X")
    p.box((-0.018, WY + 0.0185, 0.024), (0.018, 0.128, 0.040), "Plastic_Black")
    return make(p, "P2503", "Передний бампер", "chassis", "bumper", bevel=0.0007)


def build_bumper_rear():
    p = Part("P2514", ["Plastic_Black"])
    prof = [(-0.1265, 0.0290), (-0.1360, 0.0300), (-0.1365, 0.0520), (-0.1300, 0.0540),
            (-0.1265, 0.0500)]
    p.prism(prof, -0.050, 0.050, "Plastic_Black", axis="X")
    for i in range(7):
        x = -0.036 + i * 0.012
        p.box((x - 0.0012, -0.1372, 0.034), (x + 0.0012, -0.1360, 0.048), "Plastic_Black")
    skid = [(-0.1060, 0.0160), (-0.1265, 0.0250), (-0.1265, 0.0300), (-0.1060, 0.0200)]
    p.prism(skid, -0.028, 0.028, "Plastic_Black", axis="X")
    p.box((-0.018, -(WY + 0.0185), 0.024), (0.018, -0.1265, 0.040), "Plastic_Black")
    return make(p, "P2514", "Задний бампер", "chassis", "bumper", bevel=0.0007)


def build_wing_mount():
    p = Part("WING_MOUNT", ["Plastic_Black"])
    p.box((-0.030, -0.1160, 0.0895), (0.030, -0.1420, 0.0925), "Plastic_Black")
    for sx in (-1, 1):
        p.box((sx * 0.010, -0.1150, 0.0820), (sx * 0.014, -0.1340, 0.0895), "Plastic_Black")
        p.box((sx * 0.0195, -0.1180, 0.0925), (sx * 0.0255, -0.1360, 0.0945), "Plastic_Black")
    return make(p, "", "Крепление антикрыла", "chassis", "wing", bevel=0.0006)


# ---------------------------------------------------------------- трансмиссия


def build_drive():
    M_motor = axis_m((MOTOR_X, 0, MOTOR_Z), "Y")    # локальная X -> +Y
    p = Part("E9661", ["Motor_Can", "Plastic_Black", "Steel", "Brass"])
    p.lathe([(-0.0575, 0.0030), (-0.0575, 0.0105), (-0.0565, 0.0130), (-0.0555, 0.0139),
             (-0.0215, 0.0139), (-0.0205, 0.0130)], "Motor_Can", segs=40, cap0=True,
            cap1=True, M=M_motor)
    p.lathe([(-0.0205, 0.0132), (-0.0150, 0.0132), (-0.0140, 0.0110), (-0.0140, 0.0030)],
            "Plastic_Black", segs=40, cap1=True, M=M_motor)
    p.lathe([(-0.0600, 0.0042), (-0.0575, 0.0042)], "Motor_Can", segs=20, cap0=True,
            M=M_motor)
    p.cyl((MOTOR_X, -0.0675, MOTOR_Z), (MOTOR_X, -0.0130, MOTOR_Z), 0.00115, "Steel",
          segs=10)
    for sx in (-1, 1):     # щёткодержатели и клеммы
        p.cyl((MOTOR_X + sx * 0.0128, -0.0180, MOTOR_Z),
              (MOTOR_X + sx * 0.0158, -0.0180, MOTOR_Z), 0.0028, "Plastic_Black", segs=12)
        p.box((MOTOR_X + sx * 0.0045 - 0.001, -0.0170, MOTOR_Z + 0.0125),
              (MOTOR_X + sx * 0.0045 + 0.001, -0.0160, MOTOR_Z + 0.0165), "Brass")
    make(p, "E9661", "Мотор 390 коллекторный", "drive", "brushed", sharp_deg=40)

    # радиатор мотора: хомут на ~240° с рёбрами
    p = Part("E9661_heatsink", ["Alu_Red"])
    a0, a1 = math.radians(-30), math.radians(210)
    p.lathe([(-0.0530, 0.0140), (-0.0530, 0.0148), (-0.0235, 0.0148), (-0.0235, 0.0140)],
            "Alu_Red", segs=40, closed=True, M=M_motor, a0=a0, a1=a1)
    n_fin = 17
    for i in range(n_fin):
        a = a0 + (a1 - a0) * (i + 0.5) / n_fin
        R = Matrix.Rotation(a, 4, "X")
        p.box((-0.0530, -0.0006, 0.0146), (-0.0235, 0.0006, 0.0190), "Alu_Red",
              M=M_motor @ R)
    make(p, "E9661", "Радиатор мотора", "drive", "brushed")

    # моторная пластина с отверстием под вал
    p = Part("A4027", ["Alu_Silver"])
    cx, cz = MOTOR_X, MOTOR_Z
    rect = []
    for i in range(48):
        a = 2 * math.pi * i / 48
        dx, dz = math.cos(a), math.sin(a)
        lim = []
        for edge, comp in ((0.040 - cx, dx), (0.006 - cx, dx), (0.068 - cz, dz),
                           (0.0215 - cz, dz)):
            if abs(comp) > 1e-9 and comp * edge > 0:
                lim.append(edge / comp)
        t = min(lim)
        rect.append((dx * t, dz * t))
    Mp = Matrix.Translation((cx, -0.0590, cz)) @ Matrix.Rotation(math.pi / 2, 4, "X")
    p.ring_extrude(rect, 0.0055, 0.0, 0.0016, "Alu_Silver", M=Mp)
    make(p, "A4027", "Моторная пластина", "drive", "", bevel=0.0003)

    # шестерня мотора 13T и главная шестерня 39T
    M_pin = axis_m((MOTOR_X, -0.0620, MOTOR_Z), "-Y") @ ROT_Z2X
    p = Part("G2713", ["Steel"])
    p.gear(M_pin, 13, 0.0043, 0.0060, 0.0, 0.0035, "Steel", r_in=0.0012)
    p.cyl((MOTOR_X, -0.0655, MOTOR_Z), (MOTOR_X, -0.0675, MOTOR_Z), 0.0038, "Steel",
          segs=14)
    make(p, "G2713", "Шестерня мотора 13T", "drive", "gearT", sharp_deg=50)

    M_sp = axis_m((0, -0.0625, AZ), "-Y") @ ROT_Z2X
    p = Part("G1610", ["Gear_Nylon"])
    p.gear(M_sp, 39, 0.0147, 0.0164, 0.0, 0.0030, "Gear_Nylon", r_in=0.0110)
    p.ring_extrude(circle_pts(40, 0.0112), 0.0045, 0.0005, 0.0025, "Gear_Nylon", M=M_sp)
    p.cyl((0, -0.0610, AZ), (0, -0.0675, AZ), 0.0048, "Gear_Nylon", segs=20, hole=0.0022)
    make(p, "G1610", "Главная шестерня 39T", "drive", "spur", sharp_deg=50)

    # защита шестерён: дуга над шестернями + задняя стенка
    p = Part("P2516", ["Plastic_Black"])
    Mc = axis_m((0, -0.0595, AZ), "-Y")
    ga0, ga1 = math.radians(-25), math.radians(200)
    p.lathe([(0.0, 0.0200), (0.0, 0.0215), (0.0105, 0.0215), (0.0105, 0.0200)],
            "Plastic_Black", segs=28, closed=True, M=Mc, a0=ga0, a1=ga1)
    p.lathe([(0.0105, 0.0045), (0.0105, 0.0215), (0.0120, 0.0215), (0.0120, 0.0045)],
            "Plastic_Black", segs=28, closed=True, M=Mc, a0=ga0, a1=ga1)
    make(p, "P2516", "Защита шестерён", "drive", "spur")

    p = Part("P2527", ["Steel"])
    p.cyl((0, -0.0815, AZ), (0, 0.0815, AZ), 0.0022, "Steel", segs=14)
    make(p, "P2527", "Центральный вал", "drive", "shaft")

    for end, sy in (("F", 1), ("R", -1)):
        p = Part(f"G1611_{end}", ["Steel"])
        M = axis_m((0, sy * 0.0765, AZ), "Y" if sy > 0 else "-Y") @ ROT_Z2X
        p.gear(M, 13, 0.0044, 0.0062, 0.0, 0.0040, "Steel", r_in=0.0, scale1=0.62)
        p.cyl((0, sy * 0.0752, AZ), (0, sy * 0.0767, AZ), 0.0040, "Steel", segs=14)
        make(p, "G1611", f"Ведущая шестерня {END_RU_G[end]} моста", "drive", "gearT",
             sharp_deg=50)

    for pid, y, r_out, ru in (("B5510_F", 0.0733, 0.0045, "Подшипник вала передний"),
                              ("B5510_R", -0.0733, 0.0045, "Подшипник вала задний"),
                              ("B5511_C", -0.0600, 0.0050,
                               "Подшипник вала у главной шестерни")):
        p = Part(pid, ["Steel", "Plastic_Black"])
        p.bearing(axis_m((0, y, AZ), "Y"), r_out, 0.0022, 0.0025)
        make(p, pid.split("_")[0], ru, "drive", "bearing")

    for tag, (sx, sy) in CORNERS.items():
        y = sy * WY
        p = Part(f"M5367_{tag}", ["Steel"])
        x0, x1 = sx * 0.0255, sx * 0.0600
        p.cyl((x0, y, AZ), (x1, y, AZ), 0.0017, "Steel", segs=12)
        for xe in (x0 + sx * 0.0020, x1 - sx * 0.0020):
            p.lathe([(-0.0022, 0.0012), (-0.0010, 0.0030), (0.0010, 0.0030), (0.0022, 0.0012)],
                    "Steel", segs=16, cap0=True, cap1=True, M=axis_m((xe, y, AZ), "X"))
            p.cyl((xe, y, AZ - 0.0042), (xe, y, AZ + 0.0042), 0.0007, "Steel", segs=8)
        make(p, "M5367", f"Дог-бон (карданчик) {SIDE_RU[tag]}", "drive", "dogbone",
             sharp_deg=50)


# ---------------------------------------------------------------- дифференциалы


def build_diff(end):
    sy = 1 if end == "F" else -1
    yc = sy * WY
    asm = assembly(f"P6952_{end}", f"Дифференциал {END_RU[end]}", "diff", "P6952", "diff")
    Mx = lambda x: axis_m((x, yc, AZ), "X")
    g = END_RU_G[end]

    p = Part(f"P2528_{end}", ["Plastic_Dark"])
    p.lathe([(-0.0155, 0.0032), (-0.0155, 0.0056), (-0.0132, 0.0060), (-0.0130, 0.0105),
             (0.0040, 0.0105), (0.0040, 0.0091), (-0.0116, 0.0091), (-0.0116, 0.0032)],
            "Plastic_Dark", segs=36, closed=True, M=Mx(0))
    for i in range(4):
        R = Matrix.Rotation(math.pi / 2 * i + math.pi / 4, 4, "X")
        p.box((-0.0125, -0.0012, 0.0103), (0.0035, 0.0012, 0.0112), "Plastic_Dark",
              M=Mx(0) @ R)
    make(p, "P2528", f"Корпус {g} дифференциала", "diff", "diff", parent=asm)

    p = Part(f"G1612_{end}", ["Steel"])
    p.gear(Mx(0.0040) @ ROT_Z2X, 38, 0.0150, 0.0165, 0.0, 0.0035, "Steel", r_in=0.0068,
           scale1=0.93)
    p.lathe([(0.0040, 0.0068), (0.0040, 0.0100), (0.0075, 0.0100), (0.0075, 0.0068)],
            "Steel", segs=30, closed=True, M=Mx(0))
    make(p, "G1612", f"Коронная шестерня {g} дифференциала", "diff", "gearT",
         parent=asm, sharp_deg=50)

    p = Part(f"M5362_{end}", ["Steel"])
    c = Vector((0, yc, AZ))
    p.cyl(c - Vector((0.0018, 0, 0)), c + Vector((0.0018, 0, 0)), 0.0022, "Steel", segs=14)
    dirs = []
    for k in range(3):
        a = math.pi / 2 + 2 * math.pi * k / 3
        d = Vector((0, math.cos(a), math.sin(a)))
        dirs.append(d)
        p.cyl(c, c + d * 0.0078, 0.0011, "Steel", segs=10)
    make(p, "M5362", f"Крестовина сателлитов {g} дифференциала", "diff", "diff",
         parent=asm)

    for k, d in enumerate(dirs, 1):
        p = Part(f"G1613_{end}_{k}", ["Steel"])
        M, _ = frame_z_to(c + d * 0.0072, c)
        p.gear(M, 10, 0.0026, 0.0037, 0.0, 0.0030, "Steel", r_in=0.0011, scale1=0.6)
        make(p, "G1613", f"Сателлит {g} дифференциала №{k}", "diff", "diff",
             parent=asm, sharp_deg=50)

    for side, sx in (("L", -1), ("R", 1)):
        p = Part(f"G1614_{end}_{side}", ["Steel"])
        M, _ = frame_z_to(c + Vector((sx * 0.0078, 0, 0)), c)
        p.gear(M, 16, 0.0045, 0.0060, 0.0, 0.0032, "Steel", r_in=0.0, scale1=0.62)
        p.cyl(c + Vector((sx * 0.0078, 0, 0)), c + Vector((sx * 0.0112, 0, 0)), 0.0030,
              "Steel", segs=14)
        make(p, "G1614", f"Полуосевая шестерня {g} дифференциала {lr(sx, True)}", "diff",
             "diff", parent=asm, sharp_deg=50)

        p = Part(f"P2521_{end}_{side}", ["Steel"])
        x_in = -0.0130 if sx < 0 else 0.0075
        p.cyl((x_in, yc, AZ), (sx * 0.0215, yc, AZ), 0.0028, "Steel", segs=16)
        Mc = axis_m((sx * 0.0215, yc, AZ), "X" if sx > 0 else "-X")
        p.lathe([(0.0, 0.0028), (0.0, 0.0048), (0.0060, 0.0048), (0.0060, 0.0036),
                 (0.0010, 0.0036), (0.0010, 0.0028)], "Steel", segs=24, closed=True, M=Mc)
        make(p, "P2521", f"Выходная чашка {g} дифференциала {lr(sx, True)}", "diff",
             "diff", parent=asm)

        p = Part(f"B5511_D{end}_{side}", ["Steel", "Plastic_Black"])
        p.bearing(axis_m((sx * 0.0180, yc, AZ), "X"), 0.0050, 0.0028, 0.0030)
        make(p, "B5511", f"Подшипник {g} дифференциала {lr(sx)}", "diff", "bearing",
             parent=asm)


# ---------------------------------------------------------------- подвеска


def build_arm(tag, sx, sy):
    yc = sy * WY
    p = Part(f"P2505_{tag}", ["Plastic_Black", "Steel"])
    th = 0.005
    xi, xo = sx * ARM_XI, sx * ARM_XO
    for s in (-1, 1):
        p.bar((xi, yc + s * 0.0130, ARM_Z), (xo - sx * 0.002, yc + s * 0.0072, ARM_Z),
              0.0045, th, "Plastic_Black")
    p.bar((sx * 0.046, yc - 0.0090, ARM_Z), (sx * 0.046, yc + 0.0090, ARM_Z), 0.0040, th,
          "Plastic_Black")
    p.bar((sx * 0.029, yc - 0.0118, ARM_Z - 0.001), (sx * 0.029, yc + 0.0118, ARM_Z - 0.001),
          0.0030, 0.003, "Plastic_Black")
    p.bar((sx * 0.029, yc - sy * 0.0110, ARM_Z - 0.001),
          (sx * 0.046, yc + sy * 0.0080, ARM_Z - 0.001), 0.0025, 0.003, "Plastic_Black")
    for a, b in ((0.0090, 0.0175), (-0.0175, -0.0090)):
        p.cyl((xi, yc + a, ARM_Z), (xi, yc + b, ARM_Z), 0.0033, "Plastic_Black", segs=14)
    for a, b in ((0.0055, 0.0095), (-0.0095, -0.0055)):
        p.cyl((xo, yc + a, ARM_Z), (xo, yc + b, ARM_Z), 0.0030, "Plastic_Black", segs=14)
    # площадка нижнего крепления амортизатора и палец
    ys = yc + sy * SHOCK_DY
    p.box((sx * 0.0465, yc + sy * 0.0075, ARM_Z), (sx * 0.0535, ys - sy * 0.0015,
          ARM_Z + 0.0045), "Plastic_Black")
    p.cyl((sx * 0.050, yc + sy * 0.0070, 0.0255), (sx * 0.050, ys + sy * 0.0018, 0.0255),
          0.0008, "Steel", segs=8)
    pos = "передний" if sy > 0 else "задний"
    make(p, "P2505", f"Рычаг подвески {pos} {lr(sx)}", "suspension", "arm", bevel=0.0005)

    p = Part(f"F5281_{tag}", ["Steel"])
    p.cyl((xi, yc - 0.0190, ARM_Z), (xi, yc + 0.0185, ARM_Z), 0.0011, "Steel", segs=10)
    p.cyl((xi, yc + sy * 0.0185, ARM_Z), (xi, yc + sy * 0.0200, ARM_Z), 0.0022, "Steel",
          segs=12)
    make(p, "F5281", f"Ось рычага {SIDE_RU_F[tag]}", "suspension", "arm")

    p = Part(f"P2510_pin_{tag}", ["Steel"])
    p.cyl((xo, yc - 0.0100, ARM_Z), (xo, yc + 0.0100, ARM_Z), 0.0010, "Steel", segs=10)
    make(p, "", f"Палец ступицы в рычаге {SIDE_RU[tag]}", "suspension", "arm")

    p = Part(f"P2510_{tag}", ["Plastic_Black"])
    a, b = Vector((sx * 0.0235, yc, 0.0555)), Vector((sx * 0.0585, yc, 0.0545))
    d = (b - a).normalized()
    p.cyl(a + d * 0.003, b - d * 0.003, 0.0016, "Plastic_Black", segs=10)
    for q in (a, b):
        p.cyl(q - Vector((0, 0.0025, 0)), q + Vector((0, 0.0025, 0)), 0.0030,
              "Plastic_Black", segs=14, hole=0.0010)
    make(p, "P2510", f"Верхняя тяга подвески {SIDE_RU_F[tag]}", "suspension", "arm")


def build_shock(tag, sx, sy):
    yc = sy * WY
    ys = yc + sy * SHOCK_DY
    p0 = Vector((sx * 0.050, ys, 0.0255))
    p1 = Vector((sx * 0.031, ys, 0.0860))
    M, L = frame_z_to(p0, p1)
    asm = assembly(f"P6955_{tag}", f"Амортизатор {SIDE_RU[tag]}", "suspension",
                   "P6955", "shock")
    Mz = M @ ROT_X2Z           # локальная X -> ось амортизатора
    ru = SIDE_RU[tag]
    g = ("переднего " if sy > 0 else "заднего ") + ("левого" if sx < 0 else "правого")

    p = Part(f"P6955_endbot_{tag}", ["Plastic_Black"])
    p.eyelet(M, 0.0034, 0.0012, 0.0016, "Plastic_Black")
    p.lathe([(0.0028, 0.0022), (0.0090, 0.0022)], "Plastic_Black", segs=12, cap0=True,
            cap1=True, M=Mz)
    make(p, "P6955", f"Нижний наконечник амортизатора {g}", "suspension", "shock",
         parent=asm)

    p = Part(f"P6955_shaft_{tag}", ["Chrome"])
    p.lathe([(0.0080, 0.0016), (0.0300, 0.0016)], "Chrome", segs=12, cap0=True, cap1=True,
            M=Mz)
    make(p, "P6955", f"Шток амортизатора {g}", "suspension", "shock", parent=asm)

    p = Part(f"P6955_perch_{tag}", ["Plastic_Black"])
    p.lathe([(0.0085, 0.0022), (0.0085, 0.0068), (0.0098, 0.0080), (0.0112, 0.0080),
             (0.0112, 0.0022)], "Plastic_Black", segs=24, closed=True, M=Mz)
    make(p, "P6955", f"Нижняя тарелка пружины {g} амортизатора", "suspension", "shock",
         parent=asm)

    p = Part(f"P6955_body_{tag}", ["Plastic_Black"])
    p.lathe([(0.0250, 0.0017), (0.0250, 0.0060), (0.0265, 0.0066), (0.0285, 0.0066),
             (0.0290, 0.0058), (L - 0.0110, 0.0058), (L - 0.0110, 0.0062),
             (L - 0.0080, 0.0062), (L - 0.0080, 0.0017)], "Plastic_Black", segs=28,
            closed=True, M=Mz)
    make(p, "P6955", f"Корпус амортизатора {g}", "suspension", "shock", parent=asm)

    p = Part(f"P6955_cap_{tag}", ["Alu_Red"])
    p.ring_extrude(gear_pts(30, 0.0070, 0.0075, tip=0.5, flank=0.05), 0.0017, 0.0, 0.0060,
                   "Alu_Red", M=M @ Matrix.Translation((0, 0, L - 0.0110)))
    make(p, "P6955", f"Алюминиевый колпачок {g} амортизатора", "suspension", "shock",
         parent=asm, sharp_deg=50)

    p = Part(f"P6955_endtop_{tag}", ["Plastic_Black"])
    p.lathe([(L - 0.0050, 0.0050), (L - 0.0035, 0.0050)], "Plastic_Black", segs=20,
            cap0=True, cap1=True, M=Mz)
    p.lathe([(L - 0.0040, 0.0024), (L - 0.0026, 0.0024)], "Plastic_Black", segs=12,
            cap0=True, cap1=True, M=Mz)
    p.eyelet(M @ Matrix.Translation((0, 0, L)), 0.0034, 0.0012, 0.0016, "Plastic_Black")
    make(p, "P6955", f"Верхний наконечник амортизатора {g}", "suspension", "shock",
         parent=asm)

    p = Part(f"P6955_spring_{tag}", ["Chrome"])
    p.helix(0.0110, L - 0.0110, 0.0071, 0.00075, 8.5, "Chrome", M=M, per=20, segs=8)
    make(p, "P6955", f"Пружина {g} амортизатора", "suspension", "shock", parent=asm,
         sharp_deg=60)


# ---------------------------------------------------------------- рулевое


def build_steering():
    p = Part("SERVO", ["Plastic_Black", "Nylon_Gray", "Label_Black"])
    p.box((0.0150, 0.0120, 0.0230), (0.0350, 0.0520, 0.0545), "Plastic_Black")
    p.box((0.0150, 0.0060, 0.0440), (0.0350, 0.0580, 0.0465), "Plastic_Black")
    p.cyl((0.0250, 0.0440, 0.0545), (0.0250, 0.0440, 0.0565), 0.0050, "Plastic_Black",
          segs=20)
    p.cyl((0.0250, 0.0440, 0.0565), (0.0250, 0.0440, 0.0580), 0.0022, "Nylon_Gray", segs=12)
    p.box((0.0148, 0.0180, 0.0280), (0.0352, 0.0400, 0.0400), "Label_Black")
    make(p, "", "Сервопривод рулевой (5 проводов)", "steering", "servo", bevel=0.0007)

    p = Part("SERVO_HORN", ["Nylon_Gray"])
    p.cyl((0.0250, 0.0440, 0.0575), (0.0250, 0.0440, 0.0598), 0.0036, "Nylon_Gray", segs=16)
    p.bar((0.0250, 0.0440, 0.0588), (0.0340, 0.0440, 0.0588), 0.0040, 0.0020, "Nylon_Gray")
    make(p, "", "Качалка сервопривода", "steering", "servo", bevel=0.0004)

    p = Part("P2519", ["Plastic_Black"])
    p.box((0.0120, 0.0140, 0.0547), (0.0380, 0.0320, 0.0570), "Plastic_Black")
    for x in (0.0120, 0.0355):
        p.box((x, 0.0160, 0.0215), (x + 0.0025, 0.0300, 0.0570), "Plastic_Black")
    make(p, "P2519", "Крепление сервопривода", "steering", "servo", bevel=0.0005)

    p = Part("P2529", ["Steel", "Plastic_Black"])
    a, b = Vector((0.0335, 0.0440, 0.0600)), Vector((0.0310, 0.0660, 0.0485))
    p.cyl(a, b, 0.0009, "Steel", segs=8)
    for q in (a, b):
        p.cyl(q - Vector((0, 0, 0.002)), q + Vector((0, 0, 0.002)), 0.0022,
              "Plastic_Black", segs=12)
    make(p, "P2529", "Тяга сервопривода", "steering", "servo")

    asm = assembly("P6956", "Сервосейвер (узел рулевых качалок)", "steering", "P6956",
                   "servosaver")
    for side, sx in (("L", -1), ("R", 1)):
        p = Part(f"P2511_{side}", ["Plastic_Black"])
        c = Vector((sx * 0.020, 0.066, 0.0))
        p.cyl(c + Vector((0, 0, 0.0465)), c + Vector((0, 0, 0.0550)), 0.0040,
              "Plastic_Black", segs=16, hole=0.0015)
        p.bar(c + Vector((0, 0, 0.0525)), c + Vector((0, -0.0105, 0.0525)), 0.0050, 0.0030,
              "Plastic_Black")
        p.cyl(c + Vector((0, -0.0100, 0.0480)), c + Vector((0, -0.0100, 0.0540)), 0.0022,
              "Plastic_Black", segs=12)
        if sx > 0:
            p.bar(c + Vector((0, 0, 0.0485)), c + Vector((0.0110, 0, 0.0485)), 0.0045,
                  0.0030, "Plastic_Black")
        make(p, "P2511", f"Рулевая качалка {lr(sx, True)}", "steering", "servosaver",
             parent=asm, bevel=0.0004)

        p = Part(f"M5365_{side}", ["Steel"])
        p.cyl((sx * 0.020, 0.066, 0.0340), (sx * 0.020, 0.066, 0.0612), 0.0014, "Steel",
              segs=10)
        p.cyl((sx * 0.020, 0.066, 0.0605), (sx * 0.020, 0.066, 0.0615), 0.0026, "Steel",
              segs=12)
        make(p, "M5365", f"Ось рулевой качалки {lr(sx, True)}", "steering", "servosaver",
             parent=asm)

    p = Part("P6956_link", ["Plastic_Black"])
    pts = [(-0.020, 0.0560, 0.0555), (-0.010, 0.0545, 0.0565), (0.010, 0.0545, 0.0565),
           (0.020, 0.0560, 0.0555)]
    for a, b in zip(pts, pts[1:]):
        p.bar(a, b, 0.0040, 0.0025, "Plastic_Black")
    for x in (-0.020, 0.020):
        p.cyl((x, 0.056, 0.0540), (x, 0.056, 0.0572), 0.0030, "Plastic_Black", segs=14)
    make(p, "P6956", "Соединительная тяга сервосейвера", "steering", "servosaver",
         parent=asm, bevel=0.0004)

    p = Part("M5384", ["Steel"])
    p.helix(0.0553, 0.0603, 0.0030, 0.00045, 3.5, "Steel",
            M=Matrix.Translation((0.020, 0.066, 0)), per=16, segs=6)
    make(p, "M5384", "Пружина сервосейвера", "steering", "servosaver", parent=asm,
         sharp_deg=60)

    for side, sx in (("L", -1), ("R", 1)):
        p = Part(f"P2512_{side}", ["Steel", "Plastic_Black"])
        a = Vector((sx * 0.020, 0.0560, 0.0495))
        b = Vector((sx * 0.0630, WY - 0.0125, 0.0495))
        d = (b - a).normalized()
        p.cyl(a + d * 0.003, b - d * 0.003, 0.0010, "Steel", segs=8)
        for q in (a, b):
            p.cyl(q - Vector((0, 0, 0.0022)), q + Vector((0, 0, 0.0022)), 0.0027,
                  "Plastic_Black", segs=14)
        make(p, "P2512", f"Рулевая тяга {lr(sx, True)}", "steering", "servosaver")


def build_front_hub(tag, sx):
    yc = WY
    xo = sx * ARM_XO
    # C-хаб: задняя стенка с окном под ось, верхнее и нижнее ухо
    p = Part(f"P2506_{tag}", ["Plastic_Black"])
    for z0, z1 in ((0.0185, 0.0300), (0.0450, 0.0545)):
        p.box((xo - sx * 0.0005, yc - 0.0060, z0), (xo + sx * 0.0030, yc + 0.0060, z1),
              "Plastic_Black")
    for z0 in (0.0245, 0.0505):
        p.box((xo, yc - 0.0055, z0), (sx * 0.0715, yc + 0.0055, z0 + 0.0030),
              "Plastic_Black")
        p.cyl((sx * 0.0665, yc, z0 - 0.0003), (sx * 0.0665, yc, z0 + 0.0033), 0.0034,
              "Plastic_Black", segs=14)
    p.cyl((xo, yc - 0.0050, ARM_Z), (xo, yc + 0.0050, ARM_Z), 0.0030, "Plastic_Black",
          segs=14)
    for s in (-1, 1):
        p.box((xo - sx * 0.0005, yc + s * 0.0050 - 0.0015, 0.0300),
              (xo + sx * 0.0030, yc + s * 0.0050 + 0.0015, 0.0450), "Plastic_Black")
    p.cyl((xo, yc - 0.0025, 0.0545), (xo, yc + 0.0025, 0.0545), 0.0028, "Plastic_Black",
          segs=12)
    make(p, "P2506", f"C-хаб {lr(sx)}", "steering", "chub", bevel=0.0004)

    p = Part(f"P2507_{tag}", ["Plastic_Black", "Steel"])
    p.box((sx * 0.0615, yc - 0.0060, 0.0280), (sx * 0.0712, yc + 0.0060, 0.0502),
          "Plastic_Black")
    p.cyl((sx * 0.0620, yc, AZ), (sx * 0.0735, yc, AZ), 0.0068, "Plastic_Black", segs=24,
          hole=0.0040)
    p.bar((sx * 0.0660, yc - 0.0040, 0.0495), (sx * 0.0630, yc - 0.0130, 0.0495), 0.0040,
          0.0030, "Plastic_Black")
    p.cyl((sx * 0.0630, yc - 0.0125, 0.0480), (sx * 0.0630, yc - 0.0125, 0.0520), 0.0016,
          "Steel", segs=10)
    make(p, "P2507", f"Поворотный кулак {lr(sx)}", "steering", "knuckle", bevel=0.0004)

    for pos, z0, z1, zin, ru in (("T", 0.0535, 0.0555, 0.0450, "верхний"),
                                 ("B", 0.0245, 0.0225, 0.0330, "нижний")):
        p = Part(f"F5280_{tag}_{pos}", ["Steel"])
        p.cyl((sx * 0.0665, yc, z0), (sx * 0.0665, yc, z1), 0.0026, "Steel", segs=14)
        p.cyl((sx * 0.0665, yc, z0), (sx * 0.0665, yc, zin), 0.0012, "Steel", segs=10)
        make(p, "F5280", f"Шкворень {ru} {'левого' if sx < 0 else 'правого'} кулака",
             "steering", "knuckle")


def build_rear_hub(tag, sx):
    yc = -WY
    xo = sx * ARM_XO
    p = Part(f"P2513_{tag}", ["Plastic_Black"])
    p.box((xo, yc - 0.0060, 0.0250), (sx * 0.0715, yc + 0.0060, 0.0510), "Plastic_Black")
    p.cyl((sx * 0.0620, yc, AZ), (sx * 0.0735, yc, AZ), 0.0072, "Plastic_Black", segs=24,
          hole=0.0040)
    p.cyl((xo, yc - 0.0050, ARM_Z), (xo, yc + 0.0050, ARM_Z), 0.0030, "Plastic_Black",
          segs=14)
    p.bar((xo, yc, ARM_Z), (xo + sx * 0.002, yc, 0.0260), 0.0080, 0.0050, "Plastic_Black",
          up=(1, 0, 0))
    p.bar((sx * 0.0600, yc, 0.0510), (xo, yc, 0.0545), 0.0060, 0.0040, "Plastic_Black",
          up=(0, 1, 0))
    p.cyl((xo, yc - 0.0025, 0.0545), (xo, yc + 0.0025, 0.0545), 0.0028, "Plastic_Black",
          segs=12)
    make(p, "P2513", f"Задняя ступица {lr(sx, True)}", "hubs", "hub", bevel=0.0005)


def build_axle_parts(tag, sx, sy):
    yc = sy * WY
    ru = SIDE_RU[tag]
    p = Part(f"M5368_{tag}", ["Steel"])
    x_cup = sx * 0.0570
    p.cyl((x_cup, yc, AZ), (x_cup + sx * 0.0055, yc, AZ), 0.0042, "Steel", segs=20,
          hole=0.0028)
    p.cyl((x_cup + sx * 0.0045, yc, AZ), (x_cup + sx * 0.0060, yc, AZ), 0.0030, "Steel",
          segs=20)
    p.cyl((x_cup + sx * 0.0055, yc, AZ), (sx * 0.0940, yc, AZ), 0.0016, "Steel", segs=14)
    p.cyl((sx * 0.0740, yc, AZ - 0.0028), (sx * 0.0740, yc, AZ + 0.0028), 0.0005, "Steel",
          segs=6)
    make(p, "M5368", f"Ось колеса {ru}", "hubs", "shaft", sharp_deg=50)

    for pid, x, r_out, w, pos in (("B5511", 0.0640, 0.0050, 0.0030, "внутренний"),
                                  ("B5509", 0.0712, 0.0040, 0.0025, "наружный")):
        p = Part(f"{pid}_{tag}", ["Steel", "Plastic_Black"])
        p.bearing(axis_m((sx * x, yc, AZ), "X"), r_out, 0.0016, w)
        make(p, pid, f"Подшипник ступицы {pos} {ru}", "hubs", "bearing")

    ax = "X" if sx > 0 else "-X"
    p = Part(f"P2021_{tag}", ["Plastic_Black"])
    p.ring_extrude(circle_pts(6, 0.0048, math.pi / 6), 0.0016, 0.0, 0.0050, "Plastic_Black",
                   M=axis_m((sx * 0.0742, yc, AZ), ax) @ ROT_Z2X)
    make(p, "P2021", f"Колёсный хекс {ru}", "hubs", "hex", sharp_deg=40, bevel=0.0003)

    p = Part(f"F5226_{tag}", ["Steel"])
    Mn = axis_m((sx * 0.0882, yc, AZ), ax) @ ROT_Z2X
    p.ring_extrude(circle_pts(6, 0.0040, math.pi / 6), 0.0016, 0.0008, 0.0036, "Steel", M=Mn)
    p.ring_extrude(circle_pts(24, 0.0046), 0.0016, 0.0, 0.0008, "Steel", M=Mn)
    make(p, "F5226", f"Колёсная гайка M4 {ru}", "hubs", "hex", sharp_deg=40)


# ---------------------------------------------------------------- колёса


def build_wheel(tag, sx, sy):
    asm = assembly(f"P6973_{tag}", f"Колесо в сборе {SIDE_RU[tag]}", "wheels", "P6973", "")
    place = Matrix.Translation((sx * WX, sy * WY, WZ))
    if sx < 0:
        place = place @ Matrix.Scale(-1, 4, (1, 0, 0))
    hw = WHW
    R = lambda ang: Matrix.Rotation(ang, 4, "X")

    # шина D5425: каркас + рельефные грунтозацепы
    p = Part(f"D5425_{tag}", ["Rubber"])
    p.lathe([(-hw, 0.0255), (-hw, 0.0290), (-hw + 0.0015, 0.0312), (-hw + 0.0045, 0.0328),
             (hw - 0.0045, 0.0328), (hw - 0.0015, 0.0312), (hw, 0.0290), (hw, 0.0255)],
            "Rubber", segs=56, closed=True)
    pitches = 18
    h = math.pi / pitches
    for i in range(pitches):
        a = 2 * math.pi * i / pitches
        for s, da in ((-1, 0.0), (1, h)):        # центральные блоки «ёлочкой»
            M = R(a + da) @ Matrix.Translation((s * 0.0055, 0, 0.0348)) \
                @ Matrix.Rotation(math.radians(-14 * s), 4, "Z")
            p.cbox((0, 0, 0), (0.0095, 0.0070, 0.0048), "Rubber", M=M)
            M = R(a + da) @ Matrix.Translation((-s * 0.0010, 0, 0.0340))
            p.cbox((0, 0, 0), (0.0040, 0.0030, 0.0032), "Rubber", M=M)
        for s, da in ((-1, h), (1, 0.0)):        # плечевые блоки, заходящие на боковину
            M = R(a + da) @ Matrix.Translation((s * 0.0150, 0, 0.0342)) \
                @ Matrix.Rotation(math.radians(10 * s), 4, "Z")
            p.cbox((0, 0, 0), (0.0085, 0.0075, 0.0058), "Rubber", M=M)
            M = R(a + da) @ Matrix.Translation((s * 0.0198, 0, 0.0300))
            p.cbox((0, 0, 0), (0.0030, 0.0060, 0.0060), "Rubber", M=M)
    p.transform(place)
    make(p, "D5425", f"Шина {SIDE_RU_F[tag]}", "wheels", "", parent=asm,
         bevel=0.00045, bevel_deg=60, segs=1, sharp_deg=40)

    # диск P2555: обод с бедлок-кольцом, 5 двойных спиц, ступица
    p = Part(f"P2555_{tag}", ["Rim_Black"])
    p.lathe([(-0.0200, 0.0222), (-0.0200, 0.0262), (-0.0180, 0.0262), (-0.0180, 0.0252),
             (0.0170, 0.0252), (0.0170, 0.0266), (0.0205, 0.0266), (0.0205, 0.0236),
             (0.0185, 0.0226), (-0.0180, 0.0222)], "Rim_Black", segs=56, closed=True)
    for i in range(20):
        a = 2 * math.pi * i / 20
        q = (0.0251 * math.cos(a), 0.0251 * math.sin(a))
        p.cyl((0.0205, *q), (0.0212, *q), 0.0006, "Rim_Black", segs=6)
    p.lathe([(-0.0050, 0.0030), (-0.0050, 0.0078), (0.0040, 0.0078), (0.0040, 0.0030)],
            "Rim_Black", segs=24, closed=True)
    for i in range(5):
        a = 2 * math.pi * i / 5
        for s in (-1, 1):
            ah = a + s * math.radians(7)       # пара сходится у ступицы,
            at = a + s * math.radians(19)      # расходится к ободу (V-спица)
            q0 = Vector((0.0015, 0.0068 * math.cos(ah), 0.0068 * math.sin(ah)))
            q1 = Vector((0.0165, 0.0232 * math.cos(at), 0.0232 * math.sin(at)))
            p.bar(q0, q1, 0.0035, 0.0048, "Rim_Black", up=(0, -math.sin(at), math.cos(at)))
        # перемычка между спицами пары у обода
        am = Vector((0.0160, 0.0205 * math.cos(a), 0.0205 * math.sin(a)))
        p.bar(am - Vector((0, -math.sin(a), math.cos(a))) * 0.004,
              am + Vector((0, -math.sin(a), math.cos(a))) * 0.004, 0.0030, 0.0030,
              "Rim_Black", up=(1, 0, 0))
    p.transform(place)
    make(p, "P2555", f"Диск колеса {SIDE_RU[tag]}", "wheels", "", parent=asm,
         bevel=0.0004, sharp_deg=40)


# ---------------------------------------------------------------- электроника


def build_electric():
    p = Part("ESC", ["Plastic_Black", "Alu_Red", "Plug_Red", "Label_Orange"])
    p.box((-0.0410, 0.0120, 0.0215), (-0.0110, 0.0460, 0.0345), "Plastic_Black")
    for i in range(6):
        x = -0.0245 + i * 0.0024
        p.box((x, 0.0150, 0.0345), (x + 0.0011, 0.0430, 0.0410), "Alu_Red")
    p.box((-0.0255, 0.0150, 0.0345), (-0.0110, 0.0430, 0.0352), "Alu_Red")
    p.cyl((-0.0350, 0.0400, 0.0345), (-0.0350, 0.0400, 0.0365), 0.0022, "Plug_Red", segs=12)
    p.box((-0.0390, 0.0180, 0.0346), (-0.0290, 0.0300, 0.0349), "Label_Orange")
    p.tube(catmull([(-0.0390, 0.0460, 0.0300), (-0.0420, 0.0500, 0.0450),
                    (-0.0400, 0.0480, 0.0800)], 5), 0.0005, "Plastic_Black", segs=6)
    make(p, "", "Регулятор хода 3 в 1 (ESC + приёмник) с радиатором", "electric", "esc",
         bevel=0.0007)

    p = Part("BATTERY", ["Battery_Blue", "Label_Black", "Label_Orange"])
    p.box((-0.0475, -0.0640, 0.0215), (-0.0145, 0.0060, 0.0415), "Battery_Blue")
    p.box((-0.0478, -0.0420, 0.0213), (-0.0142, -0.0150, 0.0417), "Label_Black")
    p.box((-0.0400, -0.0400, 0.0417), (-0.0220, -0.0170, 0.0419), "Label_Orange")
    make(p, "", "Аккумулятор Li-ion 7,4 В (2S)", "electric", "liion", bevel=0.0025,
         segs=3)

    p = Part("TPLUG", ["Plug_Red", "Brass"])
    p.box((-0.0200, -0.0020, 0.0430), (-0.0120, 0.0130, 0.0500), "Plug_Red")
    p.box((-0.0185, 0.0050, 0.0500), (-0.0135, 0.0060, 0.0505), "Brass")
    make(p, "", "Разъём T-plug (Deans)", "electric", "tplug", bevel=0.0006)

    p = Part("BALANCE", ["Plug_White"])
    p.box((-0.0460, 0.0080, 0.0420), (-0.0380, 0.0110, 0.0460), "Plug_White")
    make(p, "", "Балансировочный разъём аккумулятора", "electric", "balance", bevel=0.0003)

    p = Part("WIRES_BATT", ["Wire_Red", "Wire_Black", "Wire_White"])
    for dx, mat in ((-0.0015, "Wire_Red"), (0.0015, "Wire_Black")):
        p.tube(catmull([(-0.0250 + dx, 0.0060, 0.0350), (-0.0230 + dx, 0.0100, 0.0420),
                        (-0.0175 + dx * 0.6, 0.0040, 0.0465),
                        (-0.0160 + dx * 0.6, -0.0020, 0.0465)], 6), 0.0010, mat, segs=8)
    for i, mat in enumerate(("Wire_Red", "Wire_Black", "Wire_White")):
        dx = -0.0010 + i * 0.0010
        p.tube(catmull([(-0.0430 + dx, 0.0060, 0.0360), (-0.0430 + dx, 0.0080, 0.0420),
                        (-0.0420 + dx, 0.0095, 0.0440)], 5), 0.00035, mat, segs=6)
    make(p, "", "Провода аккумулятора", "electric", "liion")

    p = Part("WIRES_ESC", ["Wire_Red", "Wire_Black"])
    for dx, mat in ((-0.0015, "Wire_Red"), (0.0015, "Wire_Black")):
        p.tube(catmull([(-0.0160 + dx, 0.0130, 0.0300), (-0.0130 + dx, 0.0160, 0.0440),
                        (-0.0160 + dx * 0.6, 0.0130, 0.0465)], 6), 0.0010, mat, segs=8)
    make(p, "", "Силовые провода регулятора к аккумулятору", "electric", "esc")

    p = Part("WIRES_MOTOR", ["Wire_Red", "Wire_Black"])
    for dx, mat, xm in ((-0.0015, "Wire_Red", -0.0045), (0.0015, "Wire_Black", 0.0045)):
        p.tube(catmull([(-0.0120, 0.0200 + dx, 0.0300), (-0.0050, 0.0150 + dx, 0.0620),
                        (0.0050, 0.0000 + dx, 0.0660), (MOTOR_X + xm, -0.0120, 0.0640),
                        (MOTOR_X + xm, -0.0165, MOTOR_Z + 0.0165)], 6), 0.0010, mat, segs=8)
    make(p, "", "Провода мотора", "electric", "brushed")

    p = Part("WIRES_SERVO", ["Wire_Black", "Wire_Red", "Wire_White", "Wire_Yellow"])
    for i, mat in enumerate(("Wire_Black", "Wire_Red", "Wire_White", "Wire_Yellow",
                             "Wire_Black")):
        d = (i - 2) * 0.0007
        p.tube(catmull([(0.0250 + d, 0.0120, 0.0300), (0.0150 + d, 0.0080, 0.0480),
                        (-0.0050, 0.0150 + d, 0.0500), (-0.0150, 0.0350 + d, 0.0400),
                        (-0.0175, 0.0400 + d, 0.0345)], 6), 0.00035, mat, segs=6)
    make(p, "", "Кабель сервопривода (5 проводов)", "electric", "servo")

    p = Part("WIRES_LED", ["Wire_Red", "Wire_Black"])
    for d, mat in ((-0.0006, "Wire_Red"), (0.0006, "Wire_Black")):
        p.tube(catmull([(-0.0080 + d, 0.1270, 0.0330), (-0.0300 + d, 0.1150, 0.0300),
                        (-0.0340 + d, 0.0800, 0.0300), (-0.0340 + d, 0.0500, 0.0300),
                        (-0.0300 + d, 0.0465, 0.0300)], 6), 0.00045, mat, segs=6)
    make(p, "", "Провода светодиодной планки", "electric", "led")

    p = Part("LED_BAR", ["LED_Bar", "Plastic_Black"])
    p.box((-0.0340, 0.1360, 0.0300), (0.0340, 0.1400, 0.0375), "LED_Bar")
    p.box((-0.0100, 0.1270, 0.0310), (0.0100, 0.1360, 0.0365), "Plastic_Black")
    make(p, "", "Светодиодная планка", "electric", "led", bevel=0.0005)
    for side, sx in (("L", -1), ("R", 1)):
        p = Part(f"LED_{side}", ["LED_White"])
        p.cyl((sx * 0.0220, 0.1395, 0.0337), (sx * 0.0220, 0.1405, 0.0337), 0.0030,
              "LED_White", segs=16)
        make(p, "", f"Светодиодная фара {lr(sx, True)}", "electric", "led")


# ---------------------------------------------------------------- кузов

# Сечения кузова спереди назад:
# y, zb (низ борта), wb, zs (плечо), ws, zo (край крыши/капота), wo, zi, wi
BODY_KEYS = [
    (0.120, 0.052, 0.050, 0.072, 0.054, 0.084, 0.046, 0.086, 0.020),
    (0.110, 0.048, 0.060, 0.088, 0.066, 0.094, 0.056, 0.096, 0.022),
    (0.0925, 0.048, 0.064, 0.098, 0.075, 0.101, 0.062, 0.102, 0.024),
    (0.050, 0.046, 0.060, 0.097, 0.062, 0.101, 0.054, 0.103, 0.024),
    (0.015, 0.046, 0.060, 0.098, 0.060, 0.119, 0.040, 0.121, 0.018),
    (-0.028, 0.046, 0.060, 0.098, 0.060, 0.119, 0.040, 0.121, 0.018),
    (-0.042, 0.046, 0.060, 0.099, 0.060, 0.104, 0.056, 0.096, 0.042),
    (-0.0925, 0.048, 0.064, 0.101, 0.075, 0.105, 0.066, 0.096, 0.042),
    (-0.104, 0.050, 0.064, 0.101, 0.070, 0.105, 0.064, 0.096, 0.042),
    (-0.112, 0.056, 0.058, 0.097, 0.062, 0.101, 0.056, 0.096, 0.042),
]
ARCH_R = WR + 0.0030
Y_WINDSHIELD = (0.015, 0.050)
Y_CAB = (-0.028, 0.015)
Y_REARWIN = (-0.042, -0.028)


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
    for yw in (WY, -WY):
        dy = y - yw
        if abs(dy) < ARCH_R:
            zb = max(zb, WZ + math.sqrt(ARCH_R ** 2 - dy ** 2))
    zb = min(zb, zs - 0.004)
    return [(-wb, zb), (-ws, zs), (-wo, zo), (-wi, zi),
            (wi, zi), (wo, zo), (ws, zs), (wb, zb)]


def camo(ym, e):
    """Камуфляж: пятна голубого и чёрного поверх основного цвета."""
    v = (math.sin(ym * 140 + e * 2.1) + 0.8 * math.sin(ym * 61 - e * 1.3 + 1.0)
         + 0.5 * math.sin(ym * 233 + e * 0.7))
    if v > 1.05:
        return "Body_Accent"
    if v < -1.25:
        return "Body_Black"
    return "Body_Main"


def body_face_material(ym, e):
    inside = lambda r: r[0] < ym < r[1]
    near_wheel = min(abs(ym - WY), abs(ym + WY)) < ARCH_R + 0.002
    side = min(e, 6 - e)
    if ym > 0.114 and side < 2:
        return "Body_Black"                      # морда / решётка
    if side == 0:
        if near_wheel:
            return "Body_Black"                  # расширители арок
        return camo(ym, e)
    if side == 1 and -0.026 < ym < 0.032:
        return "Body_Glass"                      # боковые окна
    if inside(Y_WINDSHIELD) or inside(Y_REARWIN):
        return "Body_Glass"
    if side == 3 and ym < Y_REARWIN[0]:
        return "Body_Black"                      # кузов-«корыто»
    if inside(Y_CAB):
        return "Body_Main" if side == 3 else "Body_Accent"    # крыша
    return camo(ym, e)


def body_side_x(y, z):
    """Наружная X нижней боковины кузова (правый борт) на высоте z."""
    st = body_station(y)
    (wb, zb), (ws, zs) = st[7], st[6]
    t = min(max((z - zb) / (zs - zb), 0.0), 1.0)
    return wb + (ws - wb) * t


def build_body():
    p = Part("BODY", ["Body_Main", "Body_Accent", "Body_Black", "Body_Glass", "Body_Light"])
    y0, y1 = BODY_KEYS[0][0], BODY_KEYS[-1][0]
    ys = {round(k[0], 5) for k in BODY_KEYS}
    n = 44
    ys |= {round(y0 + (y1 - y0) * i / n, 5) for i in range(n + 1)}
    for yw in (WY, -WY):
        for i in range(-8, 9):
            ys.add(round(yw + ARCH_R * 0.999 * i / 8, 5))
    ys = sorted(ys, reverse=True)
    clean = [ys[0]]
    for y in ys[1:]:
        if clean[-1] - y > 0.0018:
            clean.append(y)
    ys = clean
    rows = [[p._v((x, y, z)) for x, z in body_station(y)] for y in ys]
    for s in range(len(rows) - 1):
        ym = (ys[s] + ys[s + 1]) / 2
        for e in range(7):
            a, b = rows[s], rows[s + 1]
            p._face([a[e], b[e], b[e + 1], a[e + 1]], body_face_material(ym, e))
    p._face(rows[0][::-1], "Body_Black")
    p._face(rows[-1], "Body_Black")
    bmesh.ops.recalc_face_normals(p.bm, faces=p.bm.faces)
    roof = max(p.bm.faces, key=lambda f: f.calc_center_median().z)
    if roof.normal.z < 0:
        bmesh.ops.reverse_faces(p.bm, faces=p.bm.faces)
    # воздухозаборник капота, решётка, нарисованные фары
    p.box((-0.016, 0.062, 0.1005), (0.016, 0.088, 0.1045), "Body_Black")
    for i in range(4):
        y = 0.066 + i * 0.006
        p.box((-0.013, y, 0.1045), (0.013, y + 0.002, 0.1052), "Body_Main")
    for sx in (-1, 1):
        p.box((sx * 0.026, 0.1195, 0.0730), (sx * 0.044, 0.1215, 0.0790), "Body_Light")
    for i in range(3):
        z = 0.0745 + i * 0.003
        p.box((-0.018, 0.1200, z), (0.018, 0.1212, z + 0.0012), "Body_Main")
    # логотип «S» на боковинах
    s_pts = [(0.007, 0.012), (0.0, 0.0135), (-0.0062, 0.009), (-0.004, 0.003),
             (0.004, -0.003), (0.0062, -0.009), (0.0, -0.0135), (-0.007, -0.012)]
    for sx in (-1, 1):
        path = catmull([(-0.045 + sx * dy, 0.072 + dz) for dy, dz in s_pts], 4)
        for q0, q1 in zip(path, path[1:]):
            a3 = Vector((sx * (body_side_x(q0.x, q0.y) + 0.0006), q0.x, q0.y))
            b3 = Vector((sx * (body_side_x(q1.x, q1.y) + 0.0006), q1.x, q1.y))
            p.bar(a3, b3, 0.0034, 0.0008, "Body_Logo", up=(sx, 0, 0))
    return make(p, "", "Кузов S-EVOR", "body", "body", recalc=False, sharp_deg=30)


def build_wing():
    p = Part("WING", ["Wing_Black"])
    tilt = Matrix.Translation((0, -0.1300, 0.1170)) @ Matrix.Rotation(math.radians(-10), 4, "X")
    p.cbox((0, 0, 0), (0.180, 0.048, 0.0025), "Wing_Black", M=tilt)
    p.cbox((0, -0.0230, 0.0030), (0.180, 0.0020, 0.0060), "Wing_Black", M=tilt)
    p.cbox((0, 0.0, 0.0018), (0.060, 0.030, 0.0012), "Wing_Black", M=tilt)
    for sx in (-1, 1):
        x0 = sx * 0.0905
        poly = [(-0.1020, 0.1075), (-0.1520, 0.1025), (-0.1545, 0.1250), (-0.1120, 0.1215)]
        p.prism(poly, x0 - 0.0012, x0 + 0.0012, "Wing_Black", axis="X")
    make(p, "", "Антикрыло", "body", "wing", bevel=0.0005)

    for side, sx in (("L", -1), ("R", 1)):
        p = Part(f"WING_STRUT_{side}", ["Wing_Black"])
        poly = [(-0.1180, 0.0925), (-0.1360, 0.0925), (-0.1395, 0.1150), (-0.1225, 0.1150)]
        p.prism(poly, sx * 0.0210, sx * 0.0240, "Wing_Black", axis="X")
        make(p, "", f"Стойка антикрыла {lr(sx, True)}", "body", "wing", bevel=0.0004)


def build_clips():
    for end, (y, z) in (("F", (0.100, 0.104)), ("R", (-0.104, 0.103))):
        for side, sx in (("L", -1), ("R", 1)):
            p = Part(f"M5387_{end}{side}", ["Steel"])
            x = sx * 0.014
            zc = z - 0.0035
            pts = [(x - 0.0065, y, zc), (x + 0.0055, y, zc)]
            for k in range(1, 9):
                a = math.pi * k / 8
                pts.append((x + 0.0055 + 0.0022 * math.sin(a), y,
                            zc + 0.0022 - 0.0022 * math.cos(a)))
            pts += [(x + 0.0010, y, zc + 0.0044), (x - 0.0010, y, zc + 0.0060),
                    (x - 0.0035, y, zc + 0.0044), (x - 0.0065, y, zc + 0.0030)]
            p.tube(catmull(pts, 3), 0.00045, "Steel", segs=6)
            make(p, "M5387", f"Клипса кузова {END_RU_F[end]} {lr(sx, True)}", "body",
                 "clips", sharp_deg=60)


# ---------------------------------------------------------------- сборка


def build_car():
    build_tub()
    build_top_plate()
    for end in ("F", "R"):
        build_gearbox(end)
        build_shock_tower(end)
        build_body_post(end)
        build_diff(end)
    build_bumper_front()
    build_bumper_rear()
    build_wing_mount()
    build_drive()
    build_steering()
    for tag, (sx, sy) in CORNERS.items():
        build_arm(tag, sx, sy)
        build_shock(tag, sx, sy)
        if sy > 0:
            build_front_hub(tag, sx)
        else:
            build_rear_hub(tag, sx)
        build_axle_parts(tag, sx, sy)
        build_wheel(tag, sx, sy)
    build_electric()
    build_body()
    build_wing()
    build_clips()


def new_empty(name, loc, props):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "PLAIN_AXES"
    e.empty_display_size = 0.01
    e.location = loc
    for k, v in props.items():
        e[k] = v
    bpy.context.scene.collection.objects.link(e)
    assert e.name == name, f"duplicate id {name}"
    return e


def world_bbox(objs):
    lo = Vector((1e9,) * 3)
    hi = Vector((-1e9,) * 3)
    for o in objs:
        mw = o.matrix_world
        for v in o.data.vertices:
            w = mw @ v.co
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def build_hierarchy():
    bpy.context.view_layer.update()
    groups = {}
    for g, ru in GROUP_RU.items():
        groups[g] = new_empty(f"grp_{g}", (0, 0, 0),
                              {"kind": "group", "group": g, "name_ru": ru, "part": "",
                               "term": ""})
    asm_objs = {}
    for aid, info in ASSEMBLIES.items():
        kids = [d["obj"] for d in PARTS if d["parent"] == aid]
        lo, hi = world_bbox(kids)
        e = new_empty(aid, (lo + hi) / 2, {"kind": "assembly", **info})
        e.parent = groups[info["group"]]
        asm_objs[aid] = e
    for d in PARTS:
        o = d["obj"]
        par = asm_objs.get(d["parent"]) or groups[d["parent"][4:]]
        loc = o.location.copy()
        o.parent = par
        o.location = loc - par.location
    bpy.context.view_layer.update()


def write_parts_json():
    out = []
    for d in PARTS:
        o = d["obj"]
        lo, hi = world_bbox([o])
        c = (lo + hi) / 2
        out.append({"id": o.name, "part": o["part"], "name_ru": o["name_ru"],
                    "group": o["group"], "term": o["term"], "parent": o.parent.name,
                    "center": [round(c.x, 5), round(c.z, 5), round(-c.y, 5)]})
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


def export_glb():
    bpy.ops.export_scene.gltf(
        filepath=GLB_PATH, export_format="GLB", export_apply=True,
        export_cameras=False, export_lights=False, export_yup=True,
        export_extras=True, use_selection=False)


# ---------------------------------------------------------------- превью


def setup_render():
    scene = bpy.context.scene
    me = bpy.data.meshes.new("Ground")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=20.0)
    bm.to_mesh(me)
    bm.free()
    ground = bpy.data.objects.new("Ground", me)
    me.materials.append(MAT["Ground"])
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

    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    cam.data.lens = 50
    cam.data.clip_start = 0.01
    scene.collection.objects.link(cam)
    scene.camera = cam

    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = 1200, 800, 100
    r.image_settings.file_format = "PNG"
    r.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    engine = os.environ.get("SEVOR_ENGINE", "EEVEE").upper()
    if engine == "CYCLES":
        r.engine = "CYCLES"
        scene.cycles.samples = 96
        scene.cycles.use_denoising = True
    elif engine == "WORKBENCH":
        r.engine = "BLENDER_WORKBENCH"
    else:
        for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                r.engine = name
                break
            except TypeError:
                continue
        scene.eevee.taa_render_samples = 64
    return cam


def render_view(cam, path, target, az, el, dist):
    target = Vector(target)
    az, el = math.radians(az), math.radians(el)
    cam.location = target + dist * Vector((math.sin(az) * math.cos(el),
                                           math.cos(az) * math.cos(el), math.sin(el)))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("SEVOR preview:", path)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_materials()
    build_car()
    build_hierarchy()
    write_parts_json()
    export_glb()
    print("SEVOR parts: %d, assemblies: %d" % (len(PARTS), len(ASSEMBLIES)))
    print("SEVOR glb: %s (%.1f KB)" % (GLB_PATH, os.path.getsize(GLB_PATH) / 1024))
    if os.environ.get("SEVOR_NO_RENDER"):
        return
    cam = setup_render()
    render_view(cam, PREVIEW_PATH, (0.0, -0.008, 0.055), 38, 19, 0.70)
    for d in PARTS:
        if d["obj"]["group"] == "body":
            d["obj"].hide_render = True
    render_view(cam, PREVIEW_NOBODY_PATH, (0.0, -0.006, 0.040), 35, 50, 0.72)


main()
