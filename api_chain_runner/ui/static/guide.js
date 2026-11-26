/* guide.js — highlight the current section in the guide's sidebar index */
(function () {
    const toc = document.getElementById("guide-toc");
    if (!toc || typeof IntersectionObserver !== "function") return;
    const links = new Map();
    toc.querySelectorAll("a[href^='#']").forEach((a) => links.set(a.getAttribute("href").slice(1), a));
    const setActive = (id) => links.forEach((a, key) => a.classList.toggle("active", key === id));
    const observer = new IntersectionObserver((entries) => {
        const hit = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (hit) setActive(hit.target.id);
    }, { rootMargin: "-10% 0px -75% 0px" });
    links.forEach((_, id) => { const el = document.getElementById(id); if (el) observer.observe(el); });
    setActive("overview");
})();
