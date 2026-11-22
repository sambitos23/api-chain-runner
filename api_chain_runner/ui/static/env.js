/* env.js — view and edit environment variables (.env) from the sidebar */
(function () {
    const btn = document.getElementById("env-btn");
    const modal = document.getElementById("env-modal");
    if (!btn || !modal) return;

    const listEl = document.getElementById("env-list");
    const searchEl = document.getElementById("env-search");
    const fileEl = document.getElementById("env-file");
    const revealBtn = document.getElementById("env-reveal");
    const addBtn = document.getElementById("env-add");
    const saveBtn = document.getElementById("env-save");
    const cancelBtn = document.getElementById("env-cancel");
    const closeBtn = document.getElementById("env-close");
    const statusEl = document.getElementById("env-status");
    const pathEl = document.getElementById("env-path");
    const countEl = document.getElementById("env-count");
    const badgeEl = document.getElementById("env-btn-count");

    const HEADERS = { "X-ACR-Request": "1" };
    const KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

    let rows = [];            // [{ id, key, value, shown }]
    let original = "";        // snapshot of key/value pairs as last loaded or saved
    let currentPath = null;
    let revealAll = false;
    let nextId = 1;
    let busy = false;

    const esc = (s) => { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; };
    const snapshot = () => JSON.stringify(rows.map(r => [r.key.trim(), r.value]));
    const isDirty = () => snapshot() !== original;

    function setStatus(text, kind) {
        statusEl.textContent = text || "";
        statusEl.className = "env-status" + (kind ? ` ${kind}` : "");
    }

    function setBadge(count) {
        if (!badgeEl) return;
        badgeEl.textContent = count > 0 ? count : "";
        badgeEl.classList.toggle("hidden", !(count > 0));
    }

    // Validation: bad names and duplicates block saving.
    function problems() {
        const counts = {};
        rows.forEach(r => { const k = r.key.trim(); if (k) counts[k] = (counts[k] || 0) + 1; });
        const map = new Map();
        rows.forEach(r => {
            const k = r.key.trim();
            if (!k) map.set(r.id, "Enter a name");
            else if (!KEY_RE.test(k)) map.set(r.id, "Use letters, digits and _ (not starting with a digit)");
            else if (counts[k] > 1) map.set(r.id, "Duplicate name");
            else if (/[\r\n]/.test(r.value)) map.set(r.id, "Values cannot contain line breaks");
        });
        return map;
    }

    function refreshState() {
        const bad = problems();
        listEl.querySelectorAll(".env-row").forEach(el => {
            const msg = bad.get(Number(el.dataset.id));
            el.classList.toggle("is-invalid", !!msg);
            const keyInput = el.querySelector(".env-key");
            keyInput.title = msg || "";
            el.querySelector(".env-error").textContent = msg || "";
        });
        const dirty = isDirty();
        saveBtn.disabled = busy || !dirty || bad.size > 0;
        countEl.textContent = `${rows.length} variable${rows.length === 1 ? "" : "s"}`;
        if (!busy) {
            if (bad.size && dirty) setStatus("Fix the highlighted rows to save", "warn");
            else if (dirty) setStatus("Unsaved changes", "warn");
            else if (!statusEl.classList.contains("ok")) setStatus("");
        }
        applyFilter();
    }

    function applyFilter() {
        const q = searchEl.value.trim().toLowerCase();
        let visible = 0;
        listEl.querySelectorAll(".env-row").forEach(el => {
            const row = rows.find(r => r.id === Number(el.dataset.id));
            const show = !q || (row && row.key.toLowerCase().includes(q));
            el.classList.toggle("hidden", !show);
            if (show) visible++;
        });
        const noMatch = listEl.querySelector(".env-nomatch");
        if (noMatch) noMatch.classList.toggle("hidden", !(q && rows.length && visible === 0));
    }

    function renderRow(r) {
        const el = document.createElement("div");
        el.className = "env-row";
        el.dataset.id = r.id;
        el.innerHTML = `
            <input class="env-key" type="text" placeholder="VARIABLE_NAME" autocomplete="off" spellcheck="false" aria-label="Variable name">
            <div class="env-valwrap">
                <input class="env-val" placeholder="value" autocomplete="off" spellcheck="false" aria-label="Variable value" data-lpignore="true">
                <button type="button" class="rp-icon-btn env-eye" title="Show / hide value" aria-label="Show or hide value"><svg class="icon icon-sm"><use href="#i-eye"/></svg></button>
                <button type="button" class="rp-icon-btn env-copy" title="Copy value" aria-label="Copy value"><svg class="icon icon-sm"><use href="#i-copy"/></svg></button>
            </div>
            <button type="button" class="rp-icon-btn env-del" title="Remove variable" aria-label="Remove variable"><svg class="icon icon-sm"><use href="#i-trash"/></svg></button>
            <div class="env-error" role="alert"></div>`;
        const key = el.querySelector(".env-key");
        const val = el.querySelector(".env-val");
        const eye = el.querySelector(".env-eye");
        const copy = el.querySelector(".env-copy");
        key.value = r.key;
        val.value = r.value;

        const paintEye = () => {
            const show = r.shown || revealAll;
            val.type = show ? "text" : "password";
            eye.querySelector("use").setAttribute("href", show ? "#i-eye-off" : "#i-eye");
        };
        paintEye();
        el._paintEye = paintEye;

        key.addEventListener("input", () => { r.key = key.value; refreshState(); });
        val.addEventListener("input", () => { r.value = val.value; refreshState(); });
        eye.addEventListener("click", () => { r.shown = !r.shown; paintEye(); });
        copy.addEventListener("click", async () => {
            try {
                await navigator.clipboard.writeText(r.value);
                copy.classList.add("is-done");
                copy.querySelector("use").setAttribute("href", "#i-check");
                setTimeout(() => { copy.classList.remove("is-done"); copy.querySelector("use").setAttribute("href", "#i-copy"); }, 1200);
            } catch (e) { setStatus("Couldn't copy to the clipboard", "warn"); }
        });
        el.querySelector(".env-del").addEventListener("click", () => {
            rows = rows.filter(x => x.id !== r.id);
            el.classList.add("is-leaving");
            setTimeout(() => { el.remove(); render(false); refreshState(); }, 120);
        });
        return el;
    }

    function render(rebuild = true) {
        if (rebuild || !listEl.querySelector(".env-row")) {
            listEl.innerHTML = "";
            rows.forEach(r => listEl.appendChild(renderRow(r)));
        }
        let empty = listEl.querySelector(".env-empty");
        let noMatch = listEl.querySelector(".env-nomatch");
        if (!empty) {
            empty = document.createElement("div");
            empty.className = "env-empty hidden";
            empty.innerHTML = `<svg class="icon icon-xl"><use href="#i-key"/></svg><div class="env-empty-title">No variables yet</div><div class="env-empty-hint">Add one to use it as <code>\${ENV:NAME}</code> in your flows.</div>`;
            listEl.appendChild(empty);
        }
        if (!noMatch) {
            noMatch = document.createElement("div");
            noMatch.className = "env-nomatch hidden";
            noMatch.textContent = "No variables match your filter.";
            listEl.appendChild(noMatch);
        }
        empty.classList.toggle("hidden", rows.length > 0);
    }

    async function load(path) {
        busy = true;
        setStatus("Loading…");
        try {
            const url = "/api/env" + (path ? `?path=${encodeURIComponent(path)}` : "");
            const res = await fetch(url, { headers: HEADERS });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Could not load variables");
            currentPath = data.path;
            pathEl.textContent = data.path + (data.exists ? "" : " (will be created)");
            rows = data.entries.map(e => ({ id: nextId++, key: e.key, value: e.value, shown: false }));
            original = snapshot();
            fileEl.innerHTML = data.files.map(f => `<option value="${esc(f.path)}"${f.path === data.path ? " selected" : ""}>${esc(f.path)}${f.exists ? "" : "  (not created)"}</option>`).join("");
            fileEl.classList.toggle("hidden", data.files.length < 2);
            render(true);
            setBadge(rows.length);
            busy = false;
            setStatus("");
            refreshState();
        } catch (err) {
            busy = false;
            setStatus(err.message, "bad");
        }
    }

    function confirmDiscard() {
        return !isDirty() || window.confirm("Discard your unsaved changes?");
    }

    function open() {
        searchEl.value = "";
        revealAll = false;
        revealBtn.querySelector("span").textContent = "Show values";
        revealBtn.querySelector("use").setAttribute("href", "#i-eye");
        modal.classList.remove("hidden");
        load(null).then(() => { (listEl.querySelector(".env-key") || addBtn).focus(); });
    }

    function close(force) {
        if (!force && !confirmDiscard()) return;
        modal.classList.add("hidden");
    }

    async function save() {
        if (saveBtn.disabled) return;
        busy = true;
        saveBtn.disabled = true;
        setStatus("Saving…");
        try {
            const res = await fetch("/api/env", {
                method: "POST",
                headers: { ...HEADERS, "Content-Type": "application/json" },
                body: JSON.stringify({ path: currentPath, entries: rows.map(r => ({ key: r.key.trim(), value: r.value })) }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Could not save");
            busy = false;
            await load(currentPath);
            setStatus("Saved. New runs use these values.", "ok");
            setTimeout(() => { if (statusEl.classList.contains("ok")) { statusEl.className = "env-status"; statusEl.textContent = ""; } }, 3500);
        } catch (err) {
            busy = false;
            setStatus(err.message, "bad");
            refreshState();
            setStatus(err.message, "bad"); // refreshState resets the status line, so set the error last
        }
    }

    btn.addEventListener("click", open);
    closeBtn.addEventListener("click", () => close(false));
    cancelBtn.addEventListener("click", () => close(false));
    modal.addEventListener("mousedown", (e) => { if (e.target === modal) close(false); });
    saveBtn.addEventListener("click", save);
    searchEl.addEventListener("input", applyFilter);
    fileEl.addEventListener("change", () => {
        if (!confirmDiscard()) { fileEl.value = currentPath; return; }
        load(fileEl.value);
    });

    addBtn.addEventListener("click", () => {
        searchEl.value = "";
        const r = { id: nextId++, key: "", value: "", shown: true };
        rows.push(r);
        const el = renderRow(r);
        const tail = listEl.querySelector(".env-empty");
        listEl.insertBefore(el, tail);
        render(false);
        refreshState();
        el.scrollIntoView({ block: "nearest" });
        el.querySelector(".env-key").focus();
    });

    revealBtn.addEventListener("click", () => {
        revealAll = !revealAll;
        revealBtn.querySelector("span").textContent = revealAll ? "Hide values" : "Show values";
        revealBtn.querySelector("use").setAttribute("href", revealAll ? "#i-eye-off" : "#i-eye");
        listEl.querySelectorAll(".env-row").forEach(el => el._paintEye && el._paintEye());
    });

    // Capture phase so Esc / Ctrl+S here never reach page-level handlers (e.g. clearing step selection).
    window.addEventListener("keydown", (e) => {
        if (modal.classList.contains("hidden")) return;
        if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); close(false); }
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); e.stopImmediatePropagation(); save(); }
    }, true);

    window.addEventListener("beforeunload", (e) => {
        if (!modal.classList.contains("hidden") && isDirty()) { e.preventDefault(); e.returnValue = ""; }
    });

    // Sidebar badge: how many variables exist (values are never requested for this).
    fetch("/api/env?summary=1", { headers: HEADERS }).then(r => r.ok ? r.json() : null).then(d => { if (d) setBadge(d.count); }).catch(() => {});
})();
