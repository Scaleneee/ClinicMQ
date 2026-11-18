// Date boxes show and accept dd/mm/yyyy on every page.
// The browser's own date box follows the computer's language (e.g. mm/dd/yyyy), so it is
// replaced by flatpickr. The hidden real box still sends yyyy-mm-dd, so the server is unchanged.
(function () {
  if (!window.flatpickr) return; // CDN blocked: keep the browser's own date box

  document.querySelectorAll('input[type="date"]').forEach(function (input) {
    var label = input.id && document.querySelector('label[for="' + input.id + '"]');
    flatpickr(input, {
      dateFormat: "Y-m-d",   // what the form sends
      altInput: true,
      altFormat: "d/m/Y",    // what people see and type
      altInputClass: "cmq-date-input",
      allowInput: true,
      disableMobile: true,   // phones too, so every device shows dd/mm/yyyy
      minDate: input.min || null,
      maxDate: input.max || null,
      onReady: function (_dates, _str, fp) {
        fp.altInput.placeholder = "dd/mm/yyyy";
        fp.altInput.autocomplete = "off";
        if (label) fp.altInput.setAttribute("aria-label", label.textContent.trim());
        if (input.autofocus) fp.altInput.focus();
      },
    });
  });
})();
