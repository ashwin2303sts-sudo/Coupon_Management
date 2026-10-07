function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
}
function openLogout() {
    document.getElementById("logoutModal").classList.add("show");
}
function closeLogout() {
    document.getElementById("logoutModal").classList.remove("show");
}
function openModal(id) {
    document.getElementById(id).classList.add("show");
}
function closeModal(id) {
    document.getElementById(id).classList.remove("show");
}
window.addEventListener("click", function(e) {
    document.querySelectorAll(".modal-overlay").forEach(function(modal) {
        if (e.target === modal && modal.id !== "logoutModal") {
            modal.classList.remove("show");
        }
    });
});
setTimeout(function() {
    document.querySelectorAll(".alert").forEach(function(el) {
        el.style.opacity = "0";
        setTimeout(() => el.remove(), 500);
    });
}, 4500);
setTimeout(function() {
    document.querySelectorAll(".excel-upload-toast").forEach(function(el) {
        el.style.opacity = "0";
        setTimeout(() => el.remove(), 500);
    });
}, 3000);


/* ============================================================
   Global fixed horizontal scrollbar
   - Keeps exactly one horizontal scrollbar at the bottom.
   - Synchronizes all visible page table wrappers.
   - Automatically hides when the page has no horizontal overflow.
   ============================================================ */
(function () {
    function setupGlobalHorizontalScroll() {
        const fixed = document.getElementById("globalFixedScroll");
        if (!fixed || !fixed.firstElementChild) return;

        const inner = fixed.firstElementChild;
        const wrappers = Array.from(document.querySelectorAll(
            ".content .table-wrap, .content .booking-table-wrap, .content .ledger-table-wrap, .content .rdm-table-card, .content .rdm-table-wrap"
        )).filter(el => !el.closest(".modal-overlay"));

        if (!wrappers.length) {
            fixed.style.display = "none";
            return;
        }

        let maxWidth = 0;
        let needsScroll = false;

        wrappers.forEach(function (el) {
            const width = Math.max(el.scrollWidth, el.clientWidth);
            maxWidth = Math.max(maxWidth, width);
            if (el.scrollWidth > el.clientWidth + 2) needsScroll = true;
        });

        // Also account for the page content itself.
        maxWidth = Math.max(maxWidth, document.documentElement.scrollWidth);
        needsScroll = needsScroll || (document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);

        if (!needsScroll) {
            fixed.style.display = "none";
            inner.style.width = "1px";
            return;
        }

        fixed.style.display = "block";
        inner.style.width = Math.max(maxWidth, fixed.clientWidth + 1) + "px";

        // Prevent a stale scroll position from making a newly loaded page jump.
        const maxLeft = Math.max(0, inner.offsetWidth - fixed.clientWidth);
        if (fixed.scrollLeft > maxLeft) fixed.scrollLeft = maxLeft;
    }

    let syncing = false;
    function syncFixedToTables() {
        const fixed = document.getElementById("globalFixedScroll");
        if (!fixed || syncing) return;
        syncing = true;
        document.querySelectorAll(
            ".content .table-wrap, .content .booking-table-wrap, .content .ledger-table-wrap, .content .rdm-table-card, .content .rdm-table-wrap"
        ).forEach(function (el) {
            if (!el.closest(".modal-overlay")) el.scrollLeft = fixed.scrollLeft;
        });
        syncing = false;
    }

    function syncTablesToFixed(event) {
        const fixed = document.getElementById("globalFixedScroll");
        if (!fixed || syncing) return;
        syncing = true;
        fixed.scrollLeft = event.target.scrollLeft;
        syncing = false;
    }

    document.addEventListener("DOMContentLoaded", function () {
        setupGlobalHorizontalScroll();

        const fixed = document.getElementById("globalFixedScroll");
        if (fixed) fixed.addEventListener("scroll", syncFixedToTables, { passive: true });

        document.querySelectorAll(
            ".content .table-wrap, .content .booking-table-wrap, .content .ledger-table-wrap, .content .rdm-table-card, .content .rdm-table-wrap"
        ).forEach(function (el) {
            if (!el.closest(".modal-overlay")) {
                el.addEventListener("scroll", syncTablesToFixed, { passive: true });
            }
        });

        window.addEventListener("resize", setupGlobalHorizontalScroll);
        window.addEventListener("load", setupGlobalHorizontalScroll);
        setTimeout(setupGlobalHorizontalScroll, 250);
        setTimeout(setupGlobalHorizontalScroll, 1000);
    });
})();
