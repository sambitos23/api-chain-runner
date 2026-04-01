/* docs.js — Flow documentation with Quill rich text editor */
(function () {
    const editToggle = document.getElementById("edit-toggle");
    const saveBtn = document.getElementById("save-btn");
    const saveStatus = document.getElementById("save-status");
    const docView = document.getElementById("doc-view");
    const docEdit = document.getElementById("doc-edit");
    const authorsContainer = document.getElementById("e-authors");
    const addAuthorBtn = document.getElementById("add-author-btn");
    const addChangelogBtn = document.getElementById("add-changelog-btn");

    let editing = false;
    let existingDoc = null;
    let quill = null;

    // Load existing doc
    fetch(`/api/flow/${FLOW_PATH}/docs`).then(r => r.json()).then(data => {
        existingDoc = data.doc;
    });

    // ── Quill setup (lazy init on first edit) ────────────────
    function initQuill() {
        if (quill) return;
        quill = new Quill("#quill-editor", {
            theme: "snow",
            placeholder: "Write your context here — use the toolbar for formatting, images, etc.",
            modules: {
                toolbar: {
                    container: [
                        [{ header: [1, 2, 3, false] }],
                        ["bold", "italic", "underline", "strike"],
                        [{ list: "ordered" }, { list: "bullet" }],
                        ["blockquote", "code-block"],
                        ["link", "image"],
                        ["clean"],
                    ],
                    handlers: {
                        image: imageHandler,
                    },
                },
            },
        });
        // Load existing content
        if (INITIAL_CONTEXT) {
            quill.root.innerHTML = INITIAL_CONTEXT;
        }
    }

    // Custom image handler — uploads to server then inserts URL
    function imageHandler() {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*";
        input.onchange = async () => {
            const file = input.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append("file", file);
            try {
                const res = await fetch(`/api/flow/${FLOW_PATH}/docs/upload`, {
                    method: "POST", body: formData,
                });
                const data = await res.json();
                if (data.success) {
                    const range = quill.getSelection(true);
                    quill.insertEmbed(range.index, "image", `/docs/${FLOW_NAME}/${data.path.split("/").pop()}`);
                }
            } catch (err) {
                console.error("Image upload failed:", err);
            }
        };
        input.click();
    }

    // ── Toggle edit mode ─────────────────────────────────────
    editToggle.addEventListener("click", () => {
        editing = !editing;
        docView.classList.toggle("hidden", editing);
        docEdit.classList.toggle("hidden", !editing);
        saveBtn.classList.toggle("hidden", !editing);
        editToggle.textContent = editing ? "Cancel" : "Edit";
        if (editing) initQuill();
    });

    // ── Authors ──────────────────────────────────────────────
    addAuthorBtn.addEventListener("click", () => {
        const row = document.createElement("div");
        row.className = "author-edit-row";
        row.innerHTML = `
            <input type="text" class="form-input form-input-sm" placeholder="Name" data-field="name">
            <input type="text" class="form-input form-input-sm" placeholder="Email" data-field="email">
            <input type="text" class="form-input form-input-sm" placeholder="Role" data-field="role">`;
        authorsContainer.appendChild(row);
    });

    // ── Changelog ────────────────────────────────────────────
    const newChangelog = [];
    addChangelogBtn.addEventListener("click", () => {
        const author = document.getElementById("cl-author").value.trim();
        const note = document.getElementById("cl-note").value.trim();
        if (!note) return;
        newChangelog.push({ date: new Date().toISOString().split("T")[0], author: author || "Unknown", note });
        document.getElementById("cl-author").value = "";
        document.getElementById("cl-note").value = "";
        addChangelogBtn.textContent = `Added (${newChangelog.length})`;
    });

    // ── Save ─────────────────────────────────────────────────
    saveBtn.addEventListener("click", async () => {
        const authorRows = authorsContainer.querySelectorAll(".author-edit-row");
        const authors = [];
        authorRows.forEach(row => {
            const name = row.querySelector('[data-field="name"]').value.trim();
            const email = row.querySelector('[data-field="email"]').value.trim();
            const role = row.querySelector('[data-field="role"]').value.trim();
            if (name) authors.push({ name, email, role });
        });

        const tags = document.getElementById("e-tags").value.split(",").map(t => t.trim()).filter(Boolean);
        const changelog = [...((existingDoc && existingDoc.changelog) || []), ...newChangelog];

        // Get rich text HTML from Quill
        const contextHtml = quill ? quill.root.innerHTML : INITIAL_CONTEXT;

        const doc = {
            title: document.getElementById("e-title").value.trim(),
            description: document.getElementById("e-desc").value.trim(),
            group: document.getElementById("e-group").value.trim(),
            tags, authors,
            context: contextHtml,
            images: [],
            changelog,
        };

        saveStatus.textContent = "Saving...";
        try {
            const res = await fetch(`/api/flow/${FLOW_PATH}/docs/save`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ doc }),
            });
            const data = await res.json();
            if (data.success) {
                saveStatus.textContent = "Saved";
                saveStatus.className = "detail-save-status success";
                setTimeout(() => location.reload(), 1000);
            } else {
                saveStatus.textContent = data.error || "Failed";
                saveStatus.className = "detail-save-status error";
            }
        } catch (err) {
            saveStatus.textContent = err.message;
            saveStatus.className = "detail-save-status error";
        }
    });
})();
