"""图片校验与缩略图：魔数校验 → Pillow 复核 → 尺寸/大小限制 → 生成评审缩略图。

规则 4.2.1：设计图 1 张，PNG/JPG，不小于 1920×1080，≤20MB。
"""
import io
import uuid
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageOps

from .. import config

Image.MAX_IMAGE_PIXELS = 80_000_000  # 防解压炸弹（约 8000 万像素，远超 1920×1080）

MAGIC_PNG = b"\x89PNG\r\n\x1a\n"


def _sniff_format(data: bytes) -> str:
    """魔数判断真实格式：返回 'PNG' / 'JPEG' / 抛异常。"""
    if data[:8] == MAGIC_PNG:
        return "PNG"
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    raise HTTPException(400, "文件不是有效的 PNG/JPG 图片（拒绝伪造扩展名的文件）")


def check_image_bytes(data: bytes, kind: str) -> tuple[str, int, int]:
    """
    校验上传图片字节，返回 (格式, 宽, 高)。不合规抛 HTTPException。
    kind: 'design'（设计图，按规则 4.2.1 校验尺寸）或 'process'（过程记录，仅校验格式与大小）。
    """
    limit = config.DESIGN_MAX_BYTES if kind == "design" else config.PROCESS_MAX_BYTES
    if len(data) == 0:
        raise HTTPException(400, "文件为空")
    if len(data) > limit:
        raise HTTPException(400, f"文件超过大小限制（≤{limit // 1024 // 1024}MB）")
    fmt = _sniff_format(data)
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()  # 结构完整性校验
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if im.format not in ("PNG", "JPEG"):
                raise HTTPException(400, "仅支持 PNG/JPG 格式")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "图片文件损坏或无法解析")
    if kind == "design" and (w < config.DESIGN_MIN_W or h < config.DESIGN_MIN_H):
        raise HTTPException(
            400,
            f"设计图尺寸不达标：当前 {w}×{h}，规则要求不小于 {config.DESIGN_MIN_W}×{config.DESIGN_MIN_H}",
        )
    return fmt, w, h


def save_image(data: bytes, kind: str, student_id: int) -> dict:
    """校验并落盘，返回 {path, w, h}。path 为相对 uploads 的 POSIX 路径。"""
    fmt, w, h = check_image_bytes(data, kind)
    sub = "design" if kind == "design" else "process"
    folder = Path(config.UPLOAD_DIR) / sub / str(student_id)
    folder.mkdir(parents=True, exist_ok=True)
    ext = "png" if fmt == "PNG" else "jpg"
    name = f"{uuid.uuid4().hex}.{ext}"
    (folder / name).write_bytes(data)
    _make_thumbnail(data, name)
    return {"path": f"{sub}/{student_id}/{name}", "w": w, "h": h}


def _make_thumbnail(data: bytes, name: str, max_side: int = 480):
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((max_side, max_side))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.save(Path(config.THUMB_DIR) / name, "JPEG", quality=82, optimize=True)
    except Exception:
        pass  # 缩略图失败不阻塞上传，评审端会回退到原图


def delete_saved(path: str):
    """删除已保存文件及其缩略图（path 为相对 uploads 的路径）。"""
    if not path:
        return
    base = Path(config.UPLOAD_DIR)
    try:
        p = (base / path).resolve()
        if p.is_relative_to(base.resolve()) and p.is_file():
            p.unlink(missing_ok=True)
            thumb = Path(config.THUMB_DIR) / p.name
            thumb.unlink(missing_ok=True)
    except Exception:
        pass
