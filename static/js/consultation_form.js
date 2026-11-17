// New / edit consultation: add and remove prescription rows, live amounts and total,
// stock warning, and show the MC fields only when "Issue MC" is ticked.
(function () {
  var rows = document.getElementById("rx-rows");
  var template = document.getElementById("rx-row-template");
  var addBtn = document.getElementById("rx-add");
  var fee = document.getElementById("id_consult_fee");
  var issueMc = document.getElementById("id_issue_mc");
  var mcFields = document.getElementById("mc-fields");

  function money(n) { return "RM " + n.toFixed(2); }

  function priceOf(row) {
    var select = row.querySelector(".rx-med");
    if (select) {
      var opt = select.options[select.selectedIndex];
      return opt && opt.dataset.price ? parseFloat(opt.dataset.price) : null;
    }
    var fixed = row.querySelector("[data-price]");
    return fixed ? parseFloat(fixed.dataset.price) : null;
  }

  function update() {
    var subtotal = 0;
    rows.querySelectorAll(".cmq-rx-row").forEach(function (row) {
      var price = priceOf(row);
      var qty = parseInt((row.querySelector(".rx-qty") || {}).value, 10) || 0;
      row.querySelector(".rx-price").textContent = price === null ? "–" : money(price);
      var amount = price === null ? 0 : price * qty;
      row.querySelector(".rx-amount").textContent = price === null || !qty ? "–" : money(amount);
      subtotal += amount;

      // stock warning: more prescribed than in stock
      var select = row.querySelector(".rx-med");
      var warn = row.querySelector(".rx-stock-warning");
      if (select && warn) {
        var opt = select.options[select.selectedIndex];
        var stock = opt && opt.dataset.stock ? parseInt(opt.dataset.stock, 10) : null;
        if (stock !== null && qty > stock) {
          warn.textContent = "Only " + stock + " " + opt.dataset.unit + " in stock.";
          warn.hidden = false;
        } else {
          warn.hidden = true;
        }
      }
    });
    document.getElementById("rx-subtotal").textContent = money(subtotal);
    var feeValue = parseFloat(fee && fee.value) || 0;
    document.getElementById("grand-total").textContent = money(subtotal + feeValue);
    document.getElementById("rx-empty").hidden = rows.querySelector(".cmq-rx-row") !== null;
  }

  if (addBtn) {
    addBtn.addEventListener("click", function () {
      rows.appendChild(template.content.cloneNode(true));
      var added = rows.lastElementChild;
      added.querySelector(".rx-med").focus();
      update();
    });
  }

  rows.addEventListener("click", function (event) {
    var btn = event.target.closest(".rx-remove");
    if (btn) {
      btn.closest("tr").remove();
      update();
    }
  });
  rows.addEventListener("input", update);
  rows.addEventListener("change", update);
  if (fee) { fee.addEventListener("input", update); }

  function syncMc() { mcFields.hidden = !issueMc.checked; }
  issueMc.addEventListener("change", syncMc);
  syncMc();

  // Start with one empty row on a new consultation
  if (addBtn && !rows.querySelector(".cmq-rx-row")) { addBtn.click(); }
  update();
})();
