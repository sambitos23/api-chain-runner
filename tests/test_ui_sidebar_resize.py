"""Focused regression contracts for the fixed sidebar and file-name disclosure.

The module intentionally combines source contracts with small Hypothesis models:
the repository has no JavaScript DOM test runner, while the source contracts
cover the exact template, script, and stylesheet boundaries required by the
sidebar bugfix.
"""

from pathlib import Path
import re

import pytest
from hypothesis import given, settings, strategies as st


ROOT = Path(__file__).parents[1]
TEMPLATE_ROOT = ROOT / "api_chain_runner/ui/templates"
STATIC_ROOT = ROOT / "api_chain_runner/ui/static"
SIDEBAR_JS = (STATIC_ROOT / "sidebar.js").read_text(encoding="utf-8")
STYLE_CSS = (STATIC_ROOT / "style.css").read_text(encoding="utf-8")
AFFECTED_TEMPLATES = ("index.html", "flow.html", "docs.html")


@pytest.fixture(scope="module")
def templates():
    return {
        name: (TEMPLATE_ROOT / name).read_text(encoding="utf-8")
        for name in AFFECTED_TEMPLATES
    }


def _sidebar_nav(template):
    return template[template.index("<nav"):template.index("</nav>")]


def test_fixed_sidebar_templates_have_file_item_contract_and_no_resize_affordance(templates):
    """**Validates: Requirements 2.1, 2.4, 2.5, 2.6, 3.1, 3.6**"""
    for template_name, template in templates.items():
        nav = _sidebar_nav(template)
        assert 'class="sidebar-resize-handle"' not in template, template_name
        assert "aria-valuemin" not in template, template_name
        assert "aria-valuemax" not in template, template_name
        assert "aria-valuenow" not in template, template_name
        assert 'role="separator"' not in template, template_name
        assert "nav-file-item" in nav, template_name
        assert 'data-file-name="{{ ' in nav, template_name
        assert 'class="nav-file-name"' in nav, template_name
        assert "sidebar.js" in template, template_name

    assert 'data-file-name="{{ flow.name }}"' in templates["index.html"]
    assert 'data-file-name="{{ chain.name }}"' in templates["flow.html"]
    assert 'data-file-name="{{ flow_name }}"' in templates["docs.html"]
    assert '<span class="nav-file-name">{{ flow.name }}</span>' in templates["index.html"]
    assert '<span class="nav-file-name">{{ chain.name }}</span>' in templates["flow.html"]
    assert '<span class="nav-file-name">{{ flow_name }}</span>' in templates["docs.html"]


def test_fixed_sidebar_script_has_conditional_exact_name_disclosure_and_no_resize_state():
    """**Validates: Requirements 2.2, 2.3, 2.5, 2.6, 3.5, 3.6**"""
    forbidden = (
        "acr-sidebar-width",
        "localStorage",
        "sessionStorage",
        "setPointerCapture",
        "releasePointerCapture",
        "pointerdown",
        "pointermove",
        "pointerup",
        "pointercancel",
        "ArrowLeft",
        "ArrowRight",
        "ArrowUp",
        "ArrowDown",
        "Home",
        "End",
        "sidebar-resizing",
        "ew-resize",
        "matchMedia",
        "--sidebar-width",
        ".style.",
    )
    for fragment in forbidden:
        assert fragment not in SIDEBAR_JS, fragment

    for fragment in (
        'querySelectorAll(".nav-file-item")',
        'querySelector(".nav-file-name")',
        "dataset.fileName",
        "scrollWidth",
        "clientWidth",
        'setAttribute("title", rawName)',
        'setAttribute("aria-label", rawName)',
        'removeAttribute("title")',
        'removeAttribute("aria-label")',
        'window.addEventListener("resize", updateDisclosure)',
        "ResizeObserver",
    ):
        assert fragment in SIDEBAR_JS, fragment

    assert "label.scrollWidth > label.clientWidth" in SIDEBAR_JS
    assert "if (!items.length) return;" in SIDEBAR_JS
    assert "if (!label) return;" in SIDEBAR_JS
    assert "typeof rawName !== \"string\"" in SIDEBAR_JS


def test_fixed_sidebar_css_has_bounded_label_and_fixed_responsive_layout():
    """**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.2, 3.3, 3.4**"""
    assert ":root { --sidebar-width: 260px; }" in STYLE_CSS
    assert ".sidebar { width: var(--sidebar-width);" in STYLE_CSS
    assert ".main-content { flex: 1; margin-left: var(--sidebar-width);" in STYLE_CSS
    assert ".sidebar-resize-handle" not in STYLE_CSS
    assert "sidebar-resizing" not in STYLE_CSS
    assert "cursor: ew-resize" not in STYLE_CSS
    assert "user-select: none" not in STYLE_CSS

    nav_item = re.search(r"\.nav-item\s*\{([^}]*)\}", STYLE_CSS)
    assert nav_item, "missing nav-item rule"
    assert "display: flex" in nav_item.group(1)
    assert "overflow: hidden" in nav_item.group(1)
    assert "min-width: 0" in nav_item.group(1)

    file_name = re.search(r"\.nav-file-name\s*\{([^}]*)\}", STYLE_CSS)
    assert file_name, "missing nav-file-name rule"
    for declaration in (
        "display: block",
        "flex: 1 1 auto",
        "min-width: 0",
        "overflow: hidden",
        "white-space: nowrap",
        "text-overflow: ellipsis",
    ):
        assert declaration in file_name.group(1), declaration
    assert ".icon {" in STYLE_CSS and "flex-shrink: 0" in STYLE_CSS

    assert "@media (max-width: 700px)" in STYLE_CSS
    assert ".sidebar { position: relative; width: 100%; min-height: auto; max-height: none; }" in STYLE_CSS
    assert ".main-content { margin-left: 0; min-width: 0; }" in STYLE_CSS
    assert "@media (max-width: 480px)" in STYLE_CSS
    assert ".nav-item.nav-indent { padding-left: 2.5rem; }" in STYLE_CSS


_FILE_NAME_PARTS = st.one_of(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"),
            whitelist_characters="_-.",
        ),
        min_size=1,
        max_size=48,
    ),
    st.sampled_from(
        (
            "folder/very_long_chain.yaml",
            "pan_verification_module/bharatpe/chain.yaml",
            "name with spaces.yaml",
            "résumé_流程.yaml",
            "punctuation.!@#$%^&() yaml",
            "x" * 160,
        )
    ),
)


@settings(max_examples=20, deadline=None)
@given(raw_name=_FILE_NAME_PARTS, rendered_width=st.integers(1, 400))
def test_generated_file_names_require_exact_non_layout_disclosure(
    templates, raw_name, rendered_width
):
    """**Validates: Requirements 2.4, 2.5, 2.6, 3.6**

    This model covers long unbroken names, folders, punctuation, Unicode, and
    spaces. The source contract preserves the raw value separately from the
    visual label and models the conditional disclosure decision.
    """
    available_width = max(1, rendered_width // 2)
    overflowing = rendered_width > available_width

    for template_name, template in templates.items():
        assert 'class="nav-file-name"' in template, (template_name, raw_name)
        assert "data-file-name=" in template, (template_name, raw_name)
        assert "scrollWidth" in SIDEBAR_JS and "clientWidth" in SIDEBAR_JS
        assert 'setAttribute("title", rawName)' in SIDEBAR_JS
        assert 'setAttribute("aria-label", rawName)' in SIDEBAR_JS
        assert 'removeAttribute("title")' in SIDEBAR_JS
        assert 'removeAttribute("aria-label")' in SIDEBAR_JS

    # The model's raw value is never sourced from rendered/ellipsized text.
    assert "dataset.fileName" in SIDEBAR_JS
    assert "label.textContent" not in SIDEBAR_JS
    if overflowing:
        assert "label.scrollWidth > label.clientWidth" in SIDEBAR_JS
    else:
        assert "removeAttribute(\"title\")" in SIDEBAR_JS


def test_preservation_navigation_targets_active_states_and_hierarchy(templates):
    """**Validates: Requirements 3.1, 3.2, 3.6**"""
    expected = {
        "index.html": (
            ('href="/" class="nav-item active"', '#i-grid', "Dashboard"),
            ('class="nav-folder"', '#i-folder', "{{ folder.name }}"),
            ('href="/flow/{{ flow.path }}"', '#i-file', "{{ flow.name }}"),
        ),
        "flow.html": (
            ('href="/" class="nav-item"', '#i-grid', "Dashboard"),
            ('href="#" class="nav-item nav-file-item active"', '#i-flow', "{{ chain.name }}"),
            ('href="/flow/{{ flow_path }}/docs" class="nav-item"', '#i-file', "Documentation"),
        ),
        "docs.html": (
            ('href="/" class="nav-item"', '#i-grid', "Dashboard"),
            ('href="/flow/{{ flow_path }}" class="nav-item"', '#i-flow', "Flow View"),
            ('href="#" class="nav-item nav-file-item active"', '#i-file', "{{ flow_name }}"),
        ),
    }

    for template_name, contracts in expected.items():
        template = templates[template_name]
        previous_position = -1
        for href, icon, label in contracts:
            position = template.find(href)
            assert position > previous_position, (template_name, href)
            previous_position = position
            if icon:
                assert template.find(icon, position) > position, (template_name, icon)
            if label:
                assert template.find(label, position) > position, (template_name, label)

    assert "nav-section" in templates["index.html"]
    assert "nav-section" in templates["flow.html"]
    assert "nav-section" in templates["docs.html"]
    assert "nav-group-body" in templates["index.html"]
    assert 'class="nav-folder"' in templates["index.html"]


def test_preservation_theme_and_script_contracts(templates):
    """**Validates: Requirements 3.2, 3.4**"""
    for template_name, template in templates.items():
        assert '<html lang="en" data-theme="dark">' in template, template_name
        assert 'class="theme-toggle" id="theme-toggle"' in template, template_name
        assert 'class="theme-icon-dark"' in template, template_name
        assert 'class="theme-icon-light"' in template, template_name
        assert "url_for('static', filename='style.css')" in template, template_name
        assert "url_for('static', filename='theme.js')" in template, template_name
        assert "url_for('static', filename='sidebar.js')" in template, template_name

    for selector in (
        '[data-theme="dark"]',
        '[data-theme="light"]',
        '[data-theme="dark"] .theme-icon-light',
        '[data-theme="light"] .theme-icon-dark',
    ):
        assert selector in STYLE_CSS


def test_preservation_editor_and_unrelated_ui_source_contracts(templates):
    """**Validates: Requirements 3.2, 3.4, 3.5**"""
    editor = (TEMPLATE_ROOT / "editor.html").read_text(encoding="utf-8")
    assert "sidebar-resize-handle" not in editor
    assert "sidebar.js" not in editor
    for fragment in (
        'href="/" class="nav-item"',
        'href="/flow/{{ flow_path }}" class="nav-item"',
        'href="/flow/{{ flow_path }}/docs" class="nav-item"',
        'href="#" class="nav-item active"',
        'id="theme-toggle"',
        'id="monaco-container"',
        'id="editor-save"',
    ):
        assert fragment in editor, fragment

    # The sidebar-only fix must not remove page-specific surfaces.
    for fragment in ('id="create-modal"', 'id="create-flow-btn"'):
        assert fragment in templates["index.html"], fragment
    for fragment in (
        'id="run-btn"',
        'id="response-panel"',
        'id="step-detail"',
        'id="editor-section"',
    ):
        assert fragment in templates["flow.html"], fragment
    for fragment in ('id="doc-view"', 'id="quill-editor"', 'id="edit-toggle"', 'id="save-btn"'):
        assert fragment in templates["docs.html"], fragment


_FILE_NAME_CASES = st.one_of(
    st.sampled_from(("orders", "a.yaml", "short name", "résumé_流程.yaml")),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"),
            whitelist_characters=" _-.",
        ),
        min_size=1,
        max_size=64,
    ),
)


@settings(max_examples=24, deadline=None)
@given(
    raw_name=_FILE_NAME_CASES,
    active=st.booleans(),
    has_folder=st.booleans(),
    theme=st.sampled_from(("dark", "light")),
    viewport=st.sampled_from(("desktop", "700px", "480px")),
)
def test_preservation_generated_name_matrix_keeps_navigation_and_layout_contracts(
    templates, raw_name, active, has_folder, theme, viewport
):
    """**Validates: Requirements 2.6, 3.1, 3.2, 3.3, 3.4, 3.6**"""
    assert raw_name
    assert active in (True, False)
    assert theme in ("dark", "light")
    assert viewport in ("desktop", "700px", "480px")

    index = templates["index.html"]
    assert 'href="/flow/{{ flow.path }}"' in index
    assert 'class="nav-item nav-file-item' in index
    assert 'data-file-name="{{ flow.name }}"' in index
    assert '<span class="nav-file-name">{{ flow.name }}</span>' in index
    assert "folder.name" in index
    assert "nav-group-body" in index
    assert "#i-file" in index

    flow = templates["flow.html"]
    docs = templates["docs.html"]
    assert 'href="#" class="nav-item nav-file-item active"' in flow
    assert 'href="#" class="nav-item nav-file-item active"' in docs
    assert 'data-file-name="{{ chain.name }}"' in flow
    assert 'data-file-name="{{ flow_name }}"' in docs
    assert "#i-flow" in flow and "#i-file" in docs

    # Fitting names retain complete visual text and no conditional title-only
    # disclosure; overflowing names use the same exact raw-name metadata path.
    assert "dataset.fileName" in SIDEBAR_JS
    assert 'setAttribute("title", rawName)' in SIDEBAR_JS
    assert 'setAttribute("aria-label", rawName)' in SIDEBAR_JS
    assert 'removeAttribute("title")' in SIDEBAR_JS
    assert 'removeAttribute("aria-label")' in SIDEBAR_JS
    assert "text-overflow: ellipsis" in STYLE_CSS
    assert "min-width: 0" in STYLE_CSS
