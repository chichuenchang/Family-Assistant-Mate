"""拟人输入节奏（纯函数，rng 注入便于测试）。设计：docs/superpowers/specs/2026-11-25-browser-agent-design.md「Humanize」。

鼠标：三次 Bezier 弧线、smoothstep 缓动、±1px 抖动、远距离偶尔越过目标再折回。
点击/按键/滚动/思考停顿只给时长，真正的输入由驱动执行。
"""

from __future__ import annotations

import math
import random

Point = tuple[float, float]

_PUNCT = set(" ,.;:!?，。；：！？、")


def target_point(box: tuple[float, float, float, float], rng: random.Random) -> Point:
    """box = (x, y, w, h)；落点在中间 60% 内均匀取，不总点正中。"""
    x, y, w, h = box
    return (x + w * rng.uniform(0.2, 0.8), y + h * rng.uniform(0.2, 0.8))


def _bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _arc(start: Point, end: Point, n: int, rng: random.Random) -> list[Point]:
    """start→end 的 n 个点（不含 start，末点 = end），侧向弯曲 + 缓动。"""
    dx, dy = end[0] - start[0], end[1] - start[1]
    d = math.hypot(dx, dy)
    nx, ny = -dy / d, dx / d                       # 弦的单位法向
    side = rng.choice((-1, 1))
    o1, o2 = (side * rng.uniform(0.05, 0.25) * d for _ in range(2))
    c1 = (start[0] + dx / 3 + nx * o1, start[1] + dy / 3 + ny * o1)
    c2 = (start[0] + 2 * dx / 3 + nx * o2, start[1] + 2 * dy / 3 + ny * o2)
    pts = []
    for i in range(1, n + 1):
        t = i / n
        t = 3 * t * t - 2 * t * t * t              # smoothstep：起止慢、中段快
        pts.append(_bezier(start, c1, c2, end, t))
    return pts


def mouse_path(start: Point, end: Point, rng: random.Random) -> list[tuple[float, float, float]]:
    """[(x, y, 之后停顿秒)]，末点恰为 end。"""
    d = math.dist(start, end)
    if d == 0:
        return [(end[0], end[1], 0.0)]
    n = max(8, min(80, int(d / 12) + 8))
    pts: list[Point]
    if d > 500 and rng.random() < 0.3:             # 越过目标再折回
        ux, uy = (end[0] - start[0]) / d, (end[1] - start[1]) / d
        over = rng.uniform(8, 20)
        past = (end[0] + ux * over, end[1] + uy * over)
        pts = _arc(start, past, n, rng) + _arc(past, end, rng.randint(3, 5), rng)
    else:
        pts = _arc(start, end, n, rng)
    pts = [(x + rng.uniform(-1, 1), y + rng.uniform(-1, 1)) for x, y in pts[:-1]] + [end]
    total = (0.25 + d / 1500) * rng.uniform(0.8, 1.3)
    step = total / len(pts)
    return [(x, y, step) for x, y in pts]


def click_delays(rng: random.Random) -> tuple[float, float]:
    """(按下前停顿, 按住时长)。"""
    return rng.uniform(0.08, 0.30), rng.uniform(0.04, 0.12)


def key_delays(text: str, rng: random.Random) -> list[float]:
    """每个字符之后的停顿；空格/标点后翻倍。"""
    return [rng.uniform(0.06, 0.18) * (2 if ch in _PUNCT else 1) for ch in text]


def scroll_steps(pixels: int, rng: random.Random) -> list[tuple[int, float]]:
    """[(滚轮增量, 之后停顿秒)]，增量和 = pixels，每段 ≤400。"""
    sign = 1 if pixels > 0 else -1
    left, out = abs(pixels), []
    while left > 0:
        chunk = min(left, rng.randint(100, 400))
        out.append((sign * chunk, rng.uniform(0.05, 0.25)))
        left -= chunk
    return out


def think_pause(rng: random.Random) -> float:
    """两个动作之间的停顿。"""
    return rng.uniform(0.5, 2.0)
