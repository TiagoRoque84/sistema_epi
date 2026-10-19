document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.querySelector("[data-menu-toggle]");
  const sidebar = document.querySelector("#sidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", () => {
      const isOpen = sidebar.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(isOpen));
    });

    document.addEventListener("click", (event) => {
      if (window.innerWidth > 860 || !sidebar.classList.contains("is-open")) return;
      if (!sidebar.contains(event.target) && !toggle.contains(event.target)) {
        sidebar.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  document.querySelectorAll("[data-line-items]").forEach((form) => {
    const container = form.querySelector("[data-lines]");
    const template = form.querySelector("[data-line-template]");
    const add = form.querySelector("[data-add-line]");
    if (!container) return;

    function updateRemoveButtons() {
      const lines = container.querySelectorAll(".line-item");
      lines.forEach((line) => {
        const button = line.querySelector("[data-remove-line]");
        if (button) button.disabled = lines.length === 1;
      });
    }

    container.addEventListener("click", (event) => {
      const button = event.target.closest("[data-remove-line]");
      if (!button || button.disabled) return;
      button.closest(".line-item").remove();
      updateRemoveButtons();
    });
    if (add && template) {
      add.addEventListener("click", () => {
        container.appendChild(template.content.cloneNode(true));
        updateRemoveButtons();
      });
    }
    updateRemoveButtons();
  });
});
