/* notice.js — long error messages become a compact warning button with a tooltip.
 *
 * Status elements (.detail-save-status, .run-status-badge) are watched. When one is
 * styled as an error and its text is long, the text is replaced by a "⚠ Label" button
 * so the toolbar layout stays intact. Hover or focus shows the full message, click pins
 * it (Esc or a click elsewhere closes it), and the popup has a Copy button. */
(function () {
    const SELECTOR = ".detail-save-status, .run-status-badge";
    const MAX_INLINE = 40;          // errors up to this many characters stay inline
    const elements = Array.from(document.querySelectorAll(SELECTOR));
    if (!elements.length) return;

    let busy = false;
    let pop = null, popBtn = null, pinned = false, hideTimer = null;

    const labelFor = (text) => {
        const head = text.split(":")[0].trim();
        return head && head.length <= 24 && head.length < text.length ? head : "Error";
    };

    /* ── Popup ── */
    function closePop() {
        clearTimeout(hideTimer);
        if (pop) { pop.remove(); pop = null; }
        if (popBtn) { popBtn.setAttribute("aria-expanded", "false"); popBtn = null; }
        pinned = false;
    }
    function scheduleHide() {
        if (pinned) return;
        clearTimeout(hideTimer);
        hideTimer = setTimeout(closePop, 160);
    }
    function openPop(btn, pin) {
        clearTimeout(hideTimer);
        if (pop && popBtn === btn) { if (pin) pinned = true; return; }
        closePop();
        pinned = !!pin;
        popBtn = btn;
        btn.setAttribute("aria-expanded", "true");
        const message = btn.dataset.message || "";

        pop = document.createElement("div");
        pop.className = "status-notice-pop";
        pop.setAttribute("role", "tooltip");
        const title = document.createElement("div");
        title.className = "status-notice-title";
        title.textContent = btn.dataset.label || "Error";
        const body = document.createElement("div");
        body.className = "status-notice-msg";
        body.textContent = message;
        const copy = document.createElement("button");
        copy.type = "button";
        copy.className = "status-notice-copy";
        copy.textContent = "Copy";
        copy.addEventListener("click", () => {
            const done = (t) => { copy.textContent = t; setTimeout(() => { copy.textContent = "Copy"; }, 1200); };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(message).then(() => done("Copied"), () => done("Copy failed"));
            } else done("Copy failed");
        });
        const head = document.createElement("div");
        head.className = "status-notice-head";
        head.append(title, copy);
        pop.append(head, body);
        pop.addEventListener("mouseenter", () => clearTimeout(hideTimer));
        pop.addEventListener("mouseleave", scheduleHide);
        document.body.appendChild(pop);

        const gap = 8;
        const r = btn.getBoundingClientRect();
        const w = pop.getBoundingClientRect().width;
        const left = Math.min(Math.max(gap, r.right - w), window.innerWidth - w - gap);
        let top = r.bottom + gap;
        const h = pop.getBoundingClientRect().height;
        if (top + h > window.innerHeight - gap) top = Math.max(gap, r.top - h - gap);
        pop.style.left = left + "px";
        pop.style.top = top + "px";
        requestAnimationFrame(() => pop && pop.classList.add("visible"));
    }

    document.addEventListener("mousedown", (e) => {
        if (!pop) return;
        if (pop.contains(e.target) || (popBtn && popBtn.contains(e.target))) return;
        closePop();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && pop) closePop(); });

    /* ── Collapse / expand a status element ── */
    function makeButton(el, message) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "status-notice-btn";
        btn.dataset.message = message;
        btn.dataset.label = labelFor(message);
        btn.setAttribute("aria-label", "Show error details");
        btn.setAttribute("aria-expanded", "false");
        btn.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#i-alert"/></svg><span></span>';
        btn.lastChild.textContent = btn.dataset.label;
        btn.addEventListener("mouseenter", () => openPop(btn, false));
        btn.addEventListener("mouseleave", scheduleHide);
        btn.addEventListener("focus", () => openPop(btn, false));
        btn.addEventListener("blur", scheduleHide);
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            if (pop && popBtn === btn && pinned) closePop(); else openPop(btn, true);
        });
        return btn;
    }

    function enhance(el) {
        const existing = el.querySelector(":scope > .status-notice-btn");
        const isError = el.classList.contains("error");
        busy = true;
        try {
            if (existing) {
                if (isError) return;                       // already collapsed
                if (popBtn === existing) closePop();
                el.textContent = existing.dataset.message; // no longer an error: show the text again
                return;
            }
            const text = (el.textContent || "").trim();
            if (!isError || text.length <= MAX_INLINE) return;
            el.textContent = "";
            el.appendChild(makeButton(el, text));
        } finally {
            observer.takeRecords();                        // ignore our own DOM changes
            busy = false;
        }
    }

    const observer = new MutationObserver(() => { if (!busy) elements.forEach(enhance); });
    elements.forEach((el) => {
        observer.observe(el, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["class"] });
        enhance(el);
    });
})();
