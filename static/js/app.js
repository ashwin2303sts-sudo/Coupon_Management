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

(function () {
    const tableSelector = ".content .table-wrap, .content .booking-table-wrap, .content .ledger-table-wrap, .content .rdm-table-wrap";

    function setupFixedHorizontalScroll() {
        const fixed = document.getElementById("globalFixedScroll");
        if (!fixed || !fixed.firstElementChild) return;

        const inner = fixed.firstElementChild;
        const wrappers = Array.from(document.querySelectorAll(tableSelector))
            .filter(element => !element.closest(".modal-overlay"));
        const maxTableOverflow = wrappers.reduce(
            (maxOverflow, element) => Math.max(maxOverflow, element.scrollWidth - element.clientWidth),
            0
        );

        if (maxTableOverflow <= 2) {
            fixed.style.display = "none";
            inner.style.width = "1px";
            fixed.scrollLeft = 0;
            return;
        }

        fixed.style.display = "block";
        inner.style.width = `${fixed.clientWidth + maxTableOverflow}px`;
        fixed.scrollLeft = Math.min(fixed.scrollLeft, maxTableOverflow);
    }

    let syncing = false;

    function syncTablesToFixed(event) {
        const fixed = document.getElementById("globalFixedScroll");
        if (!fixed || syncing) return;
        syncing = true;

        const source = event.currentTarget;
        const sourceMax = Math.max(1, source.scrollWidth - source.clientWidth);
        const ratio = source.scrollLeft / sourceMax;
        const fixedMax = Math.max(0, fixed.scrollWidth - fixed.clientWidth);
        fixed.scrollLeft = ratio * fixedMax;

        document.querySelectorAll(tableSelector).forEach(element => {
            if (element !== source && !element.closest(".modal-overlay")) {
                const elementMax = Math.max(0, element.scrollWidth - element.clientWidth);
                element.scrollLeft = ratio * elementMax;
            }
        });
        syncing = false;
    }

    function syncFixedToTables() {
        const fixed = document.getElementById("globalFixedScroll");
        if (!fixed || syncing) return;
        syncing = true;

        const fixedMax = Math.max(1, fixed.scrollWidth - fixed.clientWidth);
        const ratio = fixed.scrollLeft / fixedMax;
        document.querySelectorAll(tableSelector).forEach(element => {
            if (!element.closest(".modal-overlay")) {
                const elementMax = Math.max(0, element.scrollWidth - element.clientWidth);
                element.scrollLeft = ratio * elementMax;
            }
        });
        syncing = false;
    }

    document.addEventListener("DOMContentLoaded", function () {
        setupFixedHorizontalScroll();

        const fixed = document.getElementById("globalFixedScroll");
        if (fixed) fixed.addEventListener("scroll", syncFixedToTables, { passive: true });
        document.querySelectorAll(tableSelector).forEach(element => {
            if (!element.closest(".modal-overlay")) {
                element.addEventListener("scroll", syncTablesToFixed, { passive: true });
            }
        });

        window.addEventListener("resize", setupFixedHorizontalScroll);
        window.addEventListener("load", setupFixedHorizontalScroll);
        setTimeout(setupFixedHorizontalScroll, 250);
        setTimeout(setupFixedHorizontalScroll, 1000);
    });
})();
