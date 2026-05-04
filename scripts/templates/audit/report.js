/**
 * MY-IA Audit Report - JavaScript
 * Navigation, accordéons et interactions
 */

// ========== ACCORDÉONS ==========

function toggleSection(id) {
    const section = document.getElementById(id);
    section.classList.toggle('open');
}

function toggleSubGroup(id) {
    const group = document.getElementById(id);
    group.classList.toggle('open');
}

function togglePrintMode() {
    document.body.classList.toggle('print-mode');
    const btn = document.querySelector('.print-btn');
    if (document.body.classList.contains('print-mode')) {
        btn.innerHTML = '📄 Mode normal';
    } else {
        btn.innerHTML = '🖨️ Version imprimable';
    }
}

// ========== NAVIGATION ==========

const navSections = [];
let currentSectionIndex = 0;

function initNavigation() {
    // Collect all navigable sections
    document.querySelectorAll('[data-nav-section]').forEach(el => {
        navSections.push({ id: el.id, label: el.dataset.navSection });
    });

    // Scroll spy
    window.addEventListener('scroll', updateActiveSection);
    updateActiveSection();

    // Back to top visibility
    const backToTop = document.querySelector('.back-to-top');
    if (backToTop) {
        window.addEventListener('scroll', () => {
            backToTop.classList.toggle('visible', window.scrollY > 300);
        });
    }

    // Update nav buttons state
    updateNavButtons();
}

function updateActiveSection() {
    const scrollPos = window.scrollY + 100;
    let activeIdx = 0;

    navSections.forEach((section, idx) => {
        const el = document.getElementById(section.id);
        if (el && el.offsetTop <= scrollPos) {
            activeIdx = idx;
        }
    });

    currentSectionIndex = activeIdx;

    // Update sidebar links
    document.querySelectorAll('.sidebar-toc a').forEach((a, idx) => {
        a.classList.toggle('active', idx === activeIdx);
    });

    updateNavButtons();
}

function updateNavButtons() {
    const prevBtn = document.getElementById('navPrev');
    const nextBtn = document.getElementById('navNext');
    if (prevBtn) prevBtn.disabled = currentSectionIndex === 0;
    if (nextBtn) nextBtn.disabled = currentSectionIndex >= navSections.length - 1;
}

function navigateToSection(idx) {
    if (idx < 0 || idx >= navSections.length) return;
    const section = navSections[idx];
    const el = document.getElementById(section.id);
    if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        currentSectionIndex = idx;
        updateNavButtons();
    }
}

function navPrev() { navigateToSection(currentSectionIndex - 1); }
function navNext() { navigateToSection(currentSectionIndex + 1); }
function scrollToTop() { window.scrollTo({ top: 0, behavior: 'smooth' }); }

// Keyboard navigation
document.addEventListener('keydown', function(e) {
    // Ignore if in input/textarea
    if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;

    switch(e.key) {
        case 'j': navNext(); break;
        case 'k': navPrev(); break;
        case 'Home':
            if (e.ctrlKey) { e.preventDefault(); scrollToTop(); }
            break;
        case 'End':
            if (e.ctrlKey) { e.preventDefault(); navigateToSection(navSections.length - 1); }
            break;
    }
});

// ========== INITIALIZATION ==========

document.addEventListener('DOMContentLoaded', function() {
    // Ouvrir automatiquement la section HIGH si elle a des éléments
    const highSection = document.getElementById('section-HIGH');
    if (highSection && highSection.querySelector('.finding')) {
        highSection.classList.add('open');
    }

    // Initialiser les graphiques (fonction définie dynamiquement)
    if (typeof initCharts === 'function') {
        initCharts();
    }

    // Initialiser la navigation
    initNavigation();
});
