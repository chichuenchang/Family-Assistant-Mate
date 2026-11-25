# tests/test_browser_humanize.py — 拟人鼠标/键盘/滚动节奏（纯函数，固定随机种子）
import math
import random

import browser_humanize as h


def R():
    return random.Random(7)


def test_path_ends_exactly_on_target():
    p = h.mouse_path((10, 10), (900, 500), R())
    assert p[-1][:2] == (900, 500)


def test_path_is_curved_not_straight():
    p = h.mouse_path((0, 0), (800, 0), R())
    assert max(abs(y) for _, y, _ in p) > 3


def test_steps_scale_with_distance_and_are_capped():
    short = h.mouse_path((0, 0), (60, 0), R())
    long = h.mouse_path((0, 0), (1500, 0), R())
    assert 8 <= len(short) < len(long) <= 90


def test_no_teleport_segments():
    p = [(0.0, 0.0, 0)] + h.mouse_path((0, 0), (1000, 600), R())
    assert max(math.dist(a[:2], b[:2]) for a, b in zip(p, p[1:])) < 200


def test_duration_human_range():
    assert 0.2 <= sum(d for *_, d in h.mouse_path((0, 0), (1000, 600), R())) <= 2.0


def test_zero_distance_is_single_point():
    assert [q[:2] for q in h.mouse_path((5, 5), (5, 5), R())] == [(5, 5)]


def test_same_seed_same_path():
    assert h.mouse_path((0, 0), (300, 300), R()) == h.mouse_path((0, 0), (300, 300), R())


def test_target_point_inside_box_even_tiny():
    for box in [(100, 100, 80, 30), (5, 5, 1, 1)]:
        x, y = h.target_point(box, R())
        assert box[0] <= x <= box[0] + box[2] and box[1] <= y <= box[1] + box[3]


def test_target_point_not_always_centre():
    r = R()
    pts = {h.target_point((0, 0, 100, 40), r) for _ in range(5)}
    assert len(pts) > 1


def test_click_delays_ranges():
    dwell, hold = h.click_delays(R())
    assert 0.08 <= dwell <= 0.30 and 0.04 <= hold <= 0.12


def test_key_delays():
    d = h.key_delays("ab c", R())
    assert len(d) == 4 and all(0.06 <= x <= 0.36 for x in d)
    assert h.key_delays("", R()) == []


def test_scroll_steps_sum_sign_chunks():
    s = h.scroll_steps(-1200, R())
    assert sum(d for d, _ in s) == -1200 and all(d < 0 and abs(d) <= 400 for d, _ in s)
    assert h.scroll_steps(0, R()) == [] and h.scroll_steps(50, R())[0][0] == 50


def test_think_pause_range():
    assert 0.5 <= h.think_pause(R()) <= 2.0
