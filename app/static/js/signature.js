document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-signature-form]");
  if (!form) return;
  const canvas = form.querySelector("[data-signature-canvas]");
  const hidden = form.querySelector("[data-signature-data]");
  const clear = form.querySelector("[data-clear-signature]");
  const placeholder = form.querySelector("[data-signature-placeholder]");
  const paper = form.querySelector("[data-paper-signature]");
  const digital = form.querySelector("[data-signature-digital]");
  const notice = form.querySelector("[data-paper-signature-notice]");
  const confirmation = form.querySelector("[data-signature-confirmation]");
  const confirmed = form.querySelector("[data-confirm-signature]");
  const context = canvas.getContext("2d");
  let drawing = false;
  let signed = false;

  function resize() {
    if (paper?.checked) return;
    const previous = signed ? canvas.toDataURL() : null;
    const ratio = Math.max(window.devicePixelRatio || 1, 1);
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.lineWidth = 2.4;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = "#172a4d";
    if (previous) {
      const image = new Image();
      image.onload = () => context.drawImage(image, 0, 0, rect.width, rect.height);
      image.src = previous;
    }
  }

  function point(event) {
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  canvas.addEventListener("pointerdown", (event) => {
    drawing = true;
    signed = true;
    canvas.setPointerCapture(event.pointerId);
    const current = point(event);
    context.beginPath();
    context.moveTo(current.x, current.y);
    placeholder.hidden = true;
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!drawing) return;
    event.preventDefault();
    const current = point(event);
    context.lineTo(current.x, current.y);
    context.stroke();
  });
  canvas.addEventListener("pointerup", () => { drawing = false; });
  canvas.addEventListener("pointercancel", () => { drawing = false; });
  function clearSignature() {
    context.clearRect(0, 0, canvas.width, canvas.height);
    drawing = false;
    signed = false;
    hidden.value = "";
    placeholder.hidden = false;
  }
  clear.addEventListener("click", clearSignature);
  function syncMode() {
    digital.hidden = paper.checked;
    notice.hidden = !paper.checked;
    confirmation.hidden = paper.checked;
    confirmed.required = !paper.checked;
    confirmed.disabled = paper.checked;
    confirmed.checked = false;
    clearSignature();
    resize();
  }
  if (paper) paper.addEventListener("change", syncMode);
  form.addEventListener("submit", (event) => {
    if (paper?.checked) {
      hidden.value = "";
      return;
    }
    if (!signed) {
      event.preventDefault();
      canvas.focus();
      window.alert("Solicite a assinatura do colaborador antes de concluir.");
      return;
    }
    hidden.value = canvas.toDataURL("image/png");
  });
  window.addEventListener("resize", resize);
  // O servidor pode manter o formulário anterior em cache até o reinício.
  if (paper) syncMode();
  else resize();
});
