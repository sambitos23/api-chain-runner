/* flow.js — Vertical flow, editable drawer, run execution, response display */
(function () {
    const canvas = document.getElementById("flow-canvas");
    const runBtn = document.getElementById("run-btn");
    const pauseBtn = document.getElementById("pause-btn");
    const resumeBtn = document.getElementById("resume-btn");
    const stopBtn = document.getElementById("stop-btn");
    const runStatus = document.getElementById("run-status");
    const runBtnLabel = document.getElementById("run-btn-label");
    const clearSelectionBtn = document.getElementById("clear-selection-btn");
    const runInputsModal = document.getElementById("run-inputs-modal");
    const runInputsBody = document.getElementById("run-inputs-body");
    const runInputsTitle = document.getElementById("run-inputs-title");
    const detailOverlay = document.getElementById("step-detail");
    const detailName = document.getElementById("detail-name");
    const detailBody = document.getElementById("detail-body");
    const detailClose = document.getElementById("detail-close");
    const detailDelete = document.getElementById("detail-delete");
    const deleteConfirmModal = document.getElementById("delete-confirm-modal");
    const deleteConfirmStepName = document.getElementById("delete-confirm-step-name");
    const deleteConfirmClose = document.getElementById("delete-confirm-close");
    const deleteConfirmCancel = document.getElementById("delete-confirm-cancel");
    const deleteConfirmOk = document.getElementById("delete-confirm-ok");
    const detailSave = document.getElementById("detail-save");
    const detailSaveStatus = document.getElementById("detail-save-status");
    const responsePanel = document.getElementById("response-panel");
    const responseList = document.getElementById("response-list");
    const responseClose = document.getElementById("response-close");
    const responseDownloadCsv = document.getElementById("response-download-csv");

    const steps = CHAIN_DATA.steps;
    const stepBoxes = [];
    let currentStepIndex = -1;
    let isCreatingStep = false;
    const selectedSteps = new Set(); // step indexes chosen with Ctrl/Cmd+click
    let insertPosition = null; // index a new step will be inserted at; null appends
    let currentResponseResults = [];

    // ── Render VERTICAL flow ─────────────────────────────────
    function renderFlow() {
        canvas.innerHTML = "";
        stepBoxes.length = 0;

        steps.forEach((step, i) => {
            const node = document.createElement("div");
            node.className = "step-node";
            node.dataset.index = i;

            // Keep the original compact row: side output is attached to the
            // same row while the card, label, and arrow remain in the canvas.
            const row = document.createElement("div");
            row.className = "step-row";

            const box = document.createElement("div");
            box.className = `step-box method-${step.method.toUpperCase()}`;

            const tags = [];
            if (step.has_polling) tags.push("polling");
            if (step.has_payload) tags.push("body");
            if (step.has_files) tags.push("files");
            if (step.has_unique_fields) tags.push("unique");
            if (step.has_condition) tags.push("cond");
            if (step.delay > 0) tags.push(`${step.delay}s`);
            if (!step.continue_on_error) tags.push("stop-on-fail");

            box.innerHTML = `
                <span class="method-badge">${esc(step.method.toUpperCase())}</span>
                <div class="step-name">${esc(step.name)}</div>
                ${tags.length ? `<div class="step-tags">${tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
            `;

            row.appendChild(box);
            node.appendChild(row);

            const idx = document.createElement("div");
            idx.className = "step-index";
            idx.textContent = `Step ${i + 1}`;
            node.appendChild(idx);

            // Hovering a card reveals "Add Step" below it (insert after this
            // step); the first card also gets one above it (insert before).
            if (i === 0) node.appendChild(buildInsertButton(0, "before", step.name));
            node.appendChild(buildInsertButton(i + 1, "after", step.name));

            // Only the step card opens the detail drawer. The row, label,
            // arrow, and side output are deliberately non-interactive.
            // Ctrl/Cmd+click selects a step to run on its own; a plain click opens the drawer.
            // macOS reports Ctrl+click as a context-menu event, so handle both.
            let lastToggle = 0;
            const toggleFromEvent = (e) => {
                e.preventDefault();
                e.stopPropagation();
                const now = Date.now();
                if (now - lastToggle < 300) return;
                lastToggle = now;
                toggleStepSelection(i);
            };
            box.addEventListener("click", (e) => {
                if (!(e.ctrlKey || e.metaKey)) return;
                e.stopImmediatePropagation(); // keep the plain-click handler below from opening the drawer
                toggleFromEvent(e);
            });
            box.addEventListener("click", (e) => { e.stopPropagation(); showDetail(step, i); });
            box.addEventListener("contextmenu", (e) => { if (e.ctrlKey) toggleFromEvent(e); });
            canvas.appendChild(node);
            stepBoxes.push(box);

            // Vertical arrow between steps remains in the original canvas flow.
            if (i < steps.length - 1) {
                const arrow = document.createElement("div");
                arrow.className = "step-arrow";
                arrow.innerHTML = `<svg viewBox="0 0 20 40">
                    <line x1="10" y1="0" x2="10" y2="30" stroke-width="1.5"/>
                    <polygon points="5,30 10,40 15,30"/>
                </svg>`;
                canvas.appendChild(arrow);
            }
        });
    }

    // ── Sidebar step list: jump to a step and open its details ─
    const sidebarSteps = document.getElementById("sidebar-steps");
    const sidebarItems = [];

    function renderSidebarSteps() {
        if (!sidebarSteps) return;
        sidebarSteps.innerHTML = "";
        sidebarItems.length = 0;
        steps.forEach((step, i) => {
            const method = (step.manual ? "MANUAL" : step.method || "").toUpperCase();
            const item = document.createElement("button");
            item.type = "button";
            item.className = "nav-step";
            item.setAttribute("role", "listitem");
            item.title = step.name;
            item.innerHTML = `<span class="nav-step-index">${i + 1}</span>
                <span class="nav-step-method method-${esc(method)}">${esc(method)}</span>
                <span class="nav-step-name">${esc(step.name)}</span>`;
            item.addEventListener("click", () => openStepFromSidebar(i));
            item.title = step.manual ? `${step.name} (manual step)` : `${step.name} — click to open the request panel`;
            sidebarSteps.appendChild(item);
            sidebarItems.push(item);
        });
    }

    function openStepFromSidebar(i) {
        const box = stepBoxes[i];
        if (box) {
            box.scrollIntoView({ block: "center", behavior: "smooth" });
            box.classList.add("flash");
            setTimeout(() => box.classList.remove("flash"), 1400);
        }
        openRequestPanel(i);
    }

    function syncSidebarActive() {
        const open = (!detailOverlay.classList.contains("hidden") && !isCreatingStep) || requestOpenIndex >= 0;
        sidebarItems.forEach((item, i) => {
            const active = open && i === (requestOpenIndex >= 0 ? requestOpenIndex : currentStepIndex);
            item.classList.toggle("active", active);
            if (active) item.setAttribute("aria-current", "true"); else item.removeAttribute("aria-current");
        });
    }
    new MutationObserver(syncSidebarActive).observe(detailOverlay, { attributes: true, attributeFilter: ["class"] });

    // ── Request panel (Postman-style single request) ─────────
    const requestModal = document.getElementById("request-modal");
    const reqTitle = document.getElementById("req-title");
    const reqMethod = document.getElementById("req-method");
    const reqUrl = document.getElementById("req-url");
    const reqSend = document.getElementById("req-send");
    const reqSendLabel = document.getElementById("req-send-label");
    const reqBody = document.getElementById("req-body");
    const reqBodyNote = document.getElementById("req-body-note");
    const reqJsonState = document.getElementById("req-json-state");
    const reqNote = document.getElementById("req-note");
    const reqResolved = document.getElementById("req-resolved");
    const reqMeta = document.getElementById("req-meta");
    const reqResponse = document.getElementById("req-response");
    const rpMethodBadge = document.getElementById("rp-method-badge");
    const rpRequest = document.getElementById("rp-request");
    const rpSplit = document.getElementById("rp-split");
    const rpPanes = {
        params: requestModal.querySelector('[data-pane="params"]'),
        headers: requestModal.querySelector('[data-pane="headers"]'),
    };
    let requestOpenIndex = -1;
    let bodyMode = "none";
    let formTable = null;
    let urlencTable = null;
    let paramsTable = null;
    let headersTable = null;
    let lastResponse = null;
    let isSending = false;
    let elapsedTimer = null;
    let wrapLines = true;
    let syncingUrl = false;

    function flashButton(btn, text = "Copied") {
        const label = btn.querySelector("span");
        const icon = btn.querySelector("use");
        const prevText = label.textContent;
        const prevIcon = icon.getAttribute("href");
        label.textContent = text;
        icon.setAttribute("href", "#i-check");
        btn.classList.add("is-done");
        clearTimeout(btn._flashTimer);
        btn._flashTimer = setTimeout(() => {
            label.textContent = prevText;
            icon.setAttribute("href", prevIcon);
            btn.classList.remove("is-done");
        }, 1400);
    }

    async function copyText(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) {
            const ta = document.createElement("textarea");
            ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
            document.body.appendChild(ta); ta.select();
            let ok = false;
            try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
            ta.remove();
            return ok;
        }
    }

    function safeDecodeParam(text) {
        try { return decodeURIComponent(text.replace(/\+/g, " ")); } catch (e) { return text; }
    }

    function encodeParam(text) {
        // Keep ${...} references readable instead of percent-encoding them.
        return encodeURIComponent(text).replace(/%24/g, "$").replace(/%7B/g, "{").replace(/%7D/g, "}");
    }

    function parseUrlParams(url) {
        const q = url.indexOf("?");
        if (q < 0) return [];
        return url.slice(q + 1).split("#")[0].split("&").filter(Boolean).map(part => {
            const eq = part.indexOf("=");
            return {
                key: safeDecodeParam(eq < 0 ? part : part.slice(0, eq)),
                value: eq < 0 ? "" : safeDecodeParam(part.slice(eq + 1)),
                enabled: true,
            };
        });
    }

    function urlWithParams(url, rows) {
        const hashAt = url.indexOf("#");
        const fragment = hashAt >= 0 ? url.slice(hashAt) : "";
        const noFragment = hashAt >= 0 ? url.slice(0, hashAt) : url;
        const base = noFragment.split("?")[0];
        const query = rows.filter(r => r.key !== "").map(r => `${encodeParam(r.key)}=${encodeParam(r.value)}`).join("&");
        return base + (query ? "?" + query : "") + fragment;
    }

    // Editable key/value rows with an enable checkbox (used for Params and Headers).
    function buildKvTable(rows, { keyPlaceholder, valuePlaceholder, onChange }) {
        const root = document.createElement("div");
        root.className = "rp-kv";
        root.innerHTML = `<div class="rp-kv-head"><span></span><span>Key</span><span>Value</span><span></span></div>`;
        const list = document.createElement("div");
        list.className = "rp-kv-list";
        root.appendChild(list);

        const addRow = (key = "", value = "", enabled = true) => {
            const row = document.createElement("div");
            row.className = "rp-kv-row" + (enabled ? "" : " is-off");
            const chk = document.createElement("input");
            chk.type = "checkbox"; chk.checked = enabled; chk.className = "rp-check"; chk.setAttribute("aria-label", "Include this row");
            const k = document.createElement("input");
            const v = document.createElement("input");
            [k, v].forEach(el => { el.type = "text"; el.className = "rp-kv-input"; el.autocomplete = "off"; el.spellcheck = false; });
            k.placeholder = keyPlaceholder; v.placeholder = valuePlaceholder;
            k.value = key; v.value = value;
            const del = document.createElement("button");
            del.type = "button"; del.className = "rp-icon-btn rp-kv-del"; del.setAttribute("aria-label", "Remove row"); del.title = "Remove";
            del.innerHTML = '<svg class="icon icon-sm"><use href="#i-x"/></svg>';
            chk.addEventListener("change", () => { row.classList.toggle("is-off", !chk.checked); onChange(); });
            k.addEventListener("input", onChange);
            v.addEventListener("input", onChange);
            del.addEventListener("click", () => { row.remove(); onChange(); });
            row.append(chk, k, v, del);
            list.appendChild(row);
            return row;
        };
        const add = document.createElement("button");
        add.type = "button"; add.className = "rp-add";
        add.innerHTML = '<svg class="icon icon-sm"><use href="#i-plus"/></svg><span>Add row</span>';
        add.addEventListener("click", () => { addRow().querySelector(".rp-kv-input").focus(); });
        root.appendChild(add);
        rows.forEach(r => addRow(r.key, r.value, r.enabled !== false));

        const all = () => [...list.querySelectorAll(".rp-kv-row")].map(r => {
            const [k, v] = r.querySelectorAll(".rp-kv-input");
            return { key: k.value.trim(), value: v.value, enabled: r.querySelector(".rp-check").checked };
        });
        return {
            el: root,
            rows: () => all().filter(r => r.enabled && r.key !== ""),
            // Replace the enabled rows (e.g. after the URL was edited) but keep rows the user switched off.
            replaceEnabled: (next) => {
                const off = all().filter(r => !r.enabled);
                list.innerHTML = "";
                next.forEach(r => addRow(r.key, r.value, true));
                off.forEach(r => addRow(r.key, r.value, false));
            },
        };
    }

    // Form-data rows: text or file. A file row takes a path on disk (e.g. from the YAML) or a file picked in the browser.
    function buildFormTable(rows, { onChange, allowFiles }) {
        const root = document.createElement("div");
        root.className = "rp-kv rp-form";
        root.innerHTML = `<div class="rp-kv-head rp-form-head${allowFiles ? "" : " no-type"}"><span></span><span>Key</span>${allowFiles ? "<span>Type</span>" : ""}<span>Value</span><span></span></div>`;
        const list = document.createElement("div");
        root.appendChild(list);

        const addRow = (r = {}) => {
            const row = document.createElement("div");
            const enabled = r.enabled !== false;
            row.className = "rp-kv-row rp-form-row" + (enabled ? "" : " is-off") + (allowFiles ? "" : " no-type");
            row._file = null;
            const chk = document.createElement("input");
            chk.type = "checkbox"; chk.checked = enabled; chk.className = "rp-check"; chk.setAttribute("aria-label", "Include this field");
            const key = document.createElement("input");
            key.type = "text"; key.className = "rp-kv-input"; key.placeholder = "Field name"; key.value = r.key || ""; key.autocomplete = "off"; key.spellcheck = false;
            const type = document.createElement("select");
            type.className = "rp-type"; type.setAttribute("aria-label", "Field type");
            type.innerHTML = '<option value="text">Text</option><option value="file">File</option>';
            type.value = allowFiles && r.type === "file" ? "file" : "text";
            if (!allowFiles) type.hidden = true;

            const cell = document.createElement("div");
            cell.className = "rp-form-cell";
            const text = document.createElement("input");
            text.type = "text"; text.className = "rp-kv-input"; text.autocomplete = "off"; text.spellcheck = false;
            text.value = r.value || "";
            const picker = document.createElement("input");
            picker.type = "file"; picker.hidden = true;
            const browse = document.createElement("button");
            browse.type = "button"; browse.className = "rp-btn rp-btn-sm rp-browse";
            browse.innerHTML = '<svg class="icon icon-sm"><use href="#i-plus"/></svg><span>Choose file</span>';
            const chip = document.createElement("span");
            chip.className = "rp-chipfile hidden";
            cell.append(text, browse, chip, picker);

            const del = document.createElement("button");
            del.type = "button"; del.className = "rp-icon-btn rp-kv-del"; del.setAttribute("aria-label", "Remove field"); del.title = "Remove";
            del.innerHTML = '<svg class="icon icon-sm"><use href="#i-x"/></svg>';

            const paint = () => {
                const isFile = type.value === "file";
                text.placeholder = isFile ? "Path on this machine, or choose a file" : "Value";
                browse.classList.toggle("hidden", !isFile);
                chip.classList.toggle("hidden", !(isFile && row._file));
                text.classList.toggle("hidden", isFile && !!row._file);
                if (row._file) chip.innerHTML = `<span class="rp-chipfile-name">${esc(row._file.name)}</span><span class="rp-chipfile-size">${formatSize(row._file.size)}</span><button type="button" class="rp-chipfile-x" aria-label="Remove chosen file">×</button>`;
            };
            type.addEventListener("change", () => { paint(); onChange(); });
            browse.addEventListener("click", () => picker.click());
            picker.addEventListener("change", () => { row._file = picker.files[0] || null; paint(); onChange(); });
            chip.addEventListener("click", (e) => {
                if (e.target.closest(".rp-chipfile-x")) { row._file = null; picker.value = ""; paint(); onChange(); text.focus(); }
            });
            chk.addEventListener("change", () => { row.classList.toggle("is-off", !chk.checked); onChange(); });
            key.addEventListener("input", onChange);
            text.addEventListener("input", onChange);
            del.addEventListener("click", () => { row.remove(); onChange(); });
            row.append(chk, key, type, cell, del);
            row._get = () => ({ key: key.value.trim(), type: type.value, value: text.value, file: type.value === "file" ? row._file : null, enabled: chk.checked });
            paint();
            list.appendChild(row);
            return row;
        };
        const add = document.createElement("button");
        add.type = "button"; add.className = "rp-add";
        add.innerHTML = '<svg class="icon icon-sm"><use href="#i-plus"/></svg><span>Add field</span>';
        add.addEventListener("click", () => { addRow().querySelector(".rp-kv-input").focus(); onChange(); });
        root.appendChild(add);
        rows.forEach(addRow);
        return { el: root, rows: () => [...list.children].map(r => r._get()).filter(r => r.enabled && r.key !== "") };
    }

    function updateRequestCounts() {
        document.getElementById("req-count-params").textContent = paramsTable.rows().length || "";
        document.getElementById("req-count-headers").textContent = headersTable.rows().length || "";
        const hasBody = bodyMode === "json" ? reqBody.value.trim() !== ""
            : bodyMode === "form" ? !!formTable && formTable.rows().length > 0
            : bodyMode === "urlencoded" ? !!urlencTable && urlencTable.rows().length > 0 : false;
        document.getElementById("req-dot-body").classList.toggle("on", hasBody);
    }

    function updateJsonState() {
        const text = reqBody.value.trim();
        reqJsonState.className = "rp-json-state";
        if (!text) { reqJsonState.textContent = "No body will be sent"; return; }
        try {
            JSON.parse(text);
            reqJsonState.textContent = "Valid JSON";
            reqJsonState.classList.add("ok");
        } catch (e) {
            reqJsonState.textContent = `Invalid JSON: ${e.message}`;
            reqJsonState.classList.add("bad");
        }
    }

    function setTab(group, name) {
        requestModal.querySelectorAll(`.rp-tabs[data-group="${group}"] .rp-tab`).forEach(t => t.classList.toggle("active", t.dataset.tab === name));
        if (group === "request") {
            requestModal.querySelectorAll(".rp-pane").forEach(p => p.classList.toggle("hidden", p.dataset.pane !== name));
        } else {
            renderResponse();
        }
    }
    requestModal.querySelectorAll(".rp-tab").forEach(tab => {
        tab.addEventListener("click", () => setTab(tab.closest(".rp-tabs").dataset.group, tab.dataset.tab));
    });

    function methodClass(method) { return `m-${String(method).toUpperCase()}`; }

    function paintMethod() {
        const m = reqMethod.value;
        reqMethod.className = `rp-method ${methodClass(m)}`;
        rpMethodBadge.textContent = m;
        rpMethodBadge.className = `rp-badge ${methodClass(m)}`;
    }
    reqMethod.addEventListener("change", paintMethod);

    function setBodyMode(mode) {
        bodyMode = mode;
        requestModal.querySelectorAll("#req-body-modes .rp-seg-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
        requestModal.querySelectorAll(".rp-bodymode").forEach(el => el.classList.toggle("hidden", el.dataset.bodymode !== mode));
        const step = steps[requestOpenIndex] || {};
        const notes = [];
        if (mode === "form" || mode === "urlencoded") notes.push("Content-Type is set automatically for this body type, so any Content-Type header is ignored.");
        if (step.unique_fields && Object.keys(step.unique_fields).length && mode !== "none") notes.push("Unique fields (e.g. email, PAN) are regenerated on every send.");
        reqBodyNote.textContent = notes.join(" ");
        reqBodyNote.classList.toggle("hidden", !notes.length);
        if (paramsTable) updateRequestCounts();
    }
    requestModal.querySelectorAll("#req-body-modes .rp-seg-btn").forEach(b => b.addEventListener("click", () => setBodyMode(b.dataset.mode)));

    function payloadRows(payload) {
        if (!payload || typeof payload !== "object" || Array.isArray(payload)) return [];
        return Object.entries(payload).map(([key, v]) => ({
            key, type: "text",
            value: v === null || v === undefined ? "" : (typeof v === "object" ? JSON.stringify(v) : String(v)),
        }));
    }

    function openRequestPanel(i) {
        const step = steps[i];
        if (step.manual) { showDetail(step, i); return; } // no request to send
        requestOpenIndex = i;
        lastResponse = null;
        isSending = false;
        reqTitle.textContent = step.name;
        document.getElementById("rp-step-no").textContent = `Step ${i + 1}`;
        reqMethod.value = (step.method || "GET").toUpperCase();
        reqUrl.value = step.url || "";
        paintMethod();

        paramsTable = buildKvTable(parseUrlParams(reqUrl.value), {
            keyPlaceholder: "Parameter", valuePlaceholder: "Value",
            onChange: () => {
                syncingUrl = true;
                reqUrl.value = urlWithParams(reqUrl.value, paramsTable.rows());
                syncingUrl = false;
                updateRequestCounts();
            },
        });
        const headerRows = Object.entries(step.headers || {}).map(([key, value]) => ({ key, value: String(value), enabled: true }));
        headersTable = buildKvTable(headerRows, { keyPlaceholder: "Header", valuePlaceholder: "Value", onChange: updateRequestCounts });
        rpPanes.params.replaceChildren(paramsTable.el);
        rpPanes.headers.replaceChildren(headersTable.el);

        const hasPayload = step.payload !== null && step.payload !== undefined && step.payload !== "";
        const fileRows = [];
        Object.entries(step.files || {}).forEach(([key, v]) => (Array.isArray(v) ? v : [v]).forEach(path => fileRows.push({ key, type: "file", value: String(path) })));
        reqBody.value = hasPayload ? JSON.stringify(step.payload, null, 2) : "";
        updateJsonState();
        formTable = buildFormTable([...payloadRows(step.payload), ...fileRows], { onChange: updateRequestCounts, allowFiles: true });
        urlencTable = buildFormTable(payloadRows(step.payload), { onChange: updateRequestCounts, allowFiles: false });
        requestModal.querySelector('[data-bodymode="form"]').replaceChildren(formTable.el);
        requestModal.querySelector('[data-bodymode="urlencoded"]').replaceChildren(urlencTable.el);
        setBodyMode(fileRows.length ? "form" : hasPayload ? "json" : "none");
        const refs = /\$\{(?!ENV:|vars\.)[^}]+\}/.test(JSON.stringify([step.url, step.headers, step.payload]));
        reqNote.textContent = refs ? "Uses ${step.key} references. They resolve from the last run of this flow or earlier sends. Run the chain first, or replace them with literal values." : "";
        reqNote.classList.toggle("hidden", !refs);
        reqResolved.classList.add("hidden");

        reqMeta.innerHTML = "";
        document.getElementById("req-count-resp-headers").textContent = "";
        rpRequest.style.height = "";
        setTab("request", bodyMode !== "none" && !Object.keys(step.headers || {}).length && !parseUrlParams(reqUrl.value).length ? "body" : "params");
        setTab("response", "resp-body");
        updateRequestCounts();
        requestModal.classList.remove("hidden");
        syncSidebarActive();
        reqSend.focus();
    }

    function closeRequestPanel() {
        requestModal.classList.add("hidden");
        requestOpenIndex = -1;
        clearInterval(elapsedTimer);
        syncSidebarActive();
    }

    reqUrl.addEventListener("input", () => {
        if (syncingUrl || !paramsTable) return;
        paramsTable.replaceEnabled(parseUrlParams(reqUrl.value));
        updateRequestCounts();
    });

    reqBody.addEventListener("input", () => { updateJsonState(); updateRequestCounts(); });
    reqBody.addEventListener("keydown", (e) => {
        if (e.key !== "Tab") return;
        e.preventDefault();
        const { selectionStart: s0, selectionEnd: s1 } = reqBody;
        reqBody.setRangeText("  ", s0, s1, "end");
        updateJsonState();
    });
    document.getElementById("req-beautify").addEventListener("click", () => {
        try {
            reqBody.value = JSON.stringify(JSON.parse(reqBody.value), null, 2);
            updateJsonState();
        } catch (e) { updateJsonState(); reqJsonState.classList.add("shake"); setTimeout(() => reqJsonState.classList.remove("shake"), 400); }
    });

    // JSON syntax highlighting (escaped first, so response content can never inject markup).
    function highlightJson(text) {
        const safe = esc(text);
        return safe.replace(
            /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
            (m) => {
                let cls = "tok-num";
                if (m.startsWith('"')) cls = /:\s*$/.test(m) ? "tok-key" : "tok-str";
                else if (m === "true" || m === "false") cls = "tok-bool";
                else if (m === "null") cls = "tok-null";
                return `<span class="${cls}">${m}</span>`;
            }
        );
    }

    function looksLikeJson(text) {
        const t = text.trim();
        return (t.startsWith("{") && t.endsWith("}")) || (t.startsWith("[") && t.endsWith("]"));
    }

    function activeResponseTab() {
        const t = requestModal.querySelector('.rp-tabs[data-group="response"] .rp-tab.active');
        return t ? t.dataset.tab : "resp-body";
    }

    function emptyState(title, hint, spinner) {
        const el = document.createElement("div");
        el.className = "rp-empty";
        el.innerHTML = `${spinner ? '<span class="rp-spinner"></span>' : '<svg class="icon icon-xl"><use href="#i-play"/></svg>'}
            <div class="rp-empty-title">${esc(title)}</div><div class="rp-empty-hint">${hint}</div>`;
        return el;
    }

    function renderResponse() {
        const tab = activeResponseTab();
        reqResponse.innerHTML = "";
        reqResponse.classList.toggle("is-wrap", wrapLines);
        requestModal.querySelector(".rp-toolbar").classList.toggle("hidden", tab !== "resp-body" || !lastResponse || lastResponse.status_code === undefined);

        if (isSending) {
            const el = emptyState("Sending request…", '<span id="rp-elapsed">0 ms</span>', true);
            reqResponse.appendChild(el);
            return;
        }
        if (!lastResponse) {
            reqResponse.appendChild(emptyState("Ready when you are", "Press <kbd class=\"rp-kbd\">Send</kbd> or <kbd class=\"rp-kbd\">Ctrl/⌘ + Enter</kbd> to run this request."));
            return;
        }
        if (lastResponse.status_code === undefined) {
            const err = document.createElement("div");
            err.className = "rp-error";
            err.innerHTML = `<strong>Couldn't send the request</strong><span>${esc(lastResponse.error || "Request failed")}</span>`;
            reqResponse.appendChild(err);
            return;
        }
        if (tab === "resp-headers") {
            const entries = Object.entries(lastResponse.response_headers || {});
            if (!entries.length) { reqResponse.appendChild(emptyState("No response headers", "")); return; }
            const table = document.createElement("div");
            table.className = "rp-headers";
            entries.forEach(([k, v]) => {
                const row = document.createElement("button");
                row.type = "button";
                row.className = "rp-headers-row";
                row.title = "Click to copy value";
                row.innerHTML = `<span class="rp-headers-key">${esc(k)}</span><span class="rp-headers-val">${esc(String(v))}</span><svg class="icon icon-sm rp-headers-copy"><use href="#i-copy"/></svg>`;
                row.addEventListener("click", async () => {
                    if (await copyText(String(v))) {
                        row.classList.add("copied");
                        setTimeout(() => row.classList.remove("copied"), 1200);
                    }
                });
                table.appendChild(row);
            });
            reqResponse.appendChild(table);
            return;
        }
        if (lastResponse.error) {
            const err = document.createElement("div");
            err.className = "rp-error";
            err.innerHTML = `<strong>Request failed</strong><span>${esc(lastResponse.error)}</span>`;
            reqResponse.appendChild(err);
        }
        const text = lastResponse.response_body || "";
        if (!text) {
            if (!lastResponse.error) reqResponse.appendChild(emptyState("No response body", ""));
            return;
        }
        const pre = document.createElement("pre");
        pre.className = "rp-code";
        if (looksLikeJson(text) && text.length < 400000) pre.innerHTML = highlightJson(text);
        else pre.textContent = text;
        reqResponse.appendChild(pre);
    }

    function formatSize(bytes) {
        if (bytes < 1024) return `${bytes} B`;
        return bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
    }

    function statusText(code) {
        const names = { 200: "OK", 201: "Created", 202: "Accepted", 204: "No Content", 301: "Moved Permanently", 302: "Found", 304: "Not Modified",
            400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 422: "Unprocessable Entity",
            429: "Too Many Requests", 500: "Internal Server Error", 502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout" };
        return names[code] || "";
    }

    function currentRequestParts() {
        const headers = {};
        headersTable.rows().forEach(r => { headers[r.key] = r.value; });
        const meta = { method: reqMethod.value, url: reqUrl.value, headers, body_mode: bodyMode, body: bodyMode === "json" ? reqBody.value : "", fields: [] };
        const uploads = [];
        const table = bodyMode === "form" ? formTable : bodyMode === "urlencoded" ? urlencTable : null;
        if (table) {
            table.rows().forEach(r => {
                const field = { key: r.key, type: r.type, value: r.value };
                if (r.type === "file" && r.file) { field.upload = `file_${uploads.length}`; uploads.push(r.file); }
                meta.fields.push(field);
            });
        }
        return { meta, uploads };
    }

    function buildCurl() {
        const { meta, uploads } = currentRequestParts();
        const q = (t) => `'${String(t).replace(/'/g, "'\\''")}'`;
        const parts = [`curl -X ${meta.method} ${q(meta.url)}`];
        Object.entries(meta.headers).forEach(([k, v]) => {
            if ((meta.body_mode === "form" || meta.body_mode === "urlencoded") && k.toLowerCase() === "content-type") return;
            parts.push(`-H ${q(`${k}: ${v}`)}`);
        });
        if (meta.body_mode === "json" && meta.body.trim()) parts.push(`--data-raw ${q(meta.body)}`);
        if (meta.body_mode === "form") {
            meta.fields.forEach(f => {
                if (f.type !== "file") parts.push(`-F ${q(`${f.key}=${f.value}`)}`);
                else if (f.upload) parts.push(`-F ${q(`${f.key}=@${uploads[Number(f.upload.slice(5))].name}`)}`);
                else if (f.value) parts.push(`-F ${q(`${f.key}=@${f.value}`)}`);
            });
        }
        if (meta.body_mode === "urlencoded") meta.fields.forEach(f => parts.push(`--data-urlencode ${q(`${f.key}=${f.value}`)}`));
        return parts.join(" \\\n  ");
    }

    async function sendRequest() {
        if (requestOpenIndex < 0 || isSending) return;
        const sentAt = performance.now();
        isSending = true;
        lastResponse = null;
        reqSend.disabled = true;
        reqSend.classList.add("is-sending");
        reqSendLabel.textContent = "Sending";
        reqMeta.innerHTML = "";
        reqResolved.classList.add("hidden");
        setTab("response", "resp-body");
        clearInterval(elapsedTimer);
        elapsedTimer = setInterval(() => {
            const el = document.getElementById("rp-elapsed");
            if (el) el.textContent = `${Math.round(performance.now() - sentAt)} ms`;
        }, 60);
        const sent = currentRequestParts();
        try {
            const endpoint = `/api/flow/${FLOW_PATH}/step/${requestOpenIndex}/send`;
            let init;
            if (sent.uploads.length) {
                const fd = new FormData();
                fd.append("meta", JSON.stringify(sent.meta));
                sent.uploads.forEach((file, n) => fd.append(`file_${n}`, file, file.name));
                init = { method: "POST", headers: { "X-ACR-Request": "1" }, body: fd };
            } else {
                init = { method: "POST", headers: { "Content-Type": "application/json", "X-ACR-Request": "1" }, body: JSON.stringify(sent.meta) };
            }
            const res = await fetch(endpoint, init);
            const data = await res.json();
            if (!res.ok || (data.error && data.status_code === undefined)) {
                lastResponse = { error: data.error || "Request failed" };
                reqMeta.innerHTML = `<span class="rp-chip rp-chip-err">Error</span>`;
            } else {
                lastResponse = data;
                const cls = data.status_code > 0 ? statusClass(data.status_code) : "err";
                const label = data.status_code > 0 ? `${data.status_code} ${statusText(data.status_code)}`.trim() : "No response";
                reqMeta.innerHTML = `<span class="rp-chip rp-chip-${cls}">${esc(label)}</span>
                    <span class="rp-stat" title="Time"><svg class="icon icon-sm"><use href="#i-retry"/></svg>${Math.round(data.duration_ms)} ms</span>
                    <span class="rp-stat" title="Size">${formatSize(data.size_bytes)}</span>`;
                document.getElementById("req-count-resp-headers").textContent = Object.keys(data.response_headers || {}).length || "";
                if (data.resolved_url && data.resolved_url !== sent.meta.url) {
                    reqResolved.innerHTML = `<span>Sent to</span> <code>${esc(data.resolved_url)}</code>`;
                    reqResolved.classList.remove("hidden");
                }
            }
        } catch (err) {
            lastResponse = { error: err.message };
            reqMeta.innerHTML = `<span class="rp-chip rp-chip-err">Error</span>`;
        } finally {
            clearInterval(elapsedTimer);
            isSending = false;
            reqSend.disabled = false;
            reqSend.classList.remove("is-sending");
            reqSendLabel.textContent = "Send";
        }
        renderResponse();
    }

    reqSend.addEventListener("click", sendRequest);
    reqUrl.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); sendRequest(); } });
    requestModal.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); sendRequest(); }
    });
    document.getElementById("req-close").addEventListener("click", closeRequestPanel);
    document.getElementById("req-edit-step").addEventListener("click", () => {
        const i = requestOpenIndex;
        closeRequestPanel();
        if (i >= 0) showDetail(steps[i], i);
    });
    document.getElementById("req-curl").addEventListener("click", async (e) => {
        if (await copyText(buildCurl())) flashButton(e.currentTarget, "Copied");
    });
    document.getElementById("req-copy").addEventListener("click", async (e) => {
        if (lastResponse && await copyText(lastResponse.response_body || "")) flashButton(e.currentTarget, "Copied");
    });
    document.getElementById("req-wrap").addEventListener("click", (e) => {
        wrapLines = !wrapLines;
        e.currentTarget.classList.toggle("is-on", wrapLines);
        reqResponse.classList.toggle("is-wrap", wrapLines);
    });
    document.getElementById("req-wrap").classList.add("is-on");
    requestModal.addEventListener("mousedown", (e) => { if (e.target === requestModal) closeRequestPanel(); });

    // Drag the divider to give the request or the response more room.
    rpSplit.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        rpSplit.setPointerCapture(e.pointerId);
        rpSplit.classList.add("dragging");
        const startY = e.clientY;
        const startH = rpRequest.getBoundingClientRect().height;
        const bodyH = document.getElementById("rp-body").getBoundingClientRect().height;
        const move = (ev) => {
            const next = Math.min(Math.max(startH + (ev.clientY - startY), 110), bodyH - 190);
            rpRequest.style.height = `${next}px`;
        };
        const up = () => {
            rpSplit.classList.remove("dragging");
            rpSplit.removeEventListener("pointermove", move);
            rpSplit.removeEventListener("pointerup", up);
        };
        rpSplit.addEventListener("pointermove", move);
        rpSplit.addEventListener("pointerup", up);
    });
    rpSplit.addEventListener("dblclick", () => { rpRequest.style.height = ""; });

    // ── Step selection (run only chosen steps) ───────────────
    function toggleStepSelection(i) {
        if (selectedSteps.has(i)) selectedSteps.delete(i); else selectedSteps.add(i);
        refreshSelectionUI();
    }

    function clearSelection() {
        selectedSteps.clear();
        refreshSelectionUI();
    }

    function refreshSelectionUI() {
        const order = [...selectedSteps].sort((a, b) => a - b);
        stepBoxes.forEach((box, i) => {
            box.classList.toggle("is-selected", selectedSteps.has(i));
            let badge = box.querySelector(".step-select-badge");
            if (selectedSteps.has(i)) {
                if (!badge) {
                    badge = document.createElement("span");
                    badge.className = "step-select-badge";
                    box.appendChild(badge);
                }
                badge.textContent = order.indexOf(i) + 1;
            } else if (badge) {
                badge.remove();
            }
        });
        runBtnLabel.textContent = order.length ? `Run Selected (${order.length})` : "Run Chain";
        clearSelectionBtn.classList.toggle("hidden", order.length === 0);
    }

    clearSelectionBtn.addEventListener("click", clearSelection);
    window.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        if (!requestModal.classList.contains("hidden")) closeRequestPanel();
        else if (!runInputsModal.classList.contains("hidden")) closeRunInputs();
        else if (selectedSteps.size && detailOverlay.classList.contains("hidden")) clearSelection();
    });

    // ── Values popup for selected steps ──────────────────────
    function safeDecode(text) {
        try { return decodeURIComponent(text.replace(/\+/g, " ")); } catch (e) { return text; }
    }

    function queryFields(step) {
        const url = step.url || "";
        const q = url.indexOf("?");
        if (q < 0) return [];
        const query = url.slice(q + 1).split("#")[0];
        const fields = [];
        query.split("&").forEach((part, index) => {
            if (!part) return;
            const eq = part.indexOf("=");
            const key = safeDecode(eq < 0 ? part : part.slice(0, eq));
            const value = eq < 0 ? "" : safeDecode(part.slice(eq + 1));
            fields.push({ kind: "query", index, label: key, value, original: value });
        });
        return fields;
    }

    function payloadFields(payload) {
        const fields = [];
        const walk = (node, path) => {
            if (Array.isArray(node)) {
                node.forEach((item, i) => walk(item, path.concat(i)));
            } else if (node && typeof node === "object") {
                Object.entries(node).forEach(([k, v]) => walk(v, path.concat(k)));
            } else if (path.length) {
                const label = path.map((seg, n) => typeof seg === "number" ? `[${seg}]` : (n ? `.${seg}` : seg)).join("");
                const type = typeof node === "boolean" ? "boolean" : "text";
                const value = node === null || node === undefined ? "" : String(node);
                fields.push({ kind: "payload", path, label, value, original: value, type });
            }
        };
        walk(payload, []);
        return fields;
    }

    function stepFields(step) {
        if (step.manual) return { query: [], payload: [] };
        return { query: queryFields(step), payload: payloadFields(step.payload) };
    }

    function unselectedRefs(value, selectedNames) {
        const names = new Set(steps.map(s => s.name));
        const found = new Set();
        String(value).replace(/\$\{([^}.]+)\./g, (m, name) => {
            if (names.has(name) && !selectedNames.has(name)) found.add(name);
            return m;
        });
        return [...found];
    }

    let pendingRunFields = [];

    function closeRunInputs() {
        runInputsModal.classList.add("hidden");
        pendingRunFields = [];
    }

    function openRunInputs() {
        const order = [...selectedSteps].sort((a, b) => a - b);
        const selectedNames = new Set(order.map(i => steps[i].name));
        runInputsBody.innerHTML = "";
        pendingRunFields = [];
        let fieldCount = 0;

        order.forEach(i => {
            const step = steps[i];
            const { query, payload } = stepFields(step);
            const section = document.createElement("section");
            section.className = "run-inputs-step";
            section.innerHTML = `<div class="run-inputs-step-head">
                <span class="step-select-badge static">${order.indexOf(i) + 1}</span>
                <span class="run-inputs-step-name">${esc(step.name)}</span>
                <span class="run-inputs-method">${esc((step.method || "").toUpperCase())}</span>
            </div>`;
            [["Query params", query], ["Payload", payload]].forEach(([title, list]) => {
                if (!list.length) return;
                const group = document.createElement("div");
                group.className = "run-inputs-group";
                group.innerHTML = `<div class="run-inputs-group-title">${title}</div>`;
                list.forEach(field => {
                    fieldCount++;
                    const row = document.createElement("label");
                    row.className = "run-inputs-row";
                    const key = document.createElement("span");
                    key.className = "run-inputs-key";
                    key.textContent = field.label;
                    key.title = field.label;
                    let input;
                    if (field.type === "boolean") {
                        input = document.createElement("select");
                        ["true", "false"].forEach(v => {
                            const o = document.createElement("option");
                            o.value = v; o.textContent = v;
                            input.appendChild(o);
                        });
                        input.value = field.value;
                    } else {
                        input = document.createElement("input");
                        input.type = "text";
                        input.value = field.value;
                        input.autocomplete = "off";
                        input.spellcheck = false;
                    }
                    input.className = "form-input run-inputs-input";
                    row.appendChild(key);
                    row.appendChild(input);
                    const refs = unselectedRefs(field.value, selectedNames);
                    if (refs.length) {
                        input.classList.add("needs-value");
                        const hint = document.createElement("span");
                        hint.className = "run-inputs-hint";
                        hint.textContent = `Uses a value from ${refs.join(", ")}, which isn't selected. Enter a value to use instead.`;
                        row.appendChild(hint);
                    }
                    group.appendChild(row);
                    pendingRunFields.push({ stepIndex: i, field, input });
                });
                section.appendChild(group);
            });
            if (!query.length && !payload.length) {
                const none = document.createElement("div");
                none.className = "run-inputs-none";
                none.textContent = "No payload or query parameters.";
                section.appendChild(none);
            }
            runInputsBody.appendChild(section);
        });

        if (!fieldCount) { startRun({ steps: order }); return; }
        runInputsTitle.textContent = `Run ${order.length} selected step${order.length > 1 ? "s" : ""}`;
        runInputsModal.classList.remove("hidden");
        pendingRunFields[0]?.input.focus();
    }

    function submitRunInputs() {
        const order = [...selectedSteps].sort((a, b) => a - b);
        const overrides = {};
        pendingRunFields.forEach(({ stepIndex, field, input }) => {
            if (input.value === field.original) return; // untouched values stay as written in the YAML
            const entry = overrides[stepIndex] || (overrides[stepIndex] = { query: [], payload: [] });
            if (field.kind === "query") entry.query.push({ index: field.index, value: input.value });
            else entry.payload.push({ path: field.path, value: input.value });
        });
        closeRunInputs();
        startRun({ steps: order, overrides });
    }

    document.getElementById("run-inputs-close").addEventListener("click", closeRunInputs);
    document.getElementById("run-inputs-cancel").addEventListener("click", closeRunInputs);
    document.getElementById("run-inputs-run").addEventListener("click", submitRunInputs);
    runInputsModal.addEventListener("click", (e) => { if (e.target === runInputsModal) closeRunInputs(); });
    runInputsBody.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); submitRunInputs(); }
    });

    function buildInsertButton(position, side, stepName) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `insert-step-btn insert-${side}`;
        btn.setAttribute("aria-label", `Add step ${side} ${stepName}`);
        btn.innerHTML = `<span class="insert-step-plus" aria-hidden="true">+</span><span class="insert-step-label">Add Step</span>`;
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            openNewStepDrawer(position);
        });
        return btn;
    }

    function blankStep(manual, name = "") {
        if (manual) {
            return { name, method: "", url: "", manual: true, instruction: "", print_ref: [], condition: [], delay: 0, continue_on_error: true, headers: {} };
        }
        return {
            name,
            method: "GET",
            url: "",
            manual: false,
            continue_on_error: true,
            delay: 0,
            headers: {},
            print_keys: [],
            condition: [],
            retry: false,
        };
    }
    function openNewStepDrawer(position) {
        insertPosition = position;
        showDetail(blankStep(false), -1, true);
        detailBody.querySelector('[data-field="name"]')?.focus();
    }
    // ── Detail drawer with editable fields ───────────────────
    function showDetail(step, index, isNew = false) {
        currentStepIndex = index;
        isCreatingStep = isNew;
        queueMicrotask(syncSidebarActive); // runs after the drawer is shown, so switching steps updates the highlight
        detailName.textContent = isNew ? "Add Step" : step.name;
        detailDelete.classList.toggle("hidden", isNew);
        detailSave.textContent = isNew ? "Save Step" : "Save Changes";
        detailSaveStatus.textContent = "";
        detailSaveStatus.className = "detail-save-status";

        const isManual = step.manual;
        const curMethod = step.method.toUpperCase();
        let html = "";

        if (isNew) {
            html += `<div class="detail-row"><div class="detail-label">Step type</div>
                <div class="rp-seg" id="new-step-type" role="group" aria-label="Step type">
                    <button type="button" class="rp-seg-btn${isManual ? "" : " active"}" data-type="api">API request</button>
                    <button type="button" class="rp-seg-btn${isManual ? " active" : ""}" data-type="manual">Manual step</button>
                </div></div>`;
        }
        if (isManual) {
            // ── Manual step UI ──
            if (!isNew) html += `<div class="detail-row"><div class="detail-label">Type</div><div class="detail-value">Manual Step</div></div>`;
            html += inputRow("name", "Step Name", step.name || "");
            html += editableRow("instruction", "Instruction", step.instruction || "");
            html += buildListField("print_ref", "Print References", step.print_ref || [], "e.g. create-lead.leadId");
            html += buildToggleSection("condition", "Conditions", (step.condition || []).length ? step.condition : null, buildConditionFields);
            html += numberRow("delay", "Delay (seconds)", step.delay || 0);
            html += dropdownRow("continue_on_error", "Continue on Error", step.continue_on_error);
        } else {
            // ── API step UI ──
            html += inputRow("name", "Step Name", step.name || "");
            const methods = ["GET","POST","PUT","DELETE","PATCH","HEAD","OPTIONS"];
            html += `<div class="detail-row"><div class="detail-label">Method</div>
                <select class="detail-select" data-field="method">${methods.map(m => `<option${m===curMethod?" selected":""}>${m}</option>`).join("")}</select></div>`;
            html += inputRow("url", "URL", step.url || "");
            html += numberRow("delay", "Delay (seconds)", step.delay || 0);
            html += dropdownRow("continue_on_error", "Continue on Error", step.continue_on_error);
            html += editableRow("headers", "Headers", step.headers && Object.keys(step.headers).length ? JSON.stringify(step.headers, null, 2) : "{}");

            if (curMethod !== "GET" && curMethod !== "HEAD" && curMethod !== "OPTIONS") {
                html += editableRow("payload", "Payload", step.payload ? JSON.stringify(step.payload, null, 2) : "");
                html += editableRow("unique_fields", "Unique Fields", step.unique_fields ? JSON.stringify(step.unique_fields, null, 2) : "");
                html += editableRow("files", "Files", step.files ? JSON.stringify(step.files, null, 2) : "");
            }

            // Print Keys — structured list
            html += buildListField("print_keys", "Print Keys", step.print_keys || [], "e.g. leadId");
            html += buildToggleSection("condition", "Conditions", (step.condition || []).length ? step.condition : null, buildConditionFields);

            // Polling — structured
            const p = (step.has_polling && step.polling) ? step.polling : null;
            html += buildToggleSection("polling", "Polling", p, buildPollingFields);

            // Retry — structured
            const retryData = step.retry;
            const hasRetry = retryData && retryData !== false && typeof retryData === "object";
            html += buildToggleSection("retry", "Retry", hasRetry ? retryData : null, buildRetryFields);

            // Eval Keys — structured
            const hasEval = step.eval_keys && Object.keys(step.eval_keys).length;
            html += buildToggleSection("eval", "Eval Keys", hasEval ? step : null, buildEvalFields);
        }

        detailBody.innerHTML = html;
        wireToggleSections();
        wireListFields();
        wireConditionFields();
        if (isNew) {
            // Switching type rebuilds the form but keeps whatever name was already typed.
            detailBody.querySelectorAll("#new-step-type .rp-seg-btn").forEach(btn => btn.addEventListener("click", () => {
                const wantManual = btn.dataset.type === "manual";
                if (wantManual === !!isManual) return;
                const typedName = detailBody.querySelector('[data-field="name"]')?.value || "";
                showDetail(blankStep(wantManual, typedName), -1, true);
                detailBody.querySelector(wantManual ? '[data-field="instruction"]' : '[data-field="url"]')?.focus();
            }));
        }
        detailOverlay.classList.remove("hidden");
    }

    // ── Field builders ───────────────────────────────────────
    function inputRow(field, label, value) {
        return `<div class="detail-row"><div class="detail-label">${esc(label)}</div>
            <input class="detail-editable-input" data-field="${esc(field)}" value="${esc(String(value))}" spellcheck="false"></div>`;
    }
    function numberRow(field, label, value) {
        return `<div class="detail-row"><div class="detail-label">${esc(label)}</div>
            <input type="number" class="detail-editable-input" data-field="${esc(field)}" value="${value}" min="0"></div>`;
    }
    function dropdownRow(field, label, currentVal) {
        return `<div class="detail-row"><div class="detail-label">${esc(label)}</div>
            <select class="detail-select" data-field="${esc(field)}">
                <option value="true"${currentVal?" selected":""}>true</option>
                <option value="false"${!currentVal?" selected":""}>false</option>
            </select></div>`;
    }
    function editableRow(field, label, value) {
        return `<div class="detail-row"><div class="detail-label">${esc(label)}</div>
            <textarea class="detail-editable" data-field="${esc(field)}" spellcheck="false">${esc(String(value))}</textarea></div>`;
    }

    // List field — add/remove items
    function buildListField(field, label, items, placeholder) {
        let html = `<div class="detail-row"><div class="detail-label">${esc(label)}</div>
            <div class="list-field" data-list-field="${esc(field)}">`;
        (items || []).forEach(item => {
            html += `<div class="list-item"><input class="detail-editable-input list-input" value="${esc(item)}" placeholder="${esc(placeholder)}"><button class="btn-icon-only list-remove" title="Remove">×</button></div>`;
        });
        html += `<button class="btn btn-ghost btn-sm list-add">+ Add</button></div></div>`;
        return html;
    }

    function wireListFields() {
        detailBody.querySelectorAll(".list-field").forEach(container => {
            container.querySelector(".list-add").addEventListener("click", () => {
                const item = document.createElement("div");
                item.className = "list-item";
                item.innerHTML = `<input class="detail-editable-input list-input" placeholder=""><button class="btn-icon-only list-remove" title="Remove">×</button>`;
                container.insertBefore(item, container.querySelector(".list-add"));
                item.querySelector(".list-remove").addEventListener("click", () => item.remove());
            });
            container.querySelectorAll(".list-remove").forEach(btn => {
                btn.addEventListener("click", () => btn.parentElement.remove());
            });
        });
    }

    function buildConditionFields(conditions) {
        let html = `<div class="condition-param">
            <div class="condition-entries">`;
        (conditions || []).forEach(condition => {
            html += buildConditionEntry(condition);
        });
        return html + `</div><button type="button" class="btn btn-ghost btn-sm condition-add">+ Add Condition</button></div>`;
    }

    function conditionOperatorOptions(current) {
        const options = [
            ["equals", "Equals"],
            ["not_equals", "Not equals"],
            ["contains", "Contains"],
            ["not_contains", "Does not contain"],
            ["greater_than", "Greater than"],
            ["greater_than_or_equal", "Greater than or equal"],
            ["less_than", "Less than"],
            ["less_than_or_equal", "Less than or equal"],
            ["starts_with", "Starts with"],
            ["ends_with", "Ends with"],
            ["is_null", "Is null"],
            ["is_not_null", "Is not null"],
        ];
        const selected = current || "equals";
        return options.map(([value, label]) =>
            `<option value="${value}"${selected === value ? " selected" : ""}>${label}</option>`
        ).join("");
    }

    function buildConditionEntry(condition) {
        const item = condition || {};
        return `<div class="condition-entry">
            <label class="poll-label">Source Step</label>
            <input class="detail-editable-input condition-input" data-condition="step" value="${esc(String(item.step ?? ""))}" placeholder="e.g. check-status" spellcheck="false">
            <label class="poll-label">Response Key Path</label>
            <input class="detail-editable-input condition-input" data-condition="key_path" value="${esc(String(item.key_path ?? ""))}" placeholder="e.g. status.value" spellcheck="false">
            <label class="poll-label">Operator</label>
            <select class="detail-select condition-input" data-condition="operator">
                ${conditionOperatorOptions(item.operator)}
            </select>
            <label class="poll-label">Expected Value</label>
            <input class="detail-editable-input condition-input" data-condition="expected_value" value="${esc(String(item.expected_value ?? ""))}" placeholder="e.g. SUCCESS" spellcheck="false">
            <button type="button" class="btn-icon-only condition-remove" title="Remove condition" aria-label="Remove condition">×</button>
        </div>`;
    }

    function wireConditionFields() {
        if (detailBody.dataset.conditionWired) return;
        detailBody.dataset.conditionWired = "true";
        detailBody.addEventListener("click", (event) => {
            const addButton = event.target.closest(".condition-add");
            if (addButton && detailBody.contains(addButton)) {
                const entries = addButton.closest(".condition-param").querySelector(".condition-entries");
                const wrapper = document.createElement("div");
                wrapper.innerHTML = buildConditionEntry({});
                const entry = wrapper.firstElementChild;
                entries.appendChild(entry);
                entry.querySelector('[data-condition="step"]').focus();
                return;
            }
            const removeButton = event.target.closest(".condition-remove");
            if (removeButton && detailBody.contains(removeButton)) {
                removeButton.closest(".condition-entry").remove();
            }
        });
    }

    // Toggle section — add/remove structured block
    function buildToggleSection(id, label, data, buildFn) {
        const hasData = data !== null && data !== undefined;
        return `<div class="detail-row"><div class="detail-label">${esc(label)}</div>
            <div class="toggle-section" id="${id}-section">
                ${hasData ? buildFn(data) : `<div class="polling-empty">Not configured</div>`}
                <button type="button" class="btn btn-ghost btn-sm toggle-btn" data-target="${id}" style="margin-top:0.4rem">${hasData ? "Remove" : "+ Add"}</button>
            </div></div>`;
    }

    function wireToggleSections() {
        if (detailBody.dataset.toggleWired) return;
        detailBody.dataset.toggleWired = "true";
        detailBody.addEventListener("click", (event) => {
            const button = event.target.closest(".toggle-btn");
            if (!button || !detailBody.contains(button)) return;
            const id = button.dataset.target;
            const section = document.getElementById(id + "-section");
            const hasParam = section.querySelector(".polling-param, .retry-param, .eval-param, .condition-param");
            if (hasParam) {
                section.innerHTML = `<div class="polling-empty">Not configured</div><button type="button" class="btn btn-ghost btn-sm toggle-btn" data-target="${id}" style="margin-top:0.4rem">+ Add</button>`;
                return;
            }
            const buildFn = id === "polling" ? buildPollingFields
                : id === "retry" ? buildRetryFields
                : id === "condition" ? buildConditionFields
                : buildEvalFields;
            const defaults = id === "polling"
                ? {key_path:"",expected_values:[],interval:10,max_timeout:120}
                : id === "retry"
                ? {max_attempts:3,delay:5,retry_on:["timeout","connection","5xx"]}
                : id === "condition"
                ? []
                : {eval_keys:{},eval_condition:"",success_message:"",failure_message:""};
            section.innerHTML = buildFn(defaults) + `<button type="button" class="btn btn-ghost btn-sm toggle-btn" data-target="${id}" style="margin-top:0.4rem">Remove</button>`;
        });
    }

    function buildPollingFields(p) {
        return `<div class="polling-param">
            <label class="poll-label">Key Path</label>
            <input class="detail-editable-input poll-input" data-poll="key_path" value="${esc(p.key_path || "")}" placeholder="e.g. status or applications.-1.status">
            <label class="poll-label">Expected Values (comma separated)</label>
            <input class="detail-editable-input poll-input" data-poll="expected_values" value="${esc((p.expected_values||[]).join(", "))}" placeholder="e.g. APPROVED, COMPLETED">
            <label class="poll-label">Interval (seconds)</label>
            <input type="number" class="detail-editable-input poll-input" data-poll="interval" value="${p.interval||10}" min="1">
            <label class="poll-label">Max Timeout (seconds)</label>
            <input type="number" class="detail-editable-input poll-input" data-poll="max_timeout" value="${p.max_timeout||120}" min="1">
        </div>`;
    }

    function buildEvalFields(s) {
        const ek = s.eval_keys || {};
        return `<div class="eval-param">
            <label class="poll-label">Eval Keys (JSON: alias → path)</label>
            <textarea class="detail-editable eval-input" data-eval="eval_keys" spellcheck="false">${esc(Object.keys(ek).length ? JSON.stringify(ek, null, 2) : '{\n  "score": "features.SCORE"\n}')}</textarea>
            <label class="poll-label">Condition (Python expression)</label>
            <input class="detail-editable-input eval-input" data-eval="eval_condition" value="${esc(s.eval_condition || "")}" placeholder="e.g. score > 0.55">
            <label class="poll-label">Success Message</label>
            <input class="detail-editable-input eval-input" data-eval="success_message" value="${esc(s.success_message || "")}" placeholder="Scores above threshold">
            <label class="poll-label">Failure Message</label>
            <input class="detail-editable-input eval-input" data-eval="failure_message" value="${esc(s.failure_message || "")}" placeholder="Scores below threshold">
        </div>`;
    }

    function buildRetryFields(r) {
        const retryOn = (r && r.retry_on) || (r && r.on) || ["timeout", "connection", "5xx"];
        const opts = ["timeout", "connection", "5xx", "4xx"];
        return `<div class="retry-param">
            <label class="poll-label">Max Attempts</label>
            <input type="number" class="detail-editable-input poll-input" data-retry="max_attempts" value="${(r && r.max_attempts) || 3}" min="1" max="20">
            <label class="poll-label">Delay Between Retries (seconds)</label>
            <input type="number" class="detail-editable-input poll-input" data-retry="delay" value="${(r && r.delay) || 5}" min="0">
            <label class="poll-label">Retry On</label>
            <div class="retry-checks">${opts.map(o => `<label class="retry-check"><input type="checkbox" data-retry-on="${o}" ${retryOn.includes(o) ? "checked" : ""}> ${o}</label>`).join("")}</div>
        </div>`;
    }

    function readonlyRow(label, value) {
        return `<div class="detail-row"><div class="detail-label">${esc(label)}</div>
            <div class="detail-value readonly-value" data-raw-value="${esc(String(value))}">${esc(String(value))}</div></div>`;
    }

    function attachFloatingTooltip(control) {
        let tooltip = null;

        const hide = () => {
            if (tooltip) {
                tooltip.remove();
                tooltip = null;
            }
        };

        const show = () => {
            hide();
            tooltip = document.createElement("div");
            tooltip.className = "response-floating-tooltip";
            tooltip.textContent = control.dataset.tooltip || control.title || "";
            document.body.appendChild(tooltip);

            const rect = control.getBoundingClientRect();
            const gap = 8;
            const tooltipRect = tooltip.getBoundingClientRect();
            const left = Math.min(
                Math.max(gap, rect.left + (rect.width - tooltipRect.width) / 2),
                window.innerWidth - tooltipRect.width - gap
            );
            const below = rect.bottom + gap;
            const top = below + tooltipRect.height <= window.innerHeight
                ? below
                : rect.top - tooltipRect.height - gap;
            tooltip.style.left = `${left}px`;
            tooltip.style.top = `${Math.max(gap, top)}px`;
            requestAnimationFrame(() => tooltip && tooltip.classList.add("visible"));
        };

        control._refreshTooltip = show;
        control.addEventListener("mouseenter", show);
        control.addEventListener("mouseleave", hide);
        control.addEventListener("focus", show);
        control.addEventListener("blur", hide);
    }

    // Shared bounded value renderer. The raw value is retained on the wrapper;
    // the preview is presentation-only and is never used for copy or expansion.
    function renderBoundedValue(value, options = {}) {
        const rawValue = value === undefined || value === null ? "" : String(value);
        const label = options.label || "value";
        const className = options.className || "bounded-value";
        const expandable = !options.truncate && (rawValue.length > 240 || rawValue.split("\\n").length > 8);
        const wrapper = document.createElement("div");
        wrapper.className = `${className} bounded-value-wrapper${expandable ? " is-expandable" : ""}`;
        wrapper.dataset.rawValue = rawValue;

        const region = document.createElement("div");
        region.className = "bounded-value-region";
        region.textContent = rawValue;
        region.setAttribute("aria-label", `${label} content`);
        wrapper.appendChild(region);

        const actions = document.createElement("div");
        actions.className = "bounded-value-actions";
        const isResponseControl = className.includes("response-value");
        const copyButton = document.createElement("button");
        copyButton.type = "button";
        copyButton.className = "value-copy btn btn-ghost btn-sm";
        copyButton.setAttribute("aria-label", `Copy ${label}`);
        copyButton.setAttribute("data-tooltip", "Copy");
        if (!isResponseControl) copyButton.title = "Copy";
        copyButton.innerHTML = '<span class="copy-icon" aria-hidden="true"></span>';
        if (isResponseControl) attachFloatingTooltip(copyButton);
        const feedback = document.createElement("span");
        feedback.className = "value-copy-feedback";
        feedback.setAttribute("role", "status");
        feedback.setAttribute("aria-live", "polite");

        let tooltipTimer;
        const showCopyTooltip = (text) => {
            copyButton.dataset.tooltip = text;
            if (!isResponseControl) copyButton.title = text;
            copyButton.dataset.tooltipVisible = "true";
            if (copyButton._refreshTooltip) copyButton._refreshTooltip();
            clearTimeout(tooltipTimer);
            tooltipTimer = setTimeout(() => {
                copyButton.dataset.tooltip = "Copy";
                if (!isResponseControl) copyButton.title = "Copy";
                delete copyButton.dataset.tooltipVisible;
            }, 1400);
        };

        copyButton.addEventListener("click", () => {
            const clipboard = navigator.clipboard;
            if (!clipboard || typeof clipboard.writeText !== "function") {
                feedback.textContent = "Clipboard unavailable";
                feedback.className = "value-copy-feedback error";
                showCopyTooltip("Copy failed");
                return;
            }
            Promise.resolve().then(() => clipboard.writeText(rawValue)).then(() => {
                feedback.textContent = "Copied";
                feedback.className = "value-copy-feedback success";
                showCopyTooltip("Copied");
            }).catch(() => {
                feedback.textContent = "Copy failed";
                feedback.className = "value-copy-feedback error";
                showCopyTooltip("Copy failed");
            });
        });
        actions.appendChild(copyButton);

        if (expandable) {
            const expandButton = document.createElement("button");
            expandButton.type = "button";
            expandButton.className = "value-expand btn btn-ghost btn-sm";
            expandButton.setAttribute("aria-label", `Expand ${label}`);
            expandButton.setAttribute("aria-expanded", "false");
            expandButton.setAttribute("data-tooltip", "Expand");
            if (!isResponseControl) expandButton.title = "Expand";
            expandButton.innerHTML = '<span class="expand-icon" aria-hidden="true"></span>';
            if (isResponseControl) attachFloatingTooltip(expandButton);
            expandButton.addEventListener("click", () => {
                const expanded = wrapper.classList.toggle("is-expanded");
                const action = expanded ? "Collapse" : "Expand";
                expandButton.setAttribute("aria-expanded", String(expanded));
                expandButton.setAttribute("aria-label", `${action} ${label}`);
                expandButton.setAttribute("data-tooltip", action);
                if (!isResponseControl) expandButton.title = action;
                if (expandButton._refreshTooltip) expandButton._refreshTooltip();
            });
            actions.appendChild(expandButton);
        }
        actions.appendChild(feedback);
        wrapper.appendChild(actions);
        return wrapper;
    }

    function esc(str) { const d = document.createElement("div"); d.textContent = str; return d.innerHTML; }

    detailClose.addEventListener("click", () => detailOverlay.classList.add("hidden"));
    detailOverlay.addEventListener("click", (e) => {
        if (e.target === detailOverlay || e.target.classList.contains("step-detail-backdrop")) {
            detailOverlay.classList.add("hidden");
        }
    });

    // ── Save step changes from drawer ────────────────────────
    detailSave.addEventListener("click", async () => {
        if (!isCreatingStep && currentStepIndex < 0) return;
        const editables = detailBody.querySelectorAll(".detail-editable, .detail-editable-input, .detail-select");
        const updates = {};

        for (const el of editables) {
            const field = el.dataset.field;
            if (!field) continue;
            const raw = el.value.trim();

            if (!raw && !["method", "url", "delay", "continue_on_error", "instruction"].includes(field)) continue;

            if (["name", "url", "method", "instruction", "eval_condition", "success_message", "failure_message"].includes(field)) {
                updates[field] = raw;
            } else if (field === "delay") {
                updates[field] = parseInt(raw) || 0;
            } else if (field === "continue_on_error") {
                updates[field] = raw === "true";
            } else {
                try {
                    updates[field] = JSON.parse(raw);
                } catch (err) {
                    detailSaveStatus.textContent = `Invalid JSON in ${field}`;
                    detailSaveStatus.className = "detail-save-status error";
                    return;
                }
            }
        }

        if (!updates.name || !updates.name.trim()) {
            detailSaveStatus.textContent = "Step name is required";
            detailSaveStatus.className = "detail-save-status error";
            detailBody.querySelector('[data-field="name"]')?.focus();
            return;
        }
        updates.name = updates.name.trim();
        if (isCreatingStep && detailBody.querySelector('#new-step-type .rp-seg-btn.active')?.dataset.type === "manual") {
            updates.manual = true;
            if (!(updates.instruction || "").trim()) {
                detailSaveStatus.textContent = "Instruction is required for a manual step";
                detailSaveStatus.className = "detail-save-status error";
                detailBody.querySelector('[data-field="instruction"]')?.focus();
                return;
            }
        }

        // Collect list fields (print_keys, print_ref)
        detailBody.querySelectorAll(".list-field").forEach(container => {
            const field = container.dataset.listField;
            const items = [];
            container.querySelectorAll(".list-input").forEach(input => {
                const v = input.value.trim();
                if (v) items.push(v);
            });
            updates[field] = items.length ? items : null;
        });

        // Collect structured conditions in DOM order. Empty rows are invalid;
        // removing the section intentionally submits an explicit empty list.
        const conditionSection = detailBody.querySelector("#condition-section");
        const conditionParam = conditionSection && conditionSection.querySelector(".condition-param");
        if (conditionParam) {
            const conditions = [];
            for (const entry of conditionParam.querySelectorAll(".condition-entry")) {
                const condition = {};
                for (const field of ["step", "key_path", "operator", "expected_value"]) {
                    const input = entry.querySelector(`[data-condition="${field}"]`);
                    condition[field] = input.value;
                    const optionalExpected = ["is_null", "is_not_null"].includes(condition.operator);
                    if (!input.value.trim() && !(field === "expected_value" && optionalExpected)) {
                        detailSaveStatus.textContent = `Condition ${field.replace("_", " ")} is required`;
                        detailSaveStatus.className = "detail-save-status error";
                        input.focus();
                        return;
                    }
                }
                conditions.push(condition);
            }
            updates.condition = conditions;
        } else if (conditionSection) {
            updates.condition = [];
        }

        // Collect polling
        const pollingParam = detailBody.querySelector(".polling-param");
        if (pollingParam) {
            const keyPath = pollingParam.querySelector('[data-poll="key_path"]').value.trim();
            const evRaw = pollingParam.querySelector('[data-poll="expected_values"]').value.trim();
            const interval = parseInt(pollingParam.querySelector('[data-poll="interval"]').value) || 10;
            const maxTimeout = parseInt(pollingParam.querySelector('[data-poll="max_timeout"]').value) || 120;
            const polling = { interval, max_timeout: maxTimeout };
            if (keyPath) {
                polling.key_path = keyPath;
                polling.expected_values = evRaw ? evRaw.split(",").map(s => s.trim()).filter(Boolean) : [];
            }
            updates.polling = polling;
        } else if (detailBody.querySelector("#polling-section .polling-empty")) {
            updates.polling = null;
        }

        // Collect eval fields
        const evalParam = detailBody.querySelector(".eval-param");
        if (evalParam) {
            const ekRaw = evalParam.querySelector('[data-eval="eval_keys"]').value.trim();
            try {
                updates.eval_keys = JSON.parse(ekRaw);
            } catch (err) {
                detailSaveStatus.textContent = "Invalid JSON in Eval Keys";
                detailSaveStatus.className = "detail-save-status error";
                return;
            }
            updates.eval_condition = evalParam.querySelector('[data-eval="eval_condition"]').value.trim();
            updates.success_message = evalParam.querySelector('[data-eval="success_message"]').value.trim();
            updates.failure_message = evalParam.querySelector('[data-eval="failure_message"]').value.trim();
        } else if (detailBody.querySelector("#eval-section .polling-empty")) {
            updates.eval_keys = null;
            updates.eval_condition = null;
            updates.success_message = null;
            updates.failure_message = null;
        }

        // Collect retry fields
        const retryParam = detailBody.querySelector(".retry-param");
        if (retryParam) {
            const maxAttempts = parseInt(retryParam.querySelector('[data-retry="max_attempts"]').value) || 3;
            const retryDelay = parseInt(retryParam.querySelector('[data-retry="delay"]').value) || 5;
            const retryOn = [];
            retryParam.querySelectorAll('[data-retry-on]').forEach(cb => {
                if (cb.checked) retryOn.push(cb.dataset.retryOn);
            });
            updates.retry = { max_attempts: maxAttempts, delay: retryDelay, on: retryOn };
        } else if (detailBody.querySelector("#retry-section .polling-empty")) {
            updates.retry = false;
        }

        detailSaveStatus.textContent = "Saving...";
        detailSaveStatus.className = "detail-save-status";

        try {
            const endpoint = isCreatingStep
                ? `/api/flow/${FLOW_PATH}/step`
                : `/api/flow/${FLOW_PATH}/step/${currentStepIndex}`;
            const body = isCreatingStep ? { step: updates, position: insertPosition } : { updates };
            const res = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (data.success) {
                detailSaveStatus.textContent = isCreatingStep ? "✓ Step added" : "✓ Saved";
                detailSaveStatus.className = "detail-save-status success";
                setTimeout(() => location.reload(), 1200);
            } else {
                detailSaveStatus.textContent = "✗ " + (data.error || "Failed");
                detailSaveStatus.className = "detail-save-status error";
            }
        } catch (err) {
            detailSaveStatus.textContent = "✗ " + err.message;
            detailSaveStatus.className = "detail-save-status error";
        }
    });

    detailDelete.addEventListener("click", () => {
        if (isCreatingStep || currentStepIndex < 0) return;
        deleteConfirmStepName.textContent = steps[currentStepIndex].name;
        deleteConfirmModal.classList.remove("hidden");
        deleteConfirmOk.focus();
    });

    function closeDeleteConfirmation() {
        deleteConfirmModal.classList.add("hidden");
    }

    deleteConfirmClose.addEventListener("click", closeDeleteConfirmation);
    deleteConfirmCancel.addEventListener("click", closeDeleteConfirmation);
    deleteConfirmModal.addEventListener("click", (event) => {
        if (event.target === deleteConfirmModal) closeDeleteConfirmation();
    });

    deleteConfirmOk.addEventListener("click", async () => {
        if (isCreatingStep || currentStepIndex < 0) return;
        closeDeleteConfirmation();
        detailDelete.disabled = true;
        deleteConfirmOk.disabled = true;
        detailSaveStatus.textContent = "Deleting...";
        detailSaveStatus.className = "detail-save-status";
        try {
            const res = await fetch(`/api/flow/${FLOW_PATH}/step/${currentStepIndex}`, { method: "DELETE" });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || "Failed to delete step");
            detailSaveStatus.textContent = "✓ Deleted";
            detailSaveStatus.className = "detail-save-status success";
            setTimeout(() => location.reload(), 700);
        } catch (err) {
            detailDelete.disabled = false;
            deleteConfirmOk.disabled = false;
            detailSaveStatus.textContent = "✗ " + err.message;
            detailSaveStatus.className = "detail-save-status error";
        }
    });

    // ── Run chain ────────────────────────────────────────────
    let pollTimer = null;
    let currentRunId = null;

    runBtn.addEventListener("click", () => {
        if (selectedSteps.size) openRunInputs();
        else startRun({});
    });

    async function startRun(extraBody) {
        runBtn.disabled = true;
        runStatus.textContent = "Starting...";
        runStatus.className = "run-status-badge running";
        pauseBtn.classList.add("hidden");
        resumeBtn.classList.add("hidden");
        stopBtn.classList.add("hidden");

        stepBoxes.forEach(box => {
            box.className = box.className.replace(/\bstate-\w+/g, "");
            const ind = box.querySelector(".step-result-indicator"); if (ind) ind.remove();
            const sc = box.querySelector(".step-status-code"); if (sc) sc.remove();
            const row = box.parentElement;
            row.querySelectorAll(".side-connector, .eval-side-connector, .retry-side-connector").forEach(panel => panel.remove());
        });
        responsePanel.classList.add("hidden");
        responseList.innerHTML = "";
        currentResponseResults = [];

        try {
            const res = await fetch("/api/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ flow_path: FLOW_PATH, ...extraBody }),
            });
            const data = await res.json();
            if (data.error) {
                runStatus.textContent = `Error: ${data.error}`;
                runStatus.className = "run-status-badge error";
                runBtn.disabled = false;
                return;
            }
            currentRunId = data.run_id;
            pauseBtn.classList.remove("hidden");
            showStopButton();
            pollRunStatus(data.run_id);
        } catch (err) {
            runStatus.textContent = `Error: ${err.message}`;
            runStatus.className = "run-status-badge error";
            runBtn.disabled = false;
        }
    }

    pauseBtn.addEventListener("click", async () => {
        if (!currentRunId) return;
        await fetch(`/api/run/${currentRunId}/pause`, { method: "POST" });
        pauseBtn.classList.add("hidden");
        resumeBtn.classList.remove("hidden");
        runStatus.textContent = "Paused";
        runStatus.className = "run-status-badge running";
    });

    resumeBtn.addEventListener("click", async () => {
        if (!currentRunId) return;
        await fetch(`/api/run/${currentRunId}/resume`, { method: "POST" });
        resumeBtn.classList.add("hidden");
        pauseBtn.classList.remove("hidden");
        runStatus.className = "run-status-badge running";
    });

    function showStopButton() {
        stopBtn.disabled = false;
        stopBtn.lastChild.textContent = " Stop";
        stopBtn.classList.remove("hidden");
    }
    // Stop confirmation popup (replaces the browser's native confirm box)
    const stopConfirmModal = document.getElementById("stop-confirm-modal");
    const stopConfirmOk = document.getElementById("stop-confirm-ok");
    function closeStopConfirm() { stopConfirmModal.classList.add("hidden"); }
    function stopRun() {
        if (!currentRunId || stopBtn.disabled) return;
        stopConfirmModal.classList.remove("hidden");
        stopConfirmOk.focus();
    }
    async function confirmStopRun() {
        closeStopConfirm();
        if (!currentRunId) return;
        stopBtn.disabled = true;
        stopBtn.lastChild.textContent = " Stopping...";
        runStatus.textContent = "Stopping...";
        runStatus.className = "run-status-badge running";
        try {
            const res = await fetch(`/api/run/${currentRunId}/stop`, { method: "POST" });
            if (!res.ok) throw new Error("run already finished");
        } catch (e) {
            showStopButton();   // the poll reports the final state
        }
    }
    stopConfirmOk.addEventListener("click", confirmStopRun);
    document.getElementById("stop-confirm-cancel").addEventListener("click", closeStopConfirm);
    document.getElementById("stop-confirm-close").addEventListener("click", closeStopConfirm);
    stopConfirmModal.addEventListener("click", (e) => { if (e.target === stopConfirmModal) closeStopConfirm(); });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && !stopConfirmModal.classList.contains("hidden")) {
            e.stopImmediatePropagation();
            closeStopConfirm();
        }
    }, true);
    stopBtn.addEventListener("click", stopRun);
    function pollRunStatus(runId) {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(async () => {
            try {
                const res = await fetch(`/api/run/${runId}`);
                const data = await res.json();
                updateStepStates(data, runId);

                if (data.status === "running") {
                    const done = data.results.length;

                    if (data.waiting_manual) {
                        // Show manual step overlay
                        runStatus.textContent = `Manual Step — waiting`;
                        runStatus.className = "run-status-badge running";
                        pauseBtn.classList.add("hidden");
                        resumeBtn.classList.add("hidden");
                        showManualOverlay(runId, data);
                    } else if (data.paused) {
                        hideManualOverlay();
                        runStatus.textContent = `Paused (${done}/${steps.length})`;
                        pauseBtn.classList.add("hidden");
                        resumeBtn.classList.remove("hidden");
                    } else {
                        hideManualOverlay();
                        runStatus.textContent = `Running ${done}/${steps.length}`;
                        pauseBtn.classList.remove("hidden");
                        resumeBtn.classList.add("hidden");
                    }
                    runStatus.className = "run-status-badge running";
                } else {
                    clearInterval(pollTimer); pollTimer = null; runBtn.disabled = false;
                    currentRunId = null;
                    pauseBtn.classList.add("hidden");
                    resumeBtn.classList.add("hidden");
                    stopBtn.classList.add("hidden");
                    closeStopConfirm();
                    hideManualOverlay();
                    const passed = data.results.filter(r => r.success).length;
                    const failed = data.results.filter(r => !r.success && !r.stopped).length;
                    if (data.status === "completed") {
                        runStatus.textContent = `✓ ${passed} passed, ${failed} failed`;
                        runStatus.className = "run-status-badge done";
                    } else if (data.status === "stopped") {
                        runStatus.textContent = `■ Stopped at ${data.results.length}/${steps.length}: ${passed} passed, ${failed} failed`;
                        runStatus.className = "run-status-badge stopped";
                    } else {
                        runStatus.textContent = data.error || "Error";
                        runStatus.className = "run-status-badge error";
                    }
                    showResponses(data.results);
                }
            } catch (err) {
                clearInterval(pollTimer); pollTimer = null; runBtn.disabled = false;
                currentRunId = null;
                pauseBtn.classList.add("hidden");
                resumeBtn.classList.add("hidden");
                stopBtn.classList.add("hidden");
                hideManualOverlay();
                runStatus.textContent = "Poll error";
                runStatus.className = "run-status-badge error";
            }
        }, 1000);
    }

    // ── Manual step overlay ──────────────────────────────────
    let manualOverlayEl = null;

    function showManualOverlay(runId, data) {
        if (manualOverlayEl) return; // already showing

        manualOverlayEl = document.createElement("div");
        manualOverlayEl.className = "manual-overlay";

        const card = document.createElement("div");
        card.className = "manual-card";

        const header = document.createElement("div");
        header.className = "manual-header";
        header.innerHTML = `<span class="manual-status-icon" aria-hidden="true"><span></span><span></span><span></span></span><span class="manual-title">Manual Step - ${esc(data.manual_step_name)}</span>`;
        card.appendChild(header);

        if (data.manual_instruction) {
            const instrBlock = document.createElement("div");
            instrBlock.className = "manual-instruction";
            const lines = data.manual_instruction.split("\n").filter(l => l.trim());
            lines.forEach(line => {
                const p = document.createElement("p");
                p.textContent = line;
                instrBlock.appendChild(p);
            });
            card.appendChild(instrBlock);
        }

        if (data.manual_print_ref && Object.keys(data.manual_print_ref).length) {
            const refBlock = document.createElement("div");
            refBlock.className = "manual-refs";
            for (const [k, v] of Object.entries(data.manual_print_ref)) {
                const row = document.createElement("div");
                row.className = "manual-ref-row";
                const key = document.createElement("div");
                key.className = "manual-ref-key";
                key.textContent = k;
                row.appendChild(key);
                row.appendChild(renderBoundedValue(v, { className: "manual-ref-val manual-ref-value", label: `reference ${k}`, truncate: true }));
                refBlock.appendChild(row);
            }
            card.appendChild(refBlock);
        }

        const btn = document.createElement("button");
        btn.className = "btn btn-primary manual-done-btn";
        btn.innerHTML = `<svg class="icon icon-sm" style="margin-right:0.4rem"><use href="#i-play"/></svg> Mark as Done & Continue`;
        btn.addEventListener("click", async () => {
            btn.disabled = true;
            btn.textContent = "Continuing...";
            try {
                await fetch(`/api/run/${runId}/manual-done`, { method: "POST" });
            } catch (e) { /* poll will pick up the state change */ }
        });
        card.appendChild(btn);
        const stopLink = document.createElement("button");
        stopLink.type = "button";
        stopLink.className = "btn btn-ghost manual-stop-btn";
        stopLink.textContent = "Stop run";
        stopLink.addEventListener("click", stopRun);
        card.appendChild(stopLink);
        manualOverlayEl.appendChild(card);
        document.querySelector(".main-content").appendChild(manualOverlayEl);
    }

    function hideManualOverlay() {
        if (manualOverlayEl) {
            manualOverlayEl.remove();
            manualOverlayEl = null;
        }
    }

    function statusClass(code) {
        if (code >= 200 && code < 300) return "2xx";
        if (code >= 300 && code < 400) return "3xx";
        if (code >= 400 && code < 500) return "4xx";
        if (code >= 500) return "5xx";
        return "err";
    }

    // One "key | value" row of a print_keys box; clicking the value copies it.
    function buildPkEntry(k, v) {
        const entry = document.createElement("div");
        entry.className = "pk-entry";
        entry.innerHTML = `<span class="pk-key-name" title="${esc(k)}">${esc(k)}</span><span class="pk-key-val" title="Copy value">${esc(String(v))}</span>`;
        const keyValue = entry.querySelector(".pk-key-val");
        const rawValue = String(v);
        keyValue.dataset.tooltip = rawValue;
        keyValue.title = rawValue;
        attachFloatingTooltip(keyValue);
        let copyTimer;
        keyValue.addEventListener("click", function() {
            const clipboard = navigator.clipboard;
            if (!clipboard || typeof clipboard.writeText !== "function") {
                keyValue.dataset.tooltip = "Copy failed";
                keyValue.title = "Copy failed";
                keyValue._refreshTooltip();
                return;
            }
            clipboard.writeText(rawValue).then(() => {
                keyValue.classList.add("pk-copied");
                keyValue.dataset.tooltip = "Copied";
                keyValue.title = "Copied";
                keyValue._refreshTooltip();
                clearTimeout(copyTimer);
                copyTimer = setTimeout(() => {
                    keyValue.classList.remove("pk-copied");
                    keyValue.dataset.tooltip = rawValue;
                    keyValue.title = rawValue;
                    if (keyValue._refreshTooltip) keyValue._refreshTooltip();
                }, 1400);
            }).catch(() => {
                keyValue.dataset.tooltip = "Copy failed";
                keyValue.title = "Copy failed";
                keyValue._refreshTooltip();
            });
        });
    return entry;
    }
    // Live print_keys of the step that is running right now (updated on every polling attempt).
    function syncLivePrintKeys(row, live) {
        let wrap = row.querySelector(".live-pk");
        const sig = JSON.stringify([live.attempt, live.status_code, live.printed_keys]);
        if (wrap && wrap.dataset.sig === sig) return;
        if (!wrap) {
            wrap = document.createElement("div");
            wrap.className = "side-connector live-pk";
            wrap.addEventListener("click", (e) => e.stopPropagation());
            const line = document.createElement("div");
            line.className = "pk-line";
            wrap.appendChild(line);
            const content = document.createElement("div");
            content.className = "side-content";
            content.appendChild(document.createElement("div"));
            wrap.appendChild(content);
            row.appendChild(wrap);
        }
        wrap.dataset.sig = sig;
        const pkBox = document.createElement("div");
        pkBox.className = "pk-box pk-box-live";
        const pkHeader = document.createElement("div");
        pkHeader.className = "pk-header";
        const code = live.status_code > 0 ? `HTTP ${live.status_code}` : "Value";
        pkHeader.innerHTML = `<span><span class="pk-live-dot"></span>Live · #${esc(String(live.attempt))}</span><span>${esc(code)}</span>`;
        pkBox.appendChild(pkHeader);
        for (const [k, v] of Object.entries(live.printed_keys || {})) {
            const entry = buildPkEntry(k, v);
            if (v === "—" || v === undefined || v === null) entry.classList.add("pk-pending");
            pkBox.appendChild(entry);
        }
        wrap.querySelector(".side-content").replaceChildren(pkBox);
    }
    function updateStepStates(data, runId) {
        const results = data.results;
        stepBoxes.forEach((box, i) => {
            box.className = box.className.replace(/\bstate-\w+/g, "");
            let el = box.querySelector(".step-result-indicator"); if (el) el.remove();
            el = box.querySelector(".step-status-code"); if (el) el.remove();

            const row = box.parentElement;
            row.querySelectorAll(".retry-side-connector").forEach(el => el.remove());
            row.parentElement.classList.remove("has-retry-stacked");
            // Side panels (printed keys / evaluation message) are kept between polls, but they must
            // be rebuilt when the step's data changes, e.g. after Retry, or dropped when the step has no result yet.
            const shown = i < results.length ? results[i] : null;
            const pkSig = shown && shown.printed_keys ? JSON.stringify(shown.printed_keys) : "";
            const evalSig = shown && shown.eval_message ? JSON.stringify(shown.eval_message) : "";
            row.querySelectorAll(".side-connector:not(.live-pk)").forEach(el => { if (el.dataset.sig !== pkSig) el.remove(); });
            row.querySelectorAll(".eval-side-connector").forEach(el => { if (el.dataset.sig !== evalSig) el.remove(); });
            const live = (data.status === "running" && data.live && data.live.step_index === i && i >= results.length) ? data.live : null;
            if (live) syncLivePrintKeys(row, live);
            else row.querySelectorAll(".live-pk").forEach(el => el.remove());

            if (i < results.length) {
                const r = results[i];
                if (r.stopped) { box.classList.add("state-skipped"); addIndicator(box, "■", "skipped"); }
                else if (r.skipped) { box.classList.add("state-skipped"); addIndicator(box, "—", "skipped"); }
                else if (r.success) { box.classList.add("state-passed"); addIndicator(box, "✓", "passed"); }
                else { box.classList.add("state-failed"); addIndicator(box, "✗", "failed"); }
                if (r.status_code && r.status_code > 0) {
                    const sc = document.createElement("span");
                    sc.className = `step-status-code status-${statusClass(r.status_code)}`;
                    sc.textContent = r.status_code;
                    box.appendChild(sc);
                }

                // Render evaluation messages to the left and printed keys to the right.
                // The two surfaces stay independent so each can be bounded and scrolled.
                const hasPK = r.printed_keys && Object.keys(r.printed_keys).some(k => {
                    const v = r.printed_keys[k];
                    return v !== undefined && v !== null && v !== "" && v !== "—" && v !== "null";
                });
                const hasMsg = r.eval_message;

                if (hasMsg && !row.querySelector(".eval-side-connector")) {
                    const evalWrap = document.createElement("div");
                    evalWrap.className = "eval-side-connector";
                    evalWrap.dataset.sig = evalSig;
                    evalWrap.addEventListener("click", (e) => e.stopPropagation());
                    const evalContent = document.createElement("div");
                    evalContent.className = "eval-side-content";
                    const evalBox = document.createElement("div");
                    evalBox.className = "eval-box";
                    const msg = document.createElement("div");
                    msg.className = `eval-msg eval-msg-${r.eval_message.type}`;
                    msg.textContent = r.eval_message.text;
                    evalBox.appendChild(msg);
                    evalContent.appendChild(evalBox);
                    const evalLine = document.createElement("div");
                    evalLine.className = "eval-line";
                    evalWrap.appendChild(evalContent);
                    evalWrap.appendChild(evalLine);
                    row.insertBefore(evalWrap, box);
                }

                if (hasPK && !row.querySelector(".side-connector")) {
                    const wrap = document.createElement("div");
                    wrap.className = "side-connector";
                    wrap.dataset.sig = pkSig;
                    wrap.addEventListener("click", (e) => e.stopPropagation());

                    const line = document.createElement("div");
                    line.className = "pk-line";
                    wrap.appendChild(line);

                    const content = document.createElement("div");
                    content.className = "side-content";
                    const pkBox = document.createElement("div");
                    pkBox.className = "pk-box";
                    const pkHeader = document.createElement("div");
                    pkHeader.className = "pk-header";
                    pkHeader.innerHTML = "<span>Parameters</span><span>Value</span>";
                    pkBox.appendChild(pkHeader);

                    for (const [k, v] of Object.entries(r.printed_keys)) {
                        if (v === undefined || v === null || v === "—") continue;
                        const entry = buildPkEntry(k, v);
                        pkBox.appendChild(entry);
                    }
                    content.appendChild(pkBox);
                    wrap.appendChild(content);
                    row.appendChild(wrap);
                }

                if (data.retryable && runId && i === data.failed_step_index) {
                    const stacked = !!row.querySelector(".side-connector");
                    row.appendChild(buildRetryConnector(runId, stacked));
                    // A stacked Retry sits under the card; make room so it does not cover the "Step N" label or the Add Step pill.
                    row.parentElement.classList.toggle("has-retry-stacked", stacked);
                }
            } else if (data.status === "running" && i === results.length) {
                if (data.waiting_manual) {
                    box.classList.add("state-manual");
                    addIndicator(box, "✋", "manual");
                } else {
                    box.classList.add("state-running");
                }
            }
        });
    }

    // ── Retry a failed stop-on-fail step ─────────────────────
    function buildRetryConnector(runId, stacked) {
        const wrap = document.createElement("div");
        wrap.className = "retry-side-connector" + (stacked ? " retry-stacked" : "");
        wrap.addEventListener("click", (e) => e.stopPropagation());

        const line = document.createElement("div");
        line.className = "retry-line";
        wrap.appendChild(line);

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "retry-btn";
        btn.title = "Retry this step and continue the chain with the existing context";
        btn.innerHTML = `<svg class="icon icon-sm" aria-hidden="true"><use href="#i-retry"/></svg><span>Retry</span>`;
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            btn.disabled = true;
            btn.classList.add("retrying");
            try {
                const res = await fetch(`/api/run/${runId}/retry`, { method: "POST" });
                const data = await res.json();
                if (!res.ok || data.error) throw new Error(data.error || "Retry failed");
                resumeTrackingRun(runId);
            } catch (err) {
                btn.disabled = false;
                btn.classList.remove("retrying");
                runStatus.textContent = `Retry error: ${err.message}`;
                runStatus.className = "run-status-badge error";
            }
        });
        wrap.appendChild(btn);
        return wrap;
    }

    function resumeTrackingRun(runId) {
        currentRunId = runId;
        runBtn.disabled = true;
        responsePanel.classList.add("hidden");
        runStatus.textContent = "Retrying...";
        runStatus.className = "run-status-badge running";
        pauseBtn.classList.remove("hidden");
        resumeBtn.classList.add("hidden");
        showStopButton();
        pollRunStatus(runId);
    }

    function addIndicator(box, text, cls) {
        const el = document.createElement("span");
        el.className = `step-result-indicator ${cls}`;
        el.textContent = text;
        box.appendChild(el);
    }

    // ── Response panel ───────────────────────────────────────
    function responseDisplayText(result) {
        return result.response_body || result.error || (result.manual ? "Manual step" : result.skipped ? "Skipped" : "—");
    }

    function responseDisplayTime(timestamp) {
        if (!timestamp) return "—";
        const date = new Date(timestamp);
        if (Number.isNaN(date.getTime())) return String(timestamp);
        return date.toLocaleString(undefined, {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            hour12: false,
        });
    }

    function responseExportRows(results) {
        return results.map(result => [
            result.step_name || "",
            result.status_code > 0 ? result.status_code : (result.skipped ? "SKIP" : "ERR"),
            responseDisplayTime(result.executed_at),
            result.duration_ms > 0 ? `${result.duration_ms}ms` : "—",
            responseDisplayText(result),
        ]);
    }

    function csvCell(value) {
        return `"${String(value ?? "").replace(/"/g, '""')}"`;
    }

    function safeDownloadName(extension) {
        const name = String(CHAIN_DATA.name || "api-chain-run")
            .trim()
            .replace(/[^a-z0-9._-]+/gi, "-")
            .replace(/^-+|-+$/g, "") || "api-chain-run";
        return `${name}-step-responses.${extension}`;
    }

    function downloadResponseFile(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 0);
    }

    function downloadResponsesCsv() {
        const rows = [["Step", "Status", "Executed At", "Duration", "Response"], ...responseExportRows(currentResponseResults)];
        const csv = rows.map(row => row.map(csvCell).join(",")).join("\r\n");
        downloadResponseFile(`\uFEFF${csv}`, safeDownloadName("csv"), "text/csv;charset=utf-8");
    }

    function showResponses(results) {
        currentResponseResults = Array.isArray(results) ? results : [];
        if (!currentResponseResults.length) return;
        responseList.innerHTML = "";
        const table = document.createElement("table");
        table.className = "response-table";
        table.innerHTML = `<thead><tr>
            <th class="col-step">Step</th>
            <th class="col-status">Status</th>
            <th class="col-executed">Executed At</th>
            <th class="col-time">Duration</th>
            <th>Response</th>
        </tr></thead>`;
        const tbody = document.createElement("tbody");
        results.forEach(r => {
            const sc = statusClass(r.status_code || -1);
            const tr = document.createElement("tr");
            const tdStep = document.createElement("td");
            tdStep.className = "col-step";
            tdStep.textContent = r.step_name;
            tdStep.title = r.step_name;

            const tdStatus = document.createElement("td");
            tdStatus.className = `col-status s-${sc}`;
            tdStatus.textContent = r.status_code > 0 ? r.status_code : (r.skipped ? "SKIP" : "ERR");

            const tdExecuted = document.createElement("td");
            tdExecuted.className = "col-executed";
            tdExecuted.textContent = responseDisplayTime(r.executed_at);
            tdExecuted.title = tdExecuted.textContent;

            const tdTime = document.createElement("td");
            tdTime.className = "col-time";
            tdTime.textContent = r.duration_ms > 0 ? r.duration_ms + "ms" : "—";

            const tdBody = document.createElement("td");
            tdBody.className = "col-body";
            const bodyText = responseDisplayText(r);
            tdBody.appendChild(renderBoundedValue(bodyText, { className: "response-value response-pre-wrap", label: "response" }));

            tr.appendChild(tdStep);
            tr.appendChild(tdStatus);
            tr.appendChild(tdExecuted);
            tr.appendChild(tdTime);
            tr.appendChild(tdBody);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        responseList.appendChild(table);
        responsePanel.classList.remove("hidden");
    }

    responseClose.addEventListener("click", () => responsePanel.classList.add("hidden"));
    responseDownloadCsv.addEventListener("click", downloadResponsesCsv);

    // ── Inline YAML Editor toggle ────────────────────────────
    const editToggleBtn = document.getElementById("edit-toggle-btn");
    const editorSaveBtn = document.getElementById("editor-save-btn");
    const editorCancelBtn = document.getElementById("editor-cancel-btn");
    const editorStatusEl = document.getElementById("editor-status");
    const flowViewSection = document.getElementById("flow-view-section");
    const editorSection = document.getElementById("editor-section");
    let editorMode = false;
    // ── Monaco Editor Setup ────────────────────────────
    let monacoEditor;
    const monacoContainer = document.getElementById("monaco-container");

    if (window.require) {
        require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
        require(['vs/editor/editor.main'], function() {
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark' || !document.documentElement.hasAttribute('data-theme');
            monacoEditor = monaco.editor.create(monacoContainer, {
                value: '',
                language: 'yaml',
                theme: isDark ? 'vs-dark' : 'vs',
                automaticLayout: true,
                fontSize: 13,
                fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', monospace",
                lineHeight: 20,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                padding: { top: 10 }
            });

            // Sync theme when data-theme attribute changes
            const observer = new MutationObserver(() => {
                const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
                monaco.editor.setTheme(isDark ? 'vs-dark' : 'vs');
            });
            observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
            window.addEventListener("keydown", (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === "s") {
                    if (editorMode) {
                        e.preventDefault();
                        editorSaveBtn.click();
                    }
                }
            });
        });
    }

    editToggleBtn.addEventListener("click", async () => {
        if (!editorMode) {
            try {
                const res = await fetch(`/api/flow/${FLOW_PATH}/raw`);
                const data = await res.json();
                if (monacoEditor) {
                  monacoEditor.setValue(data.content);
                }
            } catch (err) { return; }
            flowViewSection.classList.add("hidden");
            editorSection.classList.remove("hidden");
            editToggleBtn.classList.add("hidden");
            editorSaveBtn.classList.remove("hidden");
            editorCancelBtn.classList.remove("hidden");
            editorMode = true;
        }
    });

    editorCancelBtn.addEventListener("click", () => {
        editorSection.classList.add("hidden");
        flowViewSection.classList.remove("hidden");
        editToggleBtn.classList.remove("hidden");
        editorSaveBtn.classList.add("hidden");
        editorCancelBtn.classList.add("hidden");
        editorStatusEl.textContent = "";
        editorMode = false;
    });

    editorSaveBtn.addEventListener("click", async () => {
        if (!monacoEditor) return;
        editorStatusEl.textContent = "Saving...";
        editorStatusEl.className = "detail-save-status";
        try {
            const content = monacoEditor.getValue();
            const res = await fetch(`/api/flow/${FLOW_PATH}/save`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content }),
            });
            const data = await res.json();
            if (data.success) {
                editorStatusEl.textContent = "Saved";
                editorStatusEl.className = "detail-save-status success";
                setTimeout(() => location.reload(), 1000);
            } else {
                editorStatusEl.textContent = data.error || "Failed";
                editorStatusEl.className = "detail-save-status error";
            }
        } catch (err) {
            editorStatusEl.textContent = err.message;
            editorStatusEl.className = "detail-save-status error";
        }
    });

    // ── Init ─────────────────────────────────────────────────
    renderFlow();
    renderSidebarSteps();
})();
