/* flow-search.js — dashboard search (Drive-style) and collapsible sidebar folders */
(function () {
    const STORE_KEY = "acr-collapsed-folders";

    /* ── Sidebar folders: remember which ones are collapsed ── */
    const groups = Array.from(document.querySelectorAll("details.nav-group[data-folder]"));
    let collapsed;
    try { collapsed = new Set(JSON.parse(localStorage.getItem(STORE_KEY) || "[]")); }
    catch (e) { collapsed = new Set(); }
    groups.forEach((g) => { g.open = !collapsed.has(g.dataset.folder); });
    groups.forEach((g) => {
        g.addEventListener("toggle", () => {
            if (g.open) collapsed.delete(g.dataset.folder); else collapsed.add(g.dataset.folder);
            try { localStorage.setItem(STORE_KEY, JSON.stringify(Array.from(collapsed))); } catch (e) { /* ignore */ }
        });
    });

    /* ── Dashboard search ──
     * With an empty query the page shows the current folder (folder chips + its files).
     * With a query it searches every flow in every folder and shows matching files only. */
    const input = document.getElementById("flow-search");
    if (!input) return;
    const cards = Array.from(document.querySelectorAll(".flow-card[data-search]"));
    const countEl = document.getElementById("flow-count");
    const searchEmpty = document.getElementById("search-empty");
    const flowTree = document.getElementById("flow-tree");
    const initialCount = countEl ? countEl.textContent : "";

    const applyFilter = (raw) => {
        const tokens = raw.toLowerCase().split(/\s+/).filter(Boolean);
        const active = tokens.length > 0;
        document.body.classList.toggle("is-searching", active);
        cards.forEach((el) => {
            const hay = el.dataset.search || "";
            el.classList.toggle("is-filtered-out", active && !tokens.every((t) => hay.includes(t)));
        });
        const visible = cards.filter((el) => !el.classList.contains("is-filtered-out")).length;
        if (countEl) {
            countEl.textContent = active
                ? visible + " of " + cards.length + " chain" + (cards.length !== 1 ? "s" : "") + " match"
                : initialCount;
        }
        const none = active && visible === 0;
        if (searchEmpty) searchEmpty.classList.toggle("hidden", !none);
        if (flowTree) flowTree.classList.toggle("hidden", none);
    };

    input.addEventListener("input", () => applyFilter(input.value));
    input.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            input.value = "";
            applyFilter("");
            input.blur();
        } else if (e.key === "Enter") {
            const first = cards.find((el) => !el.classList.contains("is-filtered-out")
                && (document.body.classList.contains("is-searching") || !el.classList.contains("search-only")));
            if (first) first.click();
        }
    });
    document.addEventListener("keydown", (e) => {
        if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
        const t = e.target;
        if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
        e.preventDefault();
        input.focus();
        input.select();
    });
})();
