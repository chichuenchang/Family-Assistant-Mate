"""浏览器驱动接口（缝）。浏览循环只认这里的类型；Playwright 实现在 browser_playwright.py，
将来换自写 CDP 驱动只换实现。设计：docs/superpowers/specs/2026-11-25-browser-agent-design.md。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

TEXT_CAP, MAX_ELEMENTS, LABEL_CAP = 6000, 150, 80


@dataclass(frozen=True)
class Element:
    ref: str            # "e1".."eN"，本次快照内跨 frame 唯一
    role: str           # button / link / textbox / checkbox / radio / combobox / tab / option / image …
    label: str
    input_type: str = ""
    autocomplete: str = ""
    name: str = ""
    href: str = ""


@dataclass(frozen=True)
class Snapshot:
    url: str
    title: str
    text: str
    elements: list[Element] = field(default_factory=list)


class DriverError(Exception):
    """可恢复：ref 失效、超时、点不到。消息回给模型，任务继续。"""


class DriverGone(DriverError):
    """浏览器关了或连接断了：任务结束。"""


class Driver(Protocol):
    def navigate(self, url: str) -> None: ...
    def snapshot(self) -> Snapshot: ...
    def click(self, ref: str) -> None: ...
    def type(self, ref: str, text: str, submit: bool = False) -> None: ...
    def focused(self) -> Element | None: ...      # 键盘焦点元素（ref 为空）；无焦点 = None
    def press(self, key: str) -> None: ...
    def scroll(self, pixels: int) -> None: ...
    def back(self) -> None: ...
    def tabs(self) -> list[tuple[int, str, str]]: ...
    def switch_tab(self, index: int) -> None: ...
    def close_tab(self, index: int) -> None: ...
    def screenshot(self, path: Path) -> None: ...
    def fetch_image(self, ref: str, dest_dir: Path) -> Path: ...
    def url(self) -> str: ...
    def close(self) -> None: ...
