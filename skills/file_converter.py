"""convert files between common formats (CSV <-> JSON, and images: PNG/JPG/WEBP/BMP/GIF)."""

from __future__ import annotations

import csv
import json
import os

from PIL import Image

SKILL_METADATA = {
    "name": "convert_file",
    "description": (
        "Convert a file to a different format. Supports CSV <-> JSON (list-of-records data files), "
        "and image conversion/resizing between PNG, JPG, WEBP, BMP, and GIF. "
        "The output format is taken from the target_path's file extension."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source_path": {
                "type": "string",
                "description": "Path to the file to convert.",
            },
            "target_path": {
                "type": "string",
                "description": "Where to save the converted file. Its extension decides the output format.",
            },
            "resize_width": {
                "type": "integer",
                "description": "Optional. Resize an image to this width in pixels (images only).",
            },
            "resize_height": {
                "type": "integer",
                "description": "Optional. Resize an image to this height in pixels (images only).",
            },
        },
        "required": ["source_path", "target_path"],
    },
}

_DATA_EXTS = {".csv", ".json"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _convert_data(source_path: str, target_path: str, src_ext: str, dst_ext: str) -> dict:
    if src_ext == ".csv" and dst_ext == ".json":
        with open(source_path, "r", newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)
        return {"success": True, "message": f"Converted {len(rows)} rows: {source_path} -> {target_path}"}

    if src_ext == ".json" and dst_ext == ".csv":
        with open(source_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            return {"success": False, "message": "JSON must be a non-empty list of objects to convert to CSV."}
        fieldnames = list(data[0].keys())
        with open(target_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        return {"success": True, "message": f"Converted {len(data)} rows: {source_path} -> {target_path}"}

    return {"success": False, "message": f"Unsupported data conversion: {src_ext} -> {dst_ext}"}


def _convert_image(source_path: str, target_path: str, resize_width: int | None, resize_height: int | None) -> dict:
    img = Image.open(source_path)

    if resize_width or resize_height:
        w, h = img.size
        new_w = resize_width or int(w * (resize_height / h))
        new_h = resize_height or int(h * (resize_width / w))
        img = img.resize((new_w, new_h))

    # JPEG can't save an alpha channel; flatten to RGB first.
    dst_ext = os.path.splitext(target_path)[1].lower()
    if dst_ext in (".jpg", ".jpeg") and img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img.save(target_path)
    return {"success": True, "message": f"Converted image: {source_path} -> {target_path}"}


def run(source_path: str, target_path: str, resize_width: int | None = None, resize_height: int | None = None) -> dict:
    try:
        if not os.path.isfile(source_path):
            return {"success": False, "message": f"Source file not found: {source_path}"}

        src_ext = os.path.splitext(source_path)[1].lower()
        dst_ext = os.path.splitext(target_path)[1].lower()

        if src_ext in _DATA_EXTS and dst_ext in _DATA_EXTS:
            return _convert_data(source_path, target_path, src_ext, dst_ext)

        if src_ext in _IMAGE_EXTS and dst_ext in _IMAGE_EXTS:
            return _convert_image(source_path, target_path, resize_width, resize_height)

        return {
            "success": False,
            "message": f"Unsupported conversion: {src_ext} -> {dst_ext}. Supported: CSV/JSON, or PNG/JPG/WEBP/BMP/GIF.",
        }
    except Exception as exc:
        return {"success": False, "message": f"Conversion failed: {exc}"}