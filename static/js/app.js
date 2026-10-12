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
    var modal = document.getElementById(id);
    if (modal) {
        if (modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }
        modal.classList.add("show");
    }
}
function closeModal(id) {
    var modal = document.getElementById(id);
    if (modal) {
        modal.classList.remove("show");
    }
}
document.addEventListener("DOMContentLoaded", function() {
    document.querySelectorAll(".modal-overlay").forEach(function(modal) {
        if (modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }
    });
});
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

/* ============================================================
   CUSTOM CALENDAR DATEPICKER COMPONENT
   ============================================================ */
(function () {
    const MONTH_NAMES = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    ];

    let currentInput = null;
    let viewYear = new Date().getFullYear();
    let viewMonth = new Date().getMonth(); // 0-11
    let selectedDate = null; // { year, month, day }
    let popupEl = null;

    function createDatePickerPopup() {
        if (popupEl) return popupEl;

        popupEl = document.createElement("div");
        popupEl.className = "custom-datepicker-popup";
        popupEl.id = "customDatePickerPopup";

        popupEl.innerHTML = `
            <div class="cdp-header">
                <button type="button" class="cdp-nav-btn cdp-prev-btn" aria-label="Previous Month">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
                </button>
                <div class="cdp-title-wrap">
                    <div class="cdp-select-pill">
                        <span class="cdp-month-label">Oct</span>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"></polyline></svg>
                        <select class="cdp-native-select cdp-month-select" aria-label="Select Month">
                            ${MONTH_NAMES.map((m, idx) => `<option value="${idx}">${m}</option>`).join("")}
                        </select>
                    </div>
                    <div class="cdp-select-pill">
                        <span class="cdp-year-label">2026</span>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"></polyline></svg>
                        <select class="cdp-native-select cdp-year-select" aria-label="Select Year"></select>
                    </div>
                </div>
                <button type="button" class="cdp-nav-btn cdp-next-btn" aria-label="Next Month">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
                </button>
            </div>
            <div class="cdp-weekdays">
                <div class="cdp-weekday cdp-sunday">Su</div>
                <div class="cdp-weekday">Mo</div>
                <div class="cdp-weekday">Tu</div>
                <div class="cdp-weekday">We</div>
                <div class="cdp-weekday">Th</div>
                <div class="cdp-weekday">Fr</div>
                <div class="cdp-weekday">Sa</div>
            </div>
            <div class="cdp-grid"></div>
            <div class="cdp-footer">
                <button type="button" class="cdp-action-btn cdp-today-btn">Today</button>
                <button type="button" class="cdp-action-btn cdp-clear-btn">Clear</button>
            </div>
        `;

        document.body.appendChild(popupEl);

        // Populate years from currentYear - 30 to currentYear + 30
        const yearSelect = popupEl.querySelector(".cdp-year-select");
        const currentY = new Date().getFullYear();
        for (let y = currentY - 30; y <= currentY + 30; y++) {
            const opt = document.createElement("option");
            opt.value = y;
            opt.textContent = y;
            yearSelect.appendChild(opt);
        }

        // Header Navigation Listeners
        popupEl.querySelector(".cdp-prev-btn").addEventListener("click", function (e) {
            e.stopPropagation();
            viewMonth--;
            if (viewMonth < 0) {
                viewMonth = 11;
                viewYear--;
            }
            renderCalendar();
        });

        popupEl.querySelector(".cdp-next-btn").addEventListener("click", function (e) {
            e.stopPropagation();
            viewMonth++;
            if (viewMonth > 11) {
                viewMonth = 0;
                viewYear++;
            }
            renderCalendar();
        });

        popupEl.querySelector(".cdp-month-select").addEventListener("change", function (e) {
            e.stopPropagation();
            viewMonth = parseInt(this.value, 10);
            renderCalendar();
        });

        popupEl.querySelector(".cdp-year-select").addEventListener("change", function (e) {
            e.stopPropagation();
            viewYear = parseInt(this.value, 10);
            renderCalendar();
        });

        // Footer Actions
        popupEl.querySelector(".cdp-today-btn").addEventListener("click", function (e) {
            e.stopPropagation();
            const now = new Date();
            selectDateAndClose(now.getFullYear(), now.getMonth(), now.getDate());
        });

        popupEl.querySelector(".cdp-clear-btn").addEventListener("click", function (e) {
            e.stopPropagation();
            if (currentInput) {
                currentInput.value = "";
                currentInput.dispatchEvent(new Event("input", { bubbles: true }));
                currentInput.dispatchEvent(new Event("change", { bubbles: true }));
            }
            closeDatePicker();
        });

        // Stop clicks inside popup from bubbling to window (which would close it)
        popupEl.addEventListener("click", function (e) {
            e.stopPropagation();
        });
        popupEl.addEventListener("mousedown", function (e) {
            e.stopPropagation();
        });
        popupEl.addEventListener("touchstart", function (e) {
            e.stopPropagation();
        }, { passive: true });

        return popupEl;
    }

    function parseInputDate(val) {
        if (!val || typeof val !== "string") return null;
        val = val.trim();
        // Check YYYY-MM-DD
        const isoMatch = val.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
        if (isoMatch) {
            return {
                year: parseInt(isoMatch[1], 10),
                month: parseInt(isoMatch[2], 10) - 1,
                day: parseInt(isoMatch[3], 10),
            };
        }
        // Check DD/MM/YYYY
        const dmyMatch = val.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
        if (dmyMatch) {
            return {
                year: parseInt(dmyMatch[3], 10),
                month: parseInt(dmyMatch[2], 10) - 1,
                day: parseInt(dmyMatch[1], 10),
            };
        }
        return null;
    }

    function formatToISO(year, month, day) {
        const m = String(month + 1).padStart(2, "0");
        const d = String(day).padStart(2, "0");
        return `${year}-${m}-${d}`;
    }

    function renderCalendar() {
        createDatePickerPopup();

        // Update Header Labels & Selects
        popupEl.querySelector(".cdp-month-label").textContent = MONTH_NAMES[viewMonth];
        popupEl.querySelector(".cdp-month-select").value = viewMonth;
        popupEl.querySelector(".cdp-year-label").textContent = viewYear;
        popupEl.querySelector(".cdp-year-select").value = viewYear;

        const gridEl = popupEl.querySelector(".cdp-grid");
        gridEl.innerHTML = "";

        const firstDayOfWeek = new Date(viewYear, viewMonth, 1).getDay(); // 0 is Sunday
        const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
        const daysInPrevMonth = new Date(viewYear, viewMonth, 0).getDate();

        const today = new Date();
        const todayY = today.getFullYear();
        const todayM = today.getMonth();
        const todayD = today.getDate();

        // Previous month filler cells
        for (let i = firstDayOfWeek - 1; i >= 0; i--) {
            const dayNum = daysInPrevMonth - i;
            const cell = document.createElement("div");
            cell.className = "cdp-cell cdp-other-month";
            cell.textContent = dayNum;
            cell.addEventListener("click", () => {
                let m = viewMonth - 1;
                let y = viewYear;
                if (m < 0) { m = 11; y--; }
                selectDateAndClose(y, m, dayNum);
            });
            gridEl.appendChild(cell);
        }

        // Current month cells
        for (let d = 1; d <= daysInMonth; d++) {
            const cell = document.createElement("div");
            const dayOfWeek = (firstDayOfWeek + d - 1) % 7;
            let classes = "cdp-cell";
            if (dayOfWeek === 0) classes += " cdp-col-sunday";

            if (selectedDate &&
                selectedDate.year === viewYear &&
                selectedDate.month === viewMonth &&
                selectedDate.day === d) {
                classes += " cdp-selected";
            } else if (todayY === viewYear && todayM === viewMonth && todayD === d) {
                classes += " cdp-today";
            }

            cell.className = classes;
            cell.textContent = d;

            cell.addEventListener("click", (e) => {
                e.stopPropagation();
                selectDateAndClose(viewYear, viewMonth, d);
            });

            gridEl.appendChild(cell);
        }

        // Next month filler cells to complete 35 or 42 grid cells
        const totalCells = firstDayOfWeek + daysInMonth;
        const remainingCells = (totalCells % 7 === 0) ? 0 : 7 - (totalCells % 7);
        for (let n = 1; n <= remainingCells; n++) {
            const cell = document.createElement("div");
            cell.className = "cdp-cell cdp-other-month";
            cell.textContent = n;
            cell.addEventListener("click", (e) => {
                e.stopPropagation();
                let m = viewMonth + 1;
                let y = viewYear;
                if (m > 11) { m = 0; y++; }
                selectDateAndClose(y, m, n);
            });
            gridEl.appendChild(cell);
        }
    }

    function positionDatePicker() {
        if (!popupEl || !currentInput) return;

        const rect = currentInput.getBoundingClientRect();
        const popupWidth = popupEl.offsetWidth || 290;
        const popupHeight = popupEl.offsetHeight || 330;

        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

        const spaceBelow = window.innerHeight - rect.bottom;
        let top = rect.bottom + scrollTop + 5;

        // If not enough room below, open above the input
        if (spaceBelow < popupHeight && rect.top > popupHeight) {
            top = rect.top + scrollTop - popupHeight - 5;
        }

        let left = rect.left + scrollLeft;
        if (left + popupWidth > window.innerWidth - 12) {
            left = window.innerWidth - popupWidth - 12 + scrollLeft;
        }
        if (left < 10) left = 10;

        popupEl.style.top = top + "px";
        popupEl.style.left = left + "px";
    }

    function openDatePicker(input) {
        if (currentInput === input && popupEl && popupEl.style.display === "flex") {
            return;
        }

        if (currentInput) {
            currentInput.classList.remove("cdp-input-active");
        }

        currentInput = input;
        currentInput.classList.add("cdp-input-active");

        const parsed = parseInputDate(input.value);
        if (parsed) {
            selectedDate = parsed;
            viewYear = parsed.year;
            viewMonth = parsed.month;
        } else {
            selectedDate = null;
            const now = new Date();
            viewYear = now.getFullYear();
            viewMonth = now.getMonth();
        }

        createDatePickerPopup();
        renderCalendar();

        popupEl.style.display = "flex";
        positionDatePicker();
    }

    function selectDateAndClose(year, month, day) {
        if (currentInput) {
            const iso = formatToISO(year, month, day);
            currentInput.value = iso;
            currentInput.dispatchEvent(new Event("input", { bubbles: true }));
            currentInput.dispatchEvent(new Event("change", { bubbles: true }));
        }
        closeDatePicker();
    }

    function closeDatePicker() {
        if (popupEl) {
            popupEl.style.display = "none";
        }
        if (currentInput) {
            currentInput.classList.remove("cdp-input-active");
            currentInput = null;
        }
    }

    // Attach to inputs
    function initDatePickerOnInputs() {
        const selector = 'input[type="date"], input.custom-datepicker, input.cd-date-input, input.rdm-date-input, input[name$="_date"], input[name="date"], input[id*="Date"], input[id*="date"]';
        document.querySelectorAll(selector).forEach(input => {
            if (input._cdpInitialized) return;
            input._cdpInitialized = true;

            input.setAttribute("autocomplete", "off");

            // Override Chrome's native showPicker if available
            try {
                input.showPicker = function () {
                    openDatePicker(input);
                };
            } catch (err) {}

            // Prevent native picker and open custom calendar
            input.addEventListener("mousedown", function (e) {
                // Allows right click or middle click to behave normally
                if (e.button !== 0) return;
                openDatePicker(input);
            });

            input.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                openDatePicker(input);
            });

            input.addEventListener("focus", function () {
                openDatePicker(input);
            });

            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
                    e.preventDefault();
                    openDatePicker(input);
                } else if (e.key === "Escape") {
                    closeDatePicker();
                }
            });
        });
    }

    // Global listeners to close when clicking outside
    document.addEventListener("click", function (e) {
        if (!popupEl || popupEl.style.display !== "flex") return;
        if (currentInput && currentInput.contains(e.target)) return;
        if (popupEl.contains(e.target)) return;
        closeDatePicker();
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
            closeDatePicker();
        }
    });

    window.addEventListener("resize", function () {
        if (popupEl && popupEl.style.display === "flex") {
            positionDatePicker();
        }
    });

    window.addEventListener("scroll", function () {
        if (popupEl && popupEl.style.display === "flex") {
            positionDatePicker();
        }
    }, true);

    // Run on DOM ready and watch for dynamic modals
    document.addEventListener("DOMContentLoaded", function () {
        initDatePickerOnInputs();

        // Observer to catch any dynamically added inputs (e.g. inside modals)
        const observer = new MutationObserver(function () {
            initDatePickerOnInputs();
        });
        observer.observe(document.body, { childList: true, subtree: true });
    });

    // Expose helpers globally
    window.openCustomDatePicker = openDatePicker;
    window.closeCustomDatePicker = closeDatePicker;
})();

