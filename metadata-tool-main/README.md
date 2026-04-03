# 🟢 [METADATA TOOL ONLINE]

Terminal-Style Metadata Reader & Remover  
Image + PDF Metadata Analysis & Sanitization Tool

---

## 🚀 Overview

**Metadata Tool Online** is a web-based cybersecurity-focused application that allows users to:

- 🔍 Extract metadata from images and PDFs
- 🧠 Detect sensitive information (GPS, JavaScript, author info, etc.)
- 🛡 Analyze potential privacy/security risks
- 🧹 Remove metadata and download a cleaned file
- 🔐 Compute SHA256 file checksum
- 🧾 View raw file headers in HEX + ASCII format

Built with a neon-green terminal-inspired UI for a forensic-style experience.

---

## 🖼 Supported File Types

| Type | Supported |
|------|-----------|
| JPG  | ✅ |
| JPEG | ✅ |
| PNG  | ✅ |
| PDF  | ✅ |

Maximum file size: **30MB**

---

## 🔍 Extracted Metadata

### 📷 Image Metadata

- Camera Make & Model
- GPS Location (Decimal Coordinates)
- Date Taken
- Title / Description
- Compression Info
- Image Dimensions
- File Size
- MIME Type
- SHA256 Checksum
- Raw Header (First 256 Bytes in HEX + ASCII)
- Full EXIF / IPTC / XMP (if available)

---

### 📄 PDF Metadata

- Author
- Creator
- Producer
- Creation Date
- Modified Date
- Page Count
- Title
- JavaScript Presence Detection
- File Size
- MIME Type
- SHA256 Checksum
- Raw Header Preview

---

## 🛡 Risk Detection Engine

| Condition | Risk Level |
|-----------|------------|
| GPS Present | 🔴 HIGH |
| JavaScript in PDF | 🔴 HIGH |
| Author/Creator Info | 🟡 MEDIUM |
| Basic Metadata | 🟢 LOW |

---

## 🧹 Metadata Removal

### Images
- Removes EXIF, IPTC, XMP metadata
- Uses ExifTool (preferred)
- Pillow fallback if ExifTool is unavailable

### PDFs
- Removes DocumentInfo metadata
- Attempts to remove JavaScript triggers
- Preserves visible document content

---
