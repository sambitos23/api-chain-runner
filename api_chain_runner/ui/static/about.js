/* about.js — About popup (features, creator, links) and the guided tour of the current page */
(function () {
    const btn = document.getElementById("about-btn");
    const modal = document.getElementById("about-modal");
    if (!btn || !modal) return;
    const closeBtn = document.getElementById("about-close");
    const tourBtn = document.getElementById("about-tour-btn");

    /* ---------- About popup ---------- */
    let lastFocus = null;
    const isOpen = () => !modal.classList.contains("hidden");
    function openAbout() {
        lastFocus = document.activeElement;
        modal.classList.remove("hidden");
        closeBtn.focus();
    }
    function closeAbout(restoreFocus) {
        modal.classList.add("hidden");
        if (restoreFocus !== false && lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
    }
    // First visit: the button glows and shows its tooltip until it is clicked once.
    const SEEN_KEY = "acr-help-seen";
    let seen = false;
    try { seen = localStorage.getItem(SEEN_KEY) === "1"; } catch (e) { seen = true; }
    if (!seen) btn.classList.add("is-new");
    function markSeen() {
        btn.classList.remove("is-new");
        try { localStorage.setItem(SEEN_KEY, "1"); } catch (e) { /* storage unavailable */ }
    }
    btn.addEventListener("click", () => { markSeen(); openAbout(); });
    closeBtn.addEventListener("click", () => closeAbout());
    modal.addEventListener("mousedown", (e) => { if (e.target === modal) closeAbout(); });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && isOpen() && !tour) { e.stopPropagation(); closeAbout(); }
    }, true);

    /* ---------- Tour content ----------
       sel: CSS selector of the element to spotlight.
       fallback: "center" shows the card in the middle when the element is hidden (for
       buttons that only appear while a run is going). Without it, a missing or hidden
       element makes the step skip itself. */
    const COMMON_TAIL = [
        { sel: "#theme-toggle", title: "Light and dark mode",
          text: "Switches between the dark and light theme. Your choice is remembered in this browser." },
        { sel: "#env-btn", title: "Environment variables",
          text: "Opens your .env file. Add, edit or delete variables here, then use them in any flow as ${ENV:NAME}. Values stay hidden until you press Show values." },
        { sel: "#about-btn", title: "Help button",
          text: "This ? button reopens the About popup. From there you can restart this tour, open the written guide, star the project on GitHub or message the creator on LinkedIn." },
    ];

    const TOURS = {
        dashboard: [
            { sel: ".breadcrumb", title: "Where you are",
              text: "Shows the folder you are browsing. Click a parent folder here to go back up." },
            { sel: "#create-flow-btn", title: "New Flow",
              text: "Creates a new YAML flow. Give it a name, optionally a folder (for example partner/bharatpe), and list the first steps with their HTTP methods. You can fill in URLs and payloads afterwards." },
            { sel: "#flow-search", title: "Search",
              text: "Finds a flow in any folder as you type. Press / to jump here, Enter to open the first match and Esc to clear." },
            { sel: "#folder-section", title: "Folders",
              text: "Each tile is a sub-folder of the current folder. Click one to open it. The number shows how many flows it holds." },
            { sel: ".flow-card:not(.search-only)", title: "Flow cards",
              text: "One card per YAML flow with its step count. Click a card to open the flow, see it as a chart and run it. A Docs chip appears when the flow has documentation." },
            { sel: "#nav-tree", title: "Folder tree",
              text: "The same folders and flows as a tree. Click a folder arrow to collapse or expand it, or click a flow to open it directly." },
        ].concat(COMMON_TAIL),

        flow: [
            { sel: "#edit-toggle-btn", title: "Edit YAML",
              text: "Switches the chart to a code editor for the whole YAML file. Save writes it back to disk, and Cancel returns to the chart without saving." },
            { sel: "#run-btn", title: "Run Chain",
              text: "Runs the flow from the first step. Each step lights up green, orange or red as it finishes. If you Ctrl/Cmd+click some steps first, this button runs only those." },
            { sel: ".info-chip-hint", title: "Run only some steps",
              text: "Ctrl/Cmd+click step cards to select them. A popup then asks for the payload, query and file values for those steps. Esc or Clear selection removes the selection." },
            { sel: "#pause-btn", fallback: "center", title: "Pause, Resume and Stop",
              text: "These appear while a run is going. Pause holds the run before the next step, Resume continues it, and Stop ends it where it is and shows a report of everything that ran." },
            { sel: ".step-box", title: "Step cards",
              text: "Each card is one API call with its method and URL. The border colour shows the result of the last run. Click a card to open its details, which the next steps show." },
            { group: "drawer", sel: ".detail-body", title: "Step details",
              text: "Everything about this step in one place: name, method, URL and the sections below. Scroll the drawer to see them all." },
            { group: "drawer", sel: "#sec-query", title: "Query params",
              text: "Query parameters are stored in the URL after the ?. Add them as key and value rows and the URL above updates itself, or type them in the URL. Use ${step.key} to reuse a value from an earlier response." },
            { group: "drawer", sel: "#sec-request-data", title: "Headers and payload",
              text: "Headers is a JSON object sent with the request, for example an Authorization header using ${auth.token}. Payload is the JSON body. It appears as soon as the method is POST, PUT, PATCH or DELETE, and stays hidden for GET. Unique fields and Files sit below it." },
            { group: "drawer", sel: "#sec-print", title: "Print keys",
              text: "List the response keys you want to see, such as leadId or data.status. Their values show beside the step after it runs, and refresh live while the step is polling. Press + Add for each key." },
            { group: "drawer", sel: "#sec-condition", title: "Conditions",
              text: "Run this step only when an earlier step's response matches. Pick the source step, a key path, an operator such as Equals or Contains, and the expected value. With several conditions all must match, otherwise the step is skipped." },
            { group: "drawer", sel: "#sec-polling", title: "Polling",
              text: "Repeat the call until the value at key path equals one of the expected values. Interval is the seconds between tries and max timeout is how long to wait before the step fails. Press + Add to turn polling on." },
            { group: "drawer", sel: "#detail-save", title: "Save Changes",
              text: "Writes your edits for this step back to the YAML file. The status text next to it confirms the save or explains an error." },
            { group: "drawer", sel: "#detail-delete", title: "Delete step",
              text: "Removes the step from the YAML after a confirmation popup. This cannot be undone." },
            { sel: ".step-box", title: "Add a step",
              text: "Hover a card and an Add Step pill appears under it. It inserts a new step right after that card. Choose API request, or Manual step for a point where a person has to confirm before the run continues." },
            { sel: ".step-box", title: "Retry and printed keys",
              text: "A failed step set to stop on failure gets a Retry button that re-runs it and carries on with the data collected so far. Keys listed in print_keys show beside the step, and update live while it is polling." },
            { sel: "#sidebar-steps", title: "Steps list",
              text: "Every step of this flow with its method. Click one to open the request panel, which the next steps show." },
            { group: "request", sel: ".rp-urlbar", title: "Method, URL and Send",
              text: "Pick the method, edit the URL and press Send (or Ctrl/Cmd+Enter) to fire only this one request. The YAML file is never changed by this panel." },
            { group: "request", sel: ".rp-request .rp-tabs", title: "Params, Headers and Body",
              text: "Edit query params and headers as rows. The Body tab supports None, JSON, Form-data (with file uploads) and x-www-form-urlencoded." },
            { group: "request", sel: "#req-curl", title: "Copy cURL",
              text: "Copies this request as a cURL command you can paste into a terminal." },
            { group: "request", sel: "#req-edit-step", title: "Edit step",
              text: "Closes this panel and opens the step in the edit drawer, where changes can be saved to the YAML." },
            { group: "request", sel: ".rp-response", title: "Response",
              text: "Shows the status, time, size, highlighted JSON body and headers of the reply. Wrap toggles long lines and Copy copies the body." },
            { sel: "#response-panel", fallback: "center", title: "Step responses",
              text: "After a run, this table lists each step's status code, time and response. Use the download button to save the results as a CSV file." },
            { sel: ".sidebar a[href$='/docs']", title: "Documentation",
              text: "Opens the documentation page for this flow: description, tags, notes, authors and a change log." },
        ].concat(COMMON_TAIL),

        docs: [
            { sel: "#edit-toggle", title: "Edit documentation",
              text: "Switches this page to edit mode. You can set the title, description, group, tags, rich-text notes, authors and a change log." },
            { sel: "#save-btn", fallback: "center", title: "Save",
              text: "Appears in edit mode and stores your changes next to the flow." },
            { sel: "#doc-view", title: "Documentation view",
              text: "What readers see: the summary of the flow and the notes you wrote." },
        ].concat(COMMON_TAIL),

        editor: [
            { sel: "#monaco-container", title: "YAML editor",
              text: "Edit the raw YAML of this flow here, with syntax highlighting." },
            { sel: "#editor-save", title: "Save",
              text: "Writes your changes to the flow file. If the YAML is invalid, a red message explains what is wrong, and hovering it shows the full text." },
        ].concat(COMMON_TAIL),
    };

    function pageKey() {
        if (document.getElementById("flow-canvas")) return "flow";
        if (document.getElementById("doc-view")) return "docs";
        if (document.getElementById("editor-save")) return "editor";
        return "dashboard";
    }

    /* ---------- Tour engine ---------- */
    let tour = null; // { steps, index, els }

    const PAD = 6;
    const GAP = 14;

    function visibleRect(el) {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 ? r : null;
    }

    /* A group opens a real panel for the steps that point inside it, and closes it again
       when the tour moves on. "needs" must exist for the group's steps to be included. */
    const click = (sel) => { const e = document.querySelector(sel); if (e) e.click(); };
    const GROUPS = {
        drawer: { needs: ".step-box", enter: () => click(".step-box"), leave: () => click("#detail-close") },
        request: { needs: "#sidebar-steps .nav-step", enter: () => click("#sidebar-steps .nav-step"), leave: () => click("#req-close") },
    };

    function buildSteps() {
        const out = [];
        (TOURS[pageKey()] || TOURS.dashboard).forEach((s) => {
            if (s.group) {
                if (document.querySelector(GROUPS[s.group].needs)) out.push(Object.assign({}, s, { centered: false }));
                return;
            }
            const el = document.querySelector(s.sel);
            if (visibleRect(el)) out.push(Object.assign({}, s, { centered: false }));
            else if (s.fallback === "center") out.push(Object.assign({}, s, { centered: true }));
        });
        return out;
    }

    function syncGroup(step) {
        const want = step.group || null;
        if (tour.group === want) return false;
        if (tour.group) GROUPS[tour.group].leave();
        tour.group = want;
        if (want) GROUPS[want].enter();
        return true;
    }

    function makeEl(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text) e.textContent = text;
        return e;
    }

    function startTour() {
        if (tour) return;
        const steps = buildSteps();
        if (!steps.length) return;
        const shield = makeEl("div", "tour-shield");
        const spot = makeEl("div", "tour-spot");
        const card = makeEl("div", "tour-card");
        card.setAttribute("role", "dialog");
        card.setAttribute("aria-live", "polite");
        card.setAttribute("aria-label", "Guided tour");
        const head = makeEl("div", "tour-card-head");
        const count = makeEl("span", "tour-count");
        const skip = makeEl("button", "tour-skip", "Skip tour");
        skip.type = "button";
        head.append(count, skip);
        const title = makeEl("h4", "tour-title");
        const text = makeEl("p", "tour-text");
        const bar = makeEl("div", "tour-bar");
        const barFill = makeEl("span", "tour-bar-fill");
        bar.appendChild(barFill);
        const foot = makeEl("div", "tour-foot");
        const back = makeEl("button", "rp-btn tour-back", "Back");
        back.type = "button";
        const next = makeEl("button", "rp-send tour-next", "Next");
        next.type = "button";
        foot.append(back, next);
        card.append(head, title, text, bar, foot);
        document.body.append(shield, spot, card);
        tour = { steps, index: 0, group: null, lastKey: null, raf: 0, shield, spot, card, count, title, text, barFill, back, next, skip };

        skip.addEventListener("click", endTour);
        back.addEventListener("click", () => go(-1));
        next.addEventListener("click", () => {
            if (tour.index === tour.steps.length - 1) endTour(); else go(1);
        });
        shield.addEventListener("click", (e) => e.stopPropagation());
        window.addEventListener("resize", place);
        document.addEventListener("keydown", onKey, true);
        show(0);
        tour.raf = setInterval(follow, 60);
    }

    function endTour() {
        if (!tour) return;
        clearInterval(tour.raf);
        if (tour.group) GROUPS[tour.group].leave();
        tour.shield.remove(); tour.spot.remove(); tour.card.remove();
        window.removeEventListener("resize", place);
        document.removeEventListener("keydown", onKey, true);
        tour = null;
        btn.focus();
    }

    function onKey(e) {
        if (!tour) return;
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); endTour(); }
        else if (e.key === "ArrowRight" || e.key === "Enter") {
            if (e.target && e.target.closest && e.target.closest(".tour-skip, .tour-back")) return;
            e.preventDefault(); e.stopPropagation();
            if (tour.index === tour.steps.length - 1) endTour(); else go(1);
        } else if (e.key === "ArrowLeft") { e.preventDefault(); e.stopPropagation(); go(-1); }
    }

    function go(delta) {
        const i = tour.index + delta;
        if (i < 0 || i >= tour.steps.length) return;
        show(i);
    }

    function show(i) {
        tour.index = i;
        const s = tour.steps[i];
        const last = i === tour.steps.length - 1;
        tour.count.textContent = `Step ${i + 1} of ${tour.steps.length}`;
        tour.title.textContent = s.title;
        tour.text.textContent = s.centered
            ? `${s.text} (Not on screen right now. It shows up when it applies.)`
            : s.text;
        tour.barFill.style.width = `${((i + 1) / tour.steps.length) * 100}%`;
        tour.back.disabled = i === 0;
        tour.next.textContent = last ? "Done" : "Next";
        syncGroup(s);
        const el = s.centered ? null : document.querySelector(s.sel);
        if (el && visibleRect(el)) el.scrollIntoView({ block: "center", inline: "nearest" });
        place();
        tour.next.focus({ preventScroll: true });
    }

    // Panels slide in and pages scroll, so keep the spotlight on the target while the tour runs.
    function follow() {
        if (!tour) return;
        const s = tour.steps[tour.index];
        const el = s.centered ? null : document.querySelector(s.sel);
        const r = visibleRect(el);
        const key = r ? [r.left, r.top, r.width, r.height].join() : "none";
        if (key !== tour.lastKey) { tour.lastKey = key; place(); }
    }

    function place() {
        if (!tour) return;
        const s = tour.steps[tour.index];
        const el = s.centered ? null : document.querySelector(s.sel);
        const r = visibleRect(el);
        const card = tour.card;
        const vw = window.innerWidth, vh = window.innerHeight;
        card.style.maxWidth = `${Math.min(360, vw - 24)}px`;
        if (!r) {
            tour.spot.classList.add("is-gone");
            card.style.left = `${Math.max(12, (vw - card.offsetWidth) / 2)}px`;
            card.style.top = `${Math.max(12, (vh - card.offsetHeight) / 2)}px`;
            return;
        }
        tour.spot.classList.remove("is-gone");
        const sp = tour.spot.style;
        sp.left = `${r.left - PAD}px`;
        sp.top = `${r.top - PAD}px`;
        sp.width = `${r.width + PAD * 2}px`;
        sp.height = `${r.height + PAD * 2}px`;
        const cw = card.offsetWidth, ch = card.offsetHeight;
        const below = vh - r.bottom - PAD - GAP;
        const above = r.top - PAD - GAP;
        const right = vw - r.right - PAD - GAP;
        let left, top;
        if (below >= ch) { top = r.bottom + PAD + GAP; left = r.left; }
        else if (above >= ch) { top = r.top - PAD - GAP - ch; left = r.left; }
        else if (right >= cw) { left = r.right + PAD + GAP; top = r.top; }
        else if (r.left - PAD - GAP >= cw) { left = r.left - PAD - GAP - cw; top = r.top; }
        else { left = (vw - cw) / 2; top = vh - ch - 16; } // target is huge: dock at the bottom
        left = Math.min(Math.max(12, left), vw - cw - 12);
        top = Math.min(Math.max(12, top), vh - ch - 12);
        card.style.left = `${left}px`;
        card.style.top = `${top}px`;
    }

    tourBtn.addEventListener("click", () => {
        closeAbout(false);
        startTour();
    });
})();
