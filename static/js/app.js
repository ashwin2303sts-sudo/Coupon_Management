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
