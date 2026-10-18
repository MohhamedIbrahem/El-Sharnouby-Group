/**
 * El-Sharnouby Group — Main JavaScript
 * Sidebar toggle, responsive chart resizing, layout helpers.
 */
(function () {
    "use strict";

    // ── Sidebar Toggle ────────────────────────────────────
    const sidebar = document.getElementById("sidebar");
    const mainContent = document.getElementById("mainContent");
    const sidebarToggle = document.getElementById("sidebarToggle");
    const mobileMenuBtn = document.getElementById("mobileMenuBtn");
    const mobileOverlay = document.getElementById("mobileOverlay");

    if (sidebarToggle) {
        sidebarToggle.addEventListener("click", function () {
            sidebar.classList.toggle("collapsed");
            mainContent.classList.toggle("sidebar-collapsed");

            // Toggle chevron rotation is handled in CSS (.sidebar.collapsed .toggle-icon)

            // Resize all Plotly charts after transition
            setTimeout(resizeAllCharts, 350);
        });
    }

    // ── Mobile Menu ───────────────────────────────────────
    if (mobileMenuBtn) {
        mobileMenuBtn.addEventListener("click", function () {
            sidebar.classList.toggle("mobile-open");
            mobileOverlay.classList.toggle("active");
        });
    }

    if (mobileOverlay) {
        mobileOverlay.addEventListener("click", function () {
            sidebar.classList.remove("mobile-open");
            mobileOverlay.classList.remove("active");
        });
    }

    // ── Responsive Chart Resizing ─────────────────────────
    function resizeAllCharts() {
        const plots = document.querySelectorAll(".js-plotly-plot");
        plots.forEach(function (plot) {
            Plotly.Plots.resize(plot);
        });
    }

    let resizeTimeout;
    window.addEventListener("resize", function () {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(resizeAllCharts, 200);
    });

    // ── Animated Number Counter ───────────────────────────
    function animateCounters() {
        const counters = document.querySelectorAll("[data-count]");
        counters.forEach(function (el) {
            const target = parseFloat(el.getAttribute("data-count"));
            const suffix = el.getAttribute("data-suffix") || "";
            const duration = 1200;
            const start = performance.now();

            function update(now) {
                const elapsed = now - start;
                const progress = Math.min(elapsed / duration, 1);
                // Ease out cubic
                const eased = 1 - Math.pow(1 - progress, 3);
                const current = target * eased;

                if (target >= 1000000) {
                    el.textContent = (current / 1000000).toFixed(1) + "M" + suffix;
                } else if (target >= 1000) {
                    el.textContent = (current / 1000).toFixed(1) + "K" + suffix;
                } else if (Number.isInteger(target)) {
                    el.textContent = Math.round(current) + suffix;
                } else {
                    el.textContent = current.toFixed(1) + suffix;
                }

                if (progress < 1) {
                    requestAnimationFrame(update);
                }
            }

            requestAnimationFrame(update);
        });
    }

    // Run counter animation on load
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", animateCounters);
    } else {
        animateCounters();
    }

    // ── Staggered card entrance animation ─────────────────
    const animateElements = document.querySelectorAll(".animate-in");
    animateElements.forEach(function (el, i) {
        el.style.animationDelay = (i * 0.06) + "s";
    });

})();
