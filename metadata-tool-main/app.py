"""
Metadata Reader + Metadata Remover — Flask back-end
====================================================
Supports JPG/JPEG/PNG/PDF.  Prefers ExifTool (subprocess) for deep
extraction/removal, falls back to Pillow (images) and PyPDF2 (PDFs).
"""

import atexit
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_file,
    abort,
)
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Optional imports — app works without them (degraded)
# ---------------------------------------------------------------------------
try:
    from PIL import Image

    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False

try:
    from PyPDF2 import PdfReader, PdfWriter
    from PyPDF2.generic import (
        ArrayObject,
        DictionaryObject,
        NameObject,
        NullObject,
    )

    PYPDF2_OK = True
except ImportError:
    PYPDF2_OK = False

try:
    import magic as _magic

    MAGIC_OK = True
except ImportError:
    MAGIC_OK = False

# ---------------------------------------------------------------------------
# Flask app config
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 MB
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}
ALLOWED_MIMES = {
    "image/jpeg",
    "image/png",
    "application/pdf",
}
UPLOAD_ROOT = Path(tempfile.gettempdir()) / "metadata_tool_uploads"
UPLOAD_ROOT.mkdir(exist_ok=True)
CLEANUP_MAX_AGE = 900  # 15 minutes

# ---------------------------------------------------------------------------
# ExifTool detection
# ---------------------------------------------------------------------------

def _find_exiftool() -> str | None:
    """Return the exiftool command string if available, else None."""
    for cmd in ("exiftool", "exiftool.exe"):
        if shutil.which(cmd):
            return cmd
    return None


EXIFTOOL_CMD = _find_exiftool()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _hex_ascii_preview(path: str, n: int = 256) -> dict:
    with open(path, "rb") as f:
        raw = f.read(n)
    hex_str = " ".join(f"{b:02X}" for b in raw)
    ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
    return {"hex": hex_str, "ascii": ascii_str, "bytes_read": len(raw)}


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def _detect_mime(path: str) -> str:
    if MAGIC_OK:
        try:
            return _magic.from_file(path, mime=True)
        except Exception:
            pass
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def _make_request_dir() -> Path:
    d = UPLOAD_ROOT / uuid.uuid4().hex
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_old():
    """Delete temp dirs older than CLEANUP_MAX_AGE seconds."""
    now = time.time()
    if not UPLOAD_ROOT.exists():
        return
    for entry in UPLOAD_ROOT.iterdir():
        if entry.is_dir():
            try:
                age = now - entry.stat().st_mtime
                if age > CLEANUP_MAX_AGE:
                    shutil.rmtree(entry, ignore_errors=True)
            except Exception:
                pass


def _start_cleanup_thread():
    def _loop():
        while True:
            try:
                _cleanup_old()
            except Exception:
                pass
            time.sleep(120)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()


_start_cleanup_thread()


# ---------------------------------------------------------------------------
# ExifTool wrappers
# ---------------------------------------------------------------------------

def _exiftool_json(path: str) -> dict | None:
    if not EXIFTOOL_CMD:
        return None
    try:
        r = subprocess.run(
            [EXIFTOOL_CMD, "-j", "-G", "-n", "-s", path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            return data[0] if data else None
    except Exception:
        pass
    return None


def _exiftool_strip(src: str, dst: str) -> bool:
    if not EXIFTOOL_CMD:
        return False
    try:
        r = subprocess.run(
            [EXIFTOOL_CMD, "-all=", "-o", dst, src],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return r.returncode == 0 and os.path.isfile(dst)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# GPS helpers
# ---------------------------------------------------------------------------

def _dms_to_decimal(dms_str: str, ref: str = "") -> float | None:
    """Convert a DMS string like '48 deg 51' 24.00"' to decimal."""
    try:
        nums = re.findall(r"[\d.]+", str(dms_str))
        if len(nums) < 3:
            return None
        d, m, s = float(nums[0]), float(nums[1]), float(nums[2])
        dec = d + m / 60 + s / 3600
        if ref.upper() in ("S", "W"):
            dec = -dec
        return round(dec, 7)
    except Exception:
        return None


def _parse_gps(tags: dict) -> dict:
    """Extract GPS from exiftool tag dict.  Keys are like 'GPS:GPSLatitude'."""
    lat = tags.get("GPS:GPSLatitude") or tags.get("EXIF:GPSLatitude")
    lon = tags.get("GPS:GPSLongitude") or tags.get("EXIF:GPSLongitude")
    lat_ref = tags.get("GPS:GPSLatitudeRef", tags.get("EXIF:GPSLatitudeRef", ""))
    lon_ref = tags.get("GPS:GPSLongitudeRef", tags.get("EXIF:GPSLongitudeRef", ""))
    result = {"gps_present": False}
    if lat is not None and lon is not None:
        # ExifTool with -n gives numeric values already
        try:
            lat_dec = float(lat)
            lon_dec = float(lon)
        except (ValueError, TypeError):
            lat_dec = _dms_to_decimal(str(lat), str(lat_ref))
            lon_dec = _dms_to_decimal(str(lon), str(lon_ref))
        if lat_dec is not None and lon_dec is not None:
            result = {
                "gps_present": True,
                "latitude": lat_dec,
                "longitude": lon_dec,
                "lat_ref": str(lat_ref),
                "lon_ref": str(lon_ref),
            }
    return result


# ---------------------------------------------------------------------------
# Image metadata extraction
# ---------------------------------------------------------------------------

def _extract_image_metadata(path: str, original_name: str) -> dict:
    size = os.path.getsize(path)
    mime = _detect_mime(path)
    checksum = _sha256(path)
    header = _hex_ascii_preview(path)
    meta: dict = {
        "filename": original_name,
        "type_mime": mime,
        "type_ext": Path(original_name).suffix.lower(),
        "file_size_bytes": size,
        "file_size_human": _human_size(size),
        "sha256": checksum,
        "raw_header": header,
    }

    width, height = None, None
    if PILLOW_OK:
        try:
            with Image.open(path) as img:
                width, height = img.size
                meta["image_width"] = width
                meta["image_height"] = height
                meta["image_size"] = f"{width} x {height}"
                meta["image_format"] = img.format
                if hasattr(img, "info"):
                    meta["compression_quality"] = img.info.get("quality", "N/A")
        except Exception:
            pass

    exif_tags = _exiftool_json(path)
    all_tags = {}
    grouped: dict[str, dict] = {}

    if exif_tags:
        all_tags = {k: str(v) for k, v in exif_tags.items()}
        # Group tags
        for k, v in exif_tags.items():
            group = k.split(":")[0] if ":" in k else "Other"
            grouped.setdefault(group, {})[k] = str(v)

        meta["camera_make"] = exif_tags.get("EXIF:Make", "N/A")
        meta["camera_model"] = exif_tags.get("EXIF:Model", "N/A")
        meta["date_taken"] = (
            exif_tags.get("EXIF:DateTimeOriginal")
            or exif_tags.get("EXIF:CreateDate")
            or "N/A"
        )
        meta["title"] = (
            exif_tags.get("XMP:Title")
            or exif_tags.get("IPTC:ObjectName")
            or exif_tags.get("EXIF:ImageDescription")
            or "N/A"
        )
        meta["description"] = (
            exif_tags.get("XMP:Description")
            or exif_tags.get("IPTC:Caption-Abstract")
            or exif_tags.get("EXIF:ImageDescription")
            or "N/A"
        )

        gps = _parse_gps(exif_tags)
        meta["gps"] = gps

        if width is None:
            w = exif_tags.get("EXIF:ImageWidth") or exif_tags.get("File:ImageWidth")
            h = exif_tags.get("EXIF:ImageHeight") or exif_tags.get("File:ImageHeight")
            if w and h:
                meta["image_width"] = int(w)
                meta["image_height"] = int(h)
                meta["image_size"] = f"{w} x {h}"

        meta["compression_quality"] = exif_tags.get(
            "EXIF:Compression",
            meta.get("compression_quality", "N/A"),
        )
    else:
        # Pillow-only fallback for EXIF
        meta.setdefault("camera_make", "N/A")
        meta.setdefault("camera_model", "N/A")
        meta.setdefault("date_taken", "N/A")
        meta.setdefault("title", "N/A")
        meta.setdefault("description", "N/A")
        meta["gps"] = {"gps_present": False}
        if PILLOW_OK:
            try:
                with Image.open(path) as img:
                    exif_data = img.getexif()
                    if exif_data:
                        from PIL.ExifTags import TAGS

                        for tag_id, val in exif_data.items():
                            tag_name = TAGS.get(tag_id, str(tag_id))
                            all_tags[f"EXIF:{tag_name}"] = str(val)
                            grouped.setdefault("EXIF", {})[tag_name] = str(val)
                        if 271 in exif_data:
                            meta["camera_make"] = str(exif_data[271])
                        if 272 in exif_data:
                            meta["camera_model"] = str(exif_data[272])
                        if 36867 in exif_data:
                            meta["date_taken"] = str(exif_data[36867])
                        elif 36868 in exif_data:
                            meta["date_taken"] = str(exif_data[36868])
                        # Check GPS IFD
                        gps_ifd = exif_data.get_ifd(0x8825)
                        if gps_ifd and 2 in gps_ifd and 4 in gps_ifd:
                            lat_t = gps_ifd[2]
                            lon_t = gps_ifd[4]
                            lat_ref = gps_ifd.get(1, "N")
                            lon_ref = gps_ifd.get(3, "E")
                            lat_dec = float(lat_t[0]) + float(lat_t[1]) / 60 + float(lat_t[2]) / 3600
                            lon_dec = float(lon_t[0]) + float(lon_t[1]) / 60 + float(lon_t[2]) / 3600
                            if lat_ref == "S":
                                lat_dec = -lat_dec
                            if lon_ref == "W":
                                lon_dec = -lon_dec
                            meta["gps"] = {
                                "gps_present": True,
                                "latitude": round(lat_dec, 7),
                                "longitude": round(lon_dec, 7),
                                "lat_ref": lat_ref,
                                "lon_ref": lon_ref,
                            }
            except Exception:
                pass

    meta["all_tags"] = all_tags
    meta["grouped_tags"] = grouped
    return meta


# ---------------------------------------------------------------------------
# PDF metadata extraction
# ---------------------------------------------------------------------------

def _extract_pdf_metadata(path: str, original_name: str) -> dict:
    size = os.path.getsize(path)
    mime = _detect_mime(path)
    checksum = _sha256(path)
    header = _hex_ascii_preview(path)

    meta: dict = {
        "filename": original_name,
        "type_mime": mime,
        "type_ext": ".pdf",
        "file_size_bytes": size,
        "file_size_human": _human_size(size),
        "sha256": checksum,
        "raw_header": header,
    }

    # Defaults
    meta["author"] = "N/A"
    meta["creator"] = "N/A"
    meta["producer"] = "N/A"
    meta["creation_date"] = "N/A"
    meta["modified_date"] = "N/A"
    meta["page_count"] = "N/A"
    meta["title"] = "N/A"
    meta["javascript_present"] = False
    meta["javascript_markers"] = []
    meta["embedded_images"] = "Unknown"

    all_tags: dict = {}
    doc_info: dict = {}

    # ExifTool pass
    exif_tags = _exiftool_json(path)
    if exif_tags:
        all_tags = {k: str(v) for k, v in exif_tags.items()}
        meta["author"] = exif_tags.get("PDF:Author", "N/A")
        meta["creator"] = exif_tags.get("PDF:Creator", "N/A")
        meta["producer"] = exif_tags.get("PDF:Producer", "N/A")
        meta["creation_date"] = str(exif_tags.get("PDF:CreateDate", "N/A"))
        meta["modified_date"] = str(exif_tags.get("PDF:ModifyDate", "N/A"))
        meta["page_count"] = exif_tags.get("PDF:PageCount", "N/A")
        meta["title"] = exif_tags.get("PDF:Title") or exif_tags.get("XMP:Title") or "N/A"

    # PyPDF2 pass
    if PYPDF2_OK:
        try:
            reader = PdfReader(path)
            if meta["page_count"] == "N/A":
                meta["page_count"] = len(reader.pages)
            info = reader.metadata
            if info:
                for key in info:
                    clean_key = str(key).lstrip("/")
                    doc_info[clean_key] = str(info[key])
                if meta["author"] == "N/A" and info.author:
                    meta["author"] = info.author
                if meta["creator"] == "N/A" and info.creator:
                    meta["creator"] = info.creator
                if meta["producer"] == "N/A" and info.producer:
                    meta["producer"] = info.producer
                if meta["title"] == "N/A" and info.title:
                    meta["title"] = info.title
                if info.creation_date:
                    meta["creation_date"] = str(info.creation_date)
                if info.modification_date:
                    meta["modified_date"] = str(info.modification_date)
        except Exception:
            pass

    # JavaScript detection — scan raw bytes
    js_markers_to_check = [b"/JavaScript", b"/JS", b"/AA", b"/OpenAction"]
    found_markers = []
    try:
        with open(path, "rb") as f:
            raw = f.read()
        for marker in js_markers_to_check:
            if marker in raw:
                found_markers.append(marker.decode())
        if found_markers:
            meta["javascript_present"] = True
            meta["javascript_markers"] = found_markers
    except Exception:
        pass

    meta["document_info"] = doc_info
    meta["all_tags"] = all_tags
    return meta


# ---------------------------------------------------------------------------
# Metadata removal
# ---------------------------------------------------------------------------

def _clean_image(src: str, dst: str) -> dict:
    """Remove all metadata from an image.  Returns status dict."""
    # Try ExifTool first
    if _exiftool_strip(src, dst):
        return {"success": True, "method": "exiftool", "warning": None}

    # Pillow fallback
    if PILLOW_OK:
        try:
            with Image.open(src) as img:
                clean = Image.new(img.mode, img.size)
                clean.putdata(list(img.getdata()))
                fmt = img.format or "JPEG"
                save_kwargs = {}
                if fmt.upper() in ("JPEG", "JPG"):
                    save_kwargs["quality"] = 95
                clean.save(dst, format=fmt, **save_kwargs)
            return {
                "success": True,
                "method": "pillow",
                "warning": "Cleaned via Pillow re-save; slight recompression may occur.",
            }
        except Exception as e:
            return {"success": False, "method": "pillow", "warning": str(e)}

    return {"success": False, "method": "none", "warning": "No cleaning tool available."}


def _clean_pdf(src: str, dst: str) -> dict:
    """Remove metadata and attempt JS neutralization from a PDF."""
    if not PYPDF2_OK:
        # ExifTool-only attempt
        if _exiftool_strip(src, dst):
            return {
                "success": True,
                "method": "exiftool",
                "warning": "Cleaned via ExifTool (metadata only). JavaScript removal not attempted.",
            }
        return {"success": False, "method": "none", "warning": "PyPDF2 not available and ExifTool failed."}

    warnings: list[str] = []
    try:
        reader = PdfReader(src)
        writer = PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        # Remove document-level metadata
        writer.add_metadata({
            "/Author": "",
            "/Creator": "",
            "/Producer": "",
            "/Title": "",
            "/Subject": "",
            "/Keywords": "",
        })

        # Attempt to strip JS from the catalog
        try:
            catalog = writer._root_object
            keys_to_remove = ["/OpenAction", "/AA", "/JavaScript", "/JS"]
            removed_keys = []
            for key in keys_to_remove:
                nk = NameObject(key)
                if nk in catalog:
                    catalog[nk] = NullObject()
                    removed_keys.append(key)
            if removed_keys:
                warnings.append(f"Neutralized catalog keys: {', '.join(removed_keys)}")
        except Exception as ex:
            warnings.append(f"JS removal partially failed: {ex}")

        # Strip /AA from individual pages
        try:
            for page in writer.pages:
                aa_key = NameObject("/AA")
                if aa_key in page:
                    page[aa_key] = NullObject()
        except Exception:
            pass

        with open(dst, "wb") as f:
            writer.write(f)

        return {
            "success": True,
            "method": "pypdf2",
            "warning": "; ".join(warnings) if warnings else None,
        }
    except Exception as e:
        return {"success": False, "method": "pypdf2", "warning": str(e)}


# ---------------------------------------------------------------------------
# Risk flags
# ---------------------------------------------------------------------------

def _compute_risk_flags(meta: dict, file_type: str) -> list[dict]:
    flags = []
    # GPS
    gps = meta.get("gps", {})
    if gps.get("gps_present"):
        flags.append({"label": "GPS Location Present", "level": "HIGH"})
    # JS in PDF
    if file_type == "pdf" and meta.get("javascript_present"):
        markers = ", ".join(meta.get("javascript_markers", []))
        flags.append({"label": f"JavaScript Detected ({markers})", "level": "HIGH"})
    # Author / Creator
    author = meta.get("author", "N/A")
    creator = meta.get("creator", "N/A")
    if author not in ("N/A", "", None) or creator not in ("N/A", "", None):
        flags.append({"label": "Author/Creator Information Present", "level": "MEDIUM"})
    # Camera info
    make = meta.get("camera_make", "N/A")
    model = meta.get("camera_model", "N/A")
    if make not in ("N/A", "", None) or model not in ("N/A", "", None):
        flags.append({"label": "Camera Make/Model Present", "level": "MEDIUM"})
    if not flags:
        flags.append({"label": "No significant risks detected", "level": "LOW"})
    return flags


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", exiftool_available=EXIFTOOL_CMD is not None)


@app.route("/api/status")
def status():
    return jsonify({
        "exiftool": EXIFTOOL_CMD is not None,
        "pillow": PILLOW_OK,
        "pypdf2": PYPDF2_OK,
        "magic": MAGIC_OK,
    })


@app.route("/api/analyze", methods=["POST"])
def analyze():
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    f = request.files["file"]
    if not f or f.filename == "":
        return jsonify({"error": "Empty filename."}), 400

    original_name = secure_filename(f.filename)
    if not _allowed_file(original_name):
        return jsonify({"error": f"File type not allowed. Accepted: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

    req_dir = _make_request_dir()
    save_path = str(req_dir / original_name)
    f.save(save_path)

    # Validate MIME
    detected_mime = _detect_mime(save_path)
    if detected_mime not in ALLOWED_MIMES:
        shutil.rmtree(req_dir, ignore_errors=True)
        return jsonify({"error": f"Detected MIME '{detected_mime}' not allowed."}), 400

    ext = original_name.rsplit(".", 1)[1].lower()
    file_type = "pdf" if ext == "pdf" else "image"

    try:
        if file_type == "image":
            meta = _extract_image_metadata(save_path, original_name)
        else:
            meta = _extract_pdf_metadata(save_path, original_name)
    except Exception as e:
        shutil.rmtree(req_dir, ignore_errors=True)
        return jsonify({"error": f"Metadata extraction failed: {e}"}), 500

    risk_flags = _compute_risk_flags(meta, file_type)
    request_id = req_dir.name

    return jsonify({
        "request_id": request_id,
        "file_type": file_type,
        "metadata": meta,
        "risk_flags": risk_flags,
        "exiftool_used": EXIFTOOL_CMD is not None,
    })


@app.route("/api/clean", methods=["POST"])
def clean():
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    f = request.files["file"]
    if not f or f.filename == "":
        return jsonify({"error": "Empty filename."}), 400

    original_name = secure_filename(f.filename)
    if not _allowed_file(original_name):
        return jsonify({"error": f"File type not allowed."}), 400

    req_dir = _make_request_dir()
    save_path = str(req_dir / original_name)
    f.save(save_path)

    detected_mime = _detect_mime(save_path)
    if detected_mime not in ALLOWED_MIMES:
        shutil.rmtree(req_dir, ignore_errors=True)
        return jsonify({"error": f"Detected MIME '{detected_mime}' not allowed."}), 400

    ext = original_name.rsplit(".", 1)[1].lower()
    file_type = "pdf" if ext == "pdf" else "image"

    stem = Path(original_name).stem
    suffix = Path(original_name).suffix
    clean_name = f"{stem}_cleaned{suffix}"
    clean_path = str(req_dir / clean_name)

    if file_type == "image":
        result = _clean_image(save_path, clean_path)
    else:
        result = _clean_pdf(save_path, clean_path)

    if not result["success"]:
        shutil.rmtree(req_dir, ignore_errors=True)
        return jsonify({"error": f"Cleaning failed: {result['warning']}"}), 500

    # Return the cleaned file
    response = send_file(
        clean_path,
        as_attachment=True,
        download_name=clean_name,
    )

    # Schedule cleanup after response
    @response.call_on_close
    def _remove_dir():
        try:
            shutil.rmtree(req_dir, ignore_errors=True)
        except Exception:
            pass

    if result["warning"]:
        response.headers["X-Clean-Warning"] = result["warning"]
    response.headers["X-Clean-Method"] = result["method"]
    return response


@app.route("/api/download-report", methods=["POST"])
def download_report():
    """Return the provided JSON metadata as a downloadable .json file."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data provided."}), 400
    req_dir = _make_request_dir()
    report_path = str(req_dir / "metadata_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    response = send_file(report_path, as_attachment=True, download_name="metadata_report.json")

    @response.call_on_close
    def _remove():
        shutil.rmtree(req_dir, ignore_errors=True)

    return response


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File exceeds 30 MB limit."}), 413


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error."}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)