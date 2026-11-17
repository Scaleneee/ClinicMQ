// Ask before destructive actions (UI.md §7).
// A form with data-confirm-title opens the shared modal in _confirm_modal.html;
// it is only sent after the user presses the confirm button.
(function () {
  var pending = null;

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.dataset || !form.dataset.confirmTitle || form.dataset.confirmed === "yes") {
      return;
    }
    event.preventDefault();
    pending = form;
    document.getElementById("cmqConfirmTitle").textContent = form.dataset.confirmTitle;
    document.getElementById("cmqConfirmText").textContent = form.dataset.confirmText || "";
    document.getElementById("cmqConfirmOk").textContent = form.dataset.confirmButton || "Confirm";
    bootstrap.Modal.getOrCreateInstance(document.getElementById("cmqConfirm")).show();
  }, true);

  document.addEventListener("click", function (event) {
    if (event.target.id !== "cmqConfirmOk" || !pending) {
      return;
    }
    var form = pending;
    pending = null;
    form.dataset.confirmed = "yes";
    bootstrap.Modal.getInstance(document.getElementById("cmqConfirm")).hide();
    form.requestSubmit ? form.requestSubmit() : form.submit();
  });
})();
