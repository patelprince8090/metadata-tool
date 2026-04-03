/* ================================================================
   METADATA TOOL — Frontend logic
   Drag & drop, upload, AJAX, render results, copy JSON, clean/download
   ================================================================ */

(function () {
    "use strict";

    // ── DOM refs ──
    const dropZone      = document.getElementById("drop-zone");
    const fileInput      = document.getElementById("file-input");
    const fileStatus     = document.getElementById("file-status");
    const fileInfoMini   = document.getElementById("file-info-mini");
    const miniName       = document.getElementById("mini-name");
    const miniType       = document.getElementById("mini-type");
    const miniSize       = document.getElementById("mini-size");

    const chkExtract = document.getElementById("chk-extract");
    const chkRisk    = document.getElementById("chk-risk");
    const chkHeader  = document.getElementById("chk-header");
    const chkClean   = document.getElementById("chk-clean");

    const btnAnalyze = document.getElementById("btn-analyze");
    const btnClean   = document.getElementById("btn-clean");

    const progressBar  = document.getElementById("progress-bar");
    const progressFill = document.getElementById("progress-fill");
    const progressText = document.getElementById("progress-text");
    const errorBox     = document.getElementById("error-box");

    const resultsSection   = document.getElementById("results-section");
    const cardFileInfo     = document.getElementById("card-file-info");
    const cardRiskFlags    = document.getElementById("card-risk-flags");
    const cardRiskWrap     = document.getElementById("card-risk-wrap");
    const cardMetadata     = document.getElementById("card-metadata");
    const cardRawHeader    = document.getElementById("card-raw-header");
    const cardHeaderWrap   = document.getElementById("card-header-wrap");
    const cardAllTags      = document.getElementById("card-all-tags");
    const toggleAllTags    = document.getElementById("toggle-all-tags");

    const btnCopyJson      = document.getElementById("btn-copy-json");
    const btnDownloadReport = document.getElementById("btn-download-report");
    const btnDownloadClean = document.getElementById("btn-download-clean");

    // ── State ──
    let selectedFile = null;
    let lastResult   = null;

    // ── Utilities ──
    function humanSize(bytes) {
        const units = ["B", "KB", "MB", "GB"];
        let i = 0;
        let size = bytes;
        while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
        return size.toFixed(2) + " " + units[i];
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function toast(msg) {
        const el = document.createElement("div");
        el.className = "toast";
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 2600);
    }

    function showError(msg) {
        errorBox.textContent = msg;
        errorBox.classList.remove("hidden");
    }

    function hideError() {
        errorBox.classList.add("hidden");
        errorBox.textContent = "";
    }

    function showProgress(text) {
        progressBar.classList.remove("hidden");
        progressFill.style.width = "0%";
        progressText.textContent = text || "Processing...";
        // Animate to ~90%
        let w = 0;
        const iv = setInterval(() => {
            w += Math.random() * 15;
            if (w > 90) { clearInterval(iv); w = 90; }
            progressFill.style.width = w + "%";
        }, 200);
        return iv;
    }

    function hideProgress(iv) {
        if (iv) clearInterval(iv);
        progressFill.style.width = "100%";
        setTimeout(() => {
            progressBar.classList.add("hidden");
            progressFill.style.width = "0%";
        }, 400);
    }

    // ── KV row builder ──
    function kvRow(key, val) {
        return `<div class="kv-row"><span class="kv-key">${escapeHtml(key)}</span><span class="kv-val">${escapeHtml(String(val ?? "N/A"))}</span></div>`;
    }

    // ── File selection ──
    function setFile(file) {
        if (!file) return;
        const allowed = ["image/jpeg", "image/png", "application/pdf"];
        if (!allowed.includes(file.type) && !/\.(jpe?g|png|pdf)$/i.test(file.name)) {
            showError("File type not allowed. Accepted: jpg, jpeg, png, pdf.");
            return;
        }
        if (file.size > 30 * 1024 * 1024) {
            showError("File exceeds 30 MB limit.");
            return;
        }
        hideError();
        selectedFile = file;
        fileStatus.textContent = file.name;
        miniName.textContent = file.name;
        miniType.textContent = file.type || "unknown";
        miniSize.textContent = humanSize(file.size);
        fileInfoMini.classList.remove("hidden");
        btnAnalyze.disabled = false;
        btnClean.disabled = false;
        resultsSection.classList.add("hidden");
        lastResult = null;
    }

    // Drop zone events
    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("drag-over");
    });
    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("drag-over");
    });
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag-over");
        if (e.dataTransfer.files.length > 0) {
            setFile(e.dataTransfer.files[0]);
        }
    });
    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) {
            setFile(fileInput.files[0]);
        }
    });

    // ── Analyze ──
    btnAnalyze.addEventListener("click", async () => {
        if (!selectedFile) return;
        hideError();
        const iv = showProgress("Analyzing metadata...");
        btnAnalyze.disabled = true;
        btnClean.disabled = true;

        try {
            const fd = new FormData();
            fd.append("file", selectedFile);
            const resp = await fetch("/api/analyze", { method: "POST", body: fd });
            const data = await resp.json();
            if (!resp.ok) {
                showError(data.error || "Analysis failed.");
                hideProgress(iv);
                btnAnalyze.disabled = false;
                btnClean.disabled = false;
                return;
            }
            lastResult = data;
            renderResults(data);
            hideProgress(iv);
        } catch (err) {
            showError("Network error: " + err.message);
            hideProgress(iv);
        }
        btnAnalyze.disabled = false;
        btnClean.disabled = false;
    });

    // ── Clean & Download ──
    btnClean.addEventListener("click", async () => {
        if (!selectedFile) return;
        hideError();
        const iv = showProgress("Cleaning metadata...");
        btnAnalyze.disabled = true;
        btnClean.disabled = true;

        try {
            const fd = new FormData();
            fd.append("file", selectedFile);
            const resp = await fetch("/api/clean", { method: "POST", body: fd });
            if (!resp.ok) {
                let errMsg = "Cleaning failed.";
                try {
                    const errData = await resp.json();
                    errMsg = errData.error || errMsg;
                } catch (_) {}
                showError(errMsg);
                hideProgress(iv);
                btnAnalyze.disabled = false;
                btnClean.disabled = false;
                return;
            }
            // Download the blob
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            const warning = resp.headers.get("X-Clean-Warning");
            const method = resp.headers.get("X-Clean-Method");

            // Derive filename
            const cd = resp.headers.get("Content-Disposition");
            let fname = "cleaned_file";
            if (cd) {
                const match = cd.match(/filename=(.+)/);
                if (match) fname = match[1].replace(/"/g, "");
            }
            a.href = url;
            a.download = fname;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);

            hideProgress(iv);
            let toastMsg = "Clean file downloaded (" + (method || "unknown") + ")";
            if (warning) toastMsg += " — " + warning;
            toast(toastMsg);
        } catch (err) {
            showError("Network error: " + err.message);
            hideProgress(iv);
        }
        btnAnalyze.disabled = false;
        btnClean.disabled = false;
    });

    // ── Render results ──
    function renderResults(data) {
        const meta = data.metadata;
        const flags = data.risk_flags;
        const fileType = data.file_type;

        // FILE INFO
        let infoHtml = "";
        infoHtml += kvRow("Filename", meta.filename);
        infoHtml += kvRow("Type (MIME)", meta.type_mime);
        infoHtml += kvRow("Type (ext)", meta.type_ext);
        infoHtml += kvRow("File size", meta.file_size_human + " (" + meta.file_size_bytes + " bytes)");
        infoHtml += kvRow("SHA-256", meta.sha256);
        if (meta.image_size) infoHtml += kvRow("Image size", meta.image_size);
        if (!data.exiftool_used) {
            infoHtml += '<div class="kv-row" style="color:#ff9500;">⚠ ExifTool not used — results may be partial.</div>';
        }
        cardFileInfo.innerHTML = infoHtml;

        // RISK FLAGS
        if (chkRisk.checked || flags.some(f => f.level === "HIGH")) {
            cardRiskWrap.classList.remove("hidden");
            let riskHtml = "";
            flags.forEach(f => {
                riskHtml += `<div class="risk-flag-row"><span class="risk-badge risk-${f.level}">${f.level}</span><span>${escapeHtml(f.label)}</span></div>`;
            });
            cardRiskFlags.innerHTML = riskHtml;
        } else {
            cardRiskWrap.classList.add("hidden");
        }

        // METADATA DETAILS
        let metaHtml = "";
        if (fileType === "image") {
            metaHtml += kvRow("Camera make", meta.camera_make);
            metaHtml += kvRow("Camera model", meta.camera_model);
            metaHtml += kvRow("Date taken", meta.date_taken);
            metaHtml += kvRow("Title", meta.title);
            metaHtml += kvRow("Description", meta.description);
            metaHtml += kvRow("Image format", meta.image_format || "N/A");
            metaHtml += kvRow("Compression/Quality", meta.compression_quality);
            // GPS
            const gps = meta.gps || {};
            metaHtml += kvRow("GPS present", gps.gps_present ? "Yes" : "No");
            if (gps.gps_present) {
                metaHtml += kvRow("Latitude", gps.latitude + " " + (gps.lat_ref || ""));
                metaHtml += kvRow("Longitude", gps.longitude + " " + (gps.lon_ref || ""));
            }
        } else {
            // PDF
            metaHtml += kvRow("Title", meta.title);
            metaHtml += kvRow("Author", meta.author);
            metaHtml += kvRow("Creator", meta.creator);
            metaHtml += kvRow("Producer", meta.producer);
            metaHtml += kvRow("Creation date", meta.creation_date);
            metaHtml += kvRow("Modified date", meta.modified_date);
            metaHtml += kvRow("Page count", meta.page_count);
            metaHtml += kvRow("JavaScript", meta.javascript_present ? "Present (" + (meta.javascript_markers || []).join(", ") + ")" : "Not found");
            metaHtml += kvRow("Embedded images", meta.embedded_images || "Unknown");
            // document_info
            if (meta.document_info && Object.keys(meta.document_info).length > 0) {
                metaHtml += '<div style="margin-top:10px;color:var(--neon-dim);font-weight:700;letter-spacing:1px;">DOCUMENT INFO</div>';
                for (const [k, v] of Object.entries(meta.document_info)) {
                    metaHtml += kvRow(k, v);
                }
            }
        }
        cardMetadata.innerHTML = metaHtml;

        // RAW HEADER
        if (chkHeader.checked && meta.raw_header) {
            cardHeaderWrap.classList.remove("hidden");
            const rh = meta.raw_header;
            let headerHtml = '';
            headerHtml += '<div class="hex-label">HEX (' + rh.bytes_read + ' bytes)</div>';
            headerHtml += '<div class="hex-block">' + escapeHtml(rh.hex) + '</div>';
            headerHtml += '<div class="hex-label" style="margin-top:10px;">ASCII</div>';
            headerHtml += '<div class="hex-block">' + escapeHtml(rh.ascii) + '</div>';
            cardRawHeader.innerHTML = headerHtml;
        } else {
            cardHeaderWrap.classList.add("hidden");
        }

        // ALL TAGS (collapsible)
        const grouped = meta.grouped_tags;
        const allTags = meta.all_tags;
        let tagsHtml = "";
        if (grouped && Object.keys(grouped).length > 0) {
            for (const [group, tags] of Object.entries(grouped)) {
                tagsHtml += `<div class="tag-group"><div class="tag-group-title">${escapeHtml(group)}</div>`;
                for (const [k, v] of Object.entries(tags)) {
                    tagsHtml += kvRow(k, v);
                }
                tagsHtml += "</div>";
            }
        } else if (allTags && Object.keys(allTags).length > 0) {
            for (const [k, v] of Object.entries(allTags)) {
                tagsHtml += kvRow(k, v);
            }
        } else {
            tagsHtml = '<span style="color:var(--gray);">No tags available.</span>';
        }
        cardAllTags.innerHTML = tagsHtml;

        // Show clean download button if clean checkbox was checked
        btnDownloadClean.style.display = chkClean.checked ? "inline-flex" : "none";

        resultsSection.classList.remove("hidden");
        resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // ── Collapsible toggle for All Tags ──
    toggleAllTags.addEventListener("click", () => {
        const body = cardAllTags;
        const arrow = toggleAllTags.querySelector(".toggle-arrow");
        body.classList.toggle("open");
        arrow.style.transform = body.classList.contains("open") ? "rotate(180deg)" : "";
    });

    // ── Copy JSON ──
    btnCopyJson.addEventListener("click", () => {
        if (!lastResult) { toast("No data to copy."); return; }
        const json = JSON.stringify(lastResult, null, 2);
        navigator.clipboard.writeText(json).then(() => {
            toast("JSON copied to clipboard.");
        }).catch(() => {
            // Fallback
            const ta = document.createElement("textarea");
            ta.value = json;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            ta.remove();
            toast("JSON copied to clipboard.");
        });
    });

    // ── Download report ──
    btnDownloadReport.addEventListener("click", async () => {
        if (!lastResult) { toast("No data to export."); return; }
        try {
            const resp = await fetch("/api/download-report", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(lastResult),
            });
            if (!resp.ok) { toast("Report download failed."); return; }
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "metadata_report.json";
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            toast("Report downloaded.");
        } catch (err) {
            toast("Error: " + err.message);
        }
    });

    // ── Download clean (separate action from bottom) ──
    btnDownloadClean.addEventListener("click", () => {
        btnClean.click();
    });

})();
