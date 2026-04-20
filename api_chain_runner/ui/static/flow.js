/* flow.js — Vertical flow, editable drawer, run execution, response display */
(function () {
    const canvas = document.getElementById("flow-canvas");
    const runBtn = document.getElementById("run-btn");
    const pauseBtn = document.getElementById("pause-btn");
    const resumeBtn = document.getElementById("resume-btn");
    const runStatus = document.getElementById("run-status");
    const detailOverlay = document.getElementById("step-detail");
    const detailName = document.getElementById("detail-name");
    const detailBody = document.getElementById("detail-body");
    const detailClose = document.getElementById("detail-close");
    const detailSave = document.getElementById("detail-save");
    const detailSaveStatus = document.getElementById("detail-save-status");
    const responsePanel = document.getElementById("response-panel");
    const responseList = document.getElementById("response-list");
    const responseClose = document.getElementById("response-close");

    const steps = CHAIN_DATA.steps;
    const stepBoxes = [];
    let currentStepIndex = -1;

    // ── Render VERTICAL flow ─────────────────────────────────
    function renderFlow() {
        canvas.innerHTML = "";
        stepBoxes.length = 0;

        steps.forEach((step, i) => {
            const node = document.createElement("div");
            node.className = "step-node";
            node.dataset.index = i;

            // Wrap box + print_keys in a row container
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

            node.addEventListener("click", (e) => { e.stopPropagation(); showDetail(step, i); });
            canvas.appendChild(node);
            stepBoxes.push(box);

            // Vertical arrow between steps
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

    // ── Detail drawer with editable fields ───────────────────
    function showDetail(step, index) {
        currentStepIndex = index;
        detailName.textContent = step.name;
        detailSaveStatus.textContent = "";
        detailSaveStatus.className = "detail-save-status";

        const isManual = step.manual;
        const curMethod = step.method.toUpperCase();
        let html = "";

        if (isManual) {
            // ── Manual step UI ──
            html += `<div class="detail-row"><div class="detail-label">Type</div><div class="detail-value">Manual Step</div></div>`;
            html += editableRow("instruction", "Instruction", step.instruction || "");
            html += buildListField("print_ref", "Print References", step.print_ref || [], "e.g. create-lead.leadId");
            html += numberRow("delay", "Delay (seconds)", step.delay || 0);
            html += dropdownRow("continue_on_error", "Continue on Error", step.continue_on_error);
        } else {
            // ── API step UI ──
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

    // Toggle section — add/remove structured block
    function buildToggleSection(id, label, data, buildFn) {
        const hasData = !!data;
        return `<div class="detail-row"><div class="detail-label">${esc(label)}</div>
            <div class="toggle-section" id="${id}-section">
                ${hasData ? buildFn(data) : `<div class="polling-empty">Not configured</div>`}
                <button class="btn btn-ghost btn-sm toggle-btn" data-target="${id}" style="margin-top:0.4rem">${hasData ? "Remove" : "+ Add"}</button>
            </div></div>`;
    }

    function wireToggleSections() {
        detailBody.querySelectorAll(".toggle-btn").forEach(btn => {
            btn.addEventListener("click", function() {
                const id = this.dataset.target;
                const section = document.getElementById(id + "-section");
                const hasParam = section.querySelector(".polling-param, .eval-param");
                if (hasParam) {
                    section.innerHTML = `<div class="polling-empty">Not configured</div><button class="btn btn-ghost btn-sm toggle-btn" data-target="${id}" style="margin-top:0.4rem">+ Add</button>`;
                } else {
                    const buildFn = id === "polling" ? buildPollingFields : id === "retry" ? buildRetryFields : buildEvalFields;
                    const defaults = id === "polling"
                        ? {key_path:"",expected_values:[],interval:10,max_timeout:120}
                        : id === "retry"
                        ? {max_attempts:3,delay:5,retry_on:["timeout","connection","5xx"]}
                        : {eval_keys:{},eval_condition:"",success_message:"",failure_message:""};
                    section.innerHTML = buildFn(defaults) + `<button class="btn btn-ghost btn-sm toggle-btn" data-target="${id}" style="margin-top:0.4rem">Remove</button>`;
                }
                wireToggleSections();
            });
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
            <div class="detail-value">${esc(String(value))}</div></div>`;
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
        if (currentStepIndex < 0) return;
        const editables = detailBody.querySelectorAll(".detail-editable, .detail-editable-input, .detail-select");
        const updates = {};

        for (const el of editables) {
            const field = el.dataset.field;
            if (!field) continue;
            const raw = el.value.trim();

            if (!raw && !["method", "url", "delay", "continue_on_error", "instruction"].includes(field)) continue;

            if (["url", "method", "instruction", "eval_condition", "success_message", "failure_message"].includes(field)) {
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
            const res = await fetch(`/api/flow/${FLOW_PATH}/step/${currentStepIndex}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ updates }),
            });
            const data = await res.json();
            if (data.success) {
                detailSaveStatus.textContent = "✓ Saved";
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

    // ── Run chain ────────────────────────────────────────────
    let pollTimer = null;
    let currentRunId = null;

    runBtn.addEventListener("click", async () => {
        runBtn.disabled = true;
        runStatus.textContent = "Starting...";
        runStatus.className = "run-status-badge running";
        pauseBtn.classList.add("hidden");
        resumeBtn.classList.add("hidden");

        stepBoxes.forEach(box => {
            box.className = box.className.replace(/\bstate-\w+/g, "");
            const ind = box.querySelector(".step-result-indicator"); if (ind) ind.remove();
            const sc = box.querySelector(".step-status-code"); if (sc) sc.remove();
        });
        responsePanel.classList.add("hidden");
        responseList.innerHTML = "";

        try {
            const res = await fetch("/api/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ flow_path: FLOW_PATH }),
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
            pollRunStatus(data.run_id);
        } catch (err) {
            runStatus.textContent = `Error: ${err.message}`;
            runStatus.className = "run-status-badge error";
            runBtn.disabled = false;
        }
    });

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

    function pollRunStatus(runId) {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(async () => {
            try {
                const res = await fetch(`/api/run/${runId}`);
                const data = await res.json();
                updateStepStates(data);

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
                    hideManualOverlay();
                    const passed = data.results.filter(r => r.success).length;
                    const failed = data.results.filter(r => !r.success).length;
                    if (data.status === "completed") {
                        runStatus.textContent = `✓ ${passed} passed, ${failed} failed`;
                        runStatus.className = "run-status-badge done";
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
        header.innerHTML = `<span class="manual-icon">✋</span><span class="manual-title">Manual Step — ${esc(data.manual_step_name)}</span>`;
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
                row.innerHTML = `<span class="manual-ref-key">${esc(k)}</span>`;
                const valSpan = document.createElement("span");
                valSpan.className = "manual-ref-val";
                valSpan.textContent = v;
                valSpan.title = "Click to copy";
                valSpan.addEventListener("click", () => {
                    navigator.clipboard.writeText(v).then(() => {
                        valSpan.classList.add("pk-copied");
                        setTimeout(() => valSpan.classList.remove("pk-copied"), 1200);
                    });
                });
                row.appendChild(valSpan);
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

    function updateStepStates(data) {
        const results = data.results;
        stepBoxes.forEach((box, i) => {
            box.className = box.className.replace(/\bstate-\w+/g, "");
            let el = box.querySelector(".step-result-indicator"); if (el) el.remove();
            el = box.querySelector(".step-status-code"); if (el) el.remove();

            const row = box.parentElement;

            if (i < results.length) {
                const r = results[i];
                if (r.skipped) { box.classList.add("state-skipped"); addIndicator(box, "—", "skipped"); }
                else if (r.success) { box.classList.add("state-passed"); addIndicator(box, "✓", "passed"); }
                else { box.classList.add("state-failed"); addIndicator(box, "✗", "failed"); }
                if (r.status_code && r.status_code > 0) {
                    const sc = document.createElement("span");
                    sc.className = `step-status-code status-${statusClass(r.status_code)}`;
                    sc.textContent = r.status_code;
                    box.appendChild(sc);
                }

                // Side connector — only add once
                if (!row.querySelector(".side-connector")) {
                    const hasPK = r.printed_keys && Object.keys(r.printed_keys).some(k => {
                        const v = r.printed_keys[k];
                        return v !== undefined && v !== null && v !== "" && v !== "—" && v !== "null";
                    });
                    const hasEval = r.eval_result && Object.keys(r.eval_result).length;
                    const hasMsg = r.eval_message;

                    if (hasPK || hasEval || hasMsg) {
                        const wrap = document.createElement("div");
                        wrap.className = "side-connector";
                        wrap.addEventListener("click", (e) => e.stopPropagation());

                        const line = document.createElement("div");
                        line.className = "pk-line";
                        wrap.appendChild(line);

                        const content = document.createElement("div");
                        content.className = "side-content";

                        // Print keys box
                        if (hasPK) {
                            const pkBox = document.createElement("div");
                            pkBox.className = "pk-box";
                            for (const [k, v] of Object.entries(r.printed_keys)) {
                                if (v === undefined || v === null || v === "—") continue;
                                const entry = document.createElement("div");
                                entry.className = "pk-entry";
                                const displayKey = k.length > 30 ? "..." + k.slice(-27) : k;
                                entry.innerHTML = `<span class="pk-key-name" title="${esc(k)}">${esc(displayKey)}</span><span class="pk-key-val" title="${esc(v)} — click to copy">${esc(v)}</span>`;
                                entry.querySelector(".pk-key-val").addEventListener("click", function() {
                                    navigator.clipboard.writeText(v).then(() => {
                                        this.classList.add("pk-copied");
                                        setTimeout(() => this.classList.remove("pk-copied"), 1200);
                                    });
                                });
                                pkBox.appendChild(entry);
                            }
                            content.appendChild(pkBox);
                        }

                        // Eval box (separate from print keys)
                        if (hasEval || hasMsg) {
                            const evalBox = document.createElement("div");
                            evalBox.className = "eval-box";
                            if (hasEval) {
                                for (const [k, v] of Object.entries(r.eval_result)) {
                                    const entry = document.createElement("div");
                                    entry.className = "eval-entry";
                                    entry.innerHTML = `<span class="eval-key">${esc(k)}</span><span class="eval-val">${esc(v)}</span>`;
                                    evalBox.appendChild(entry);
                                }
                            }
                            if (hasMsg) {
                                const msg = document.createElement("div");
                                msg.className = `eval-msg eval-msg-${r.eval_message.type}`;
                                msg.textContent = r.eval_message.text;
                                evalBox.appendChild(msg);
                            }
                            content.appendChild(evalBox);
                        }

                        wrap.appendChild(content);
                        row.appendChild(wrap);
                    }
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

    function addIndicator(box, text, cls) {
        const el = document.createElement("span");
        el.className = `step-result-indicator ${cls}`;
        el.textContent = text;
        box.appendChild(el);
    }

    // ── Response panel ───────────────────────────────────────
    function showResponses(results) {
        if (!results || !results.length) return;
        responseList.innerHTML = "";
        const table = document.createElement("table");
        table.className = "response-table";
        table.innerHTML = `<thead><tr>
            <th class="col-step">Step</th>
            <th class="col-status">Status</th>
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

            const tdTime = document.createElement("td");
            tdTime.className = "col-time";
            tdTime.textContent = r.duration_ms > 0 ? r.duration_ms + "ms" : "—";

            const tdBody = document.createElement("td");
            tdBody.className = "col-body";
            const bodyText = r.response_body || r.error || (r.manual ? "Manual step" : r.skipped ? "Skipped" : "—");
            const preWrap = document.createElement("div");
            preWrap.className = "response-pre-wrap";
            const pre = document.createElement("pre");
            pre.textContent = bodyText;
            const copyIcon = document.createElement("span");
            copyIcon.className = "response-copy-icon";
            copyIcon.textContent = "⧉";
            copyIcon.title = "Copy response";
            copyIcon.addEventListener("click", () => {
                navigator.clipboard.writeText(bodyText).then(() => {
                    copyIcon.textContent = "✓";
                    setTimeout(() => { copyIcon.textContent = "⧉"; }, 1500);
                });
            });
            preWrap.appendChild(pre);
            preWrap.appendChild(copyIcon);
            tdBody.appendChild(preWrap);

            tr.appendChild(tdStep);
            tr.appendChild(tdStatus);
            tr.appendChild(tdTime);
            tr.appendChild(tdBody);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        responseList.appendChild(table);
        responsePanel.classList.remove("hidden");
    }

    responseClose.addEventListener("click", () => responsePanel.classList.add("hidden"));

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
})();
