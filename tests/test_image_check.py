"""图片校验服务测试（规则 4.2.1：PNG/JPG、≥1920×1080、≤20MB）。"""
import pytest
from fastapi import HTTPException

from app.services import image_check


def test_valid_design_png_ok():
    from tests.conftest import make_png
    data = make_png(1920, 1080)
    fmt, w, h = image_check.check_image_bytes(data, "design")
    assert fmt == "PNG" and w == 1920 and h == 1080


def test_design_too_small_rejected():
    from tests.conftest import make_png
    with pytest.raises(HTTPException) as e:
        image_check.check_image_bytes(make_png(1280, 720), "design")
    assert "尺寸不达标" in e.value.detail


def test_fake_png_rejected():
    fake = b"\x89PNG\r\n\x1a\n" + b"this is not a real png body" * 10
    with pytest.raises(HTTPException):
        image_check.check_image_bytes(fake, "design")


def test_text_renamed_to_png_rejected():
    with pytest.raises(HTTPException):
        image_check.check_image_bytes(b"hello world, not an image at all", "design")


def test_jpeg_ok_for_design():
    from tests.conftest import make_jpeg
    fmt, w, h = image_check.check_image_bytes(make_jpeg(2400, 1200), "design")
    assert fmt == "JPEG" and (w, h) == (2400, 1200)


def test_process_image_allows_small():
    from tests.conftest import make_png
    fmt, w, h = image_check.check_image_bytes(make_png(800, 600), "process")
    assert fmt == "PNG"


def test_save_and_delete_roundtrip():
    from tests.conftest import make_png
    from app import config
    saved = image_check.save_image(make_png(1920, 1080), "design", 99901)
    p = config.UPLOAD_DIR / saved["path"]
    assert p.is_file()
    thumb = config.THUMB_DIR / p.name
    assert thumb.is_file(), "缩略图应已生成"
    image_check.delete_saved(saved["path"])
    assert not p.exists() and not thumb.exists()
