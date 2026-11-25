# tests/test_image_sniff.py — 魔数判图片格式（llm_providers.image_part、Browser_Agent fetch_image 共用）
import pytest

from image_sniff import image_format


@pytest.mark.parametrize("data,fmt", [
    (b"\xff\xd8\xff\xe0" + b"0" * 8, "jpeg"),
    (b"\x89PNG\r\n\x1a\n" + b"0" * 8, "png"),
    (b"GIF89a" + b"0" * 8, "gif"),
    (b"RIFF\0\0\0\0WEBPVP8 ", "webp"),
])
def test_known_formats(data, fmt):
    assert image_format(data) == fmt


@pytest.mark.parametrize("data", [b"<svg xmlns=", b"%PDF-1.7", b"RIFF\0\0\0\0WAVE", b""])
def test_unknown_is_none(data):
    assert image_format(data) is None
