"use strict";
(function () {
  // Toggle visibility of the per-platform field group based on the radio.
  var radios = document.querySelectorAll('input[name="platform"]');
  function refresh() {
    var selected = document.querySelector('input[name="platform"]:checked');
    var value = selected ? selected.value : 'smartzone';
    document.querySelectorAll('[data-platform-fields]').forEach(function (el) {
      if (el.getAttribute('data-platform-fields') === value) {
        el.classList.remove('hidden');
      } else {
        el.classList.add('hidden');
      }
    });
  }
  radios.forEach(function (r) { r.addEventListener('change', refresh); });
  refresh();
})();
