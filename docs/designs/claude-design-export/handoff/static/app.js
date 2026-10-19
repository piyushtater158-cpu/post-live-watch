/* Post-Live Watch — client behaviour. All handlers are delegated from
   document, so they keep working after HTMX swaps #queue-list. */
(function () {
  'use strict';

  // ---- 1. Table sort (fix #3) -------------------------------------------
  // Sorts by a cell's data-sort-value when present (status rank, severity),
  // otherwise by its text. Numbers compare numerically.
  function cellKey(row, idx) {
    var cell = row.children[idx];
    if (!cell) return '';
    var v = cell.hasAttribute('data-sort-value') ? cell.getAttribute('data-sort-value') : cell.textContent.trim();
    var n = parseFloat(String(v).replace(/,/g, ''));
    return isNaN(n) ? String(v).toLowerCase() : n;
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('table[data-sortable] .sort');
    if (!btn) return;
    var th = btn.closest('th');
    var table = th.closest('table');
    var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
    var next = th.getAttribute('aria-sort') === 'descending' ? 'ascending' : 'descending';
    table.querySelectorAll('th[aria-sort]').forEach(function (h) { h.removeAttribute('aria-sort'); });
    th.setAttribute('aria-sort', next);
    var dir = next === 'ascending' ? 1 : -1;
    var tbody = table.tBodies[0];
    Array.prototype.slice.call(tbody.rows)
      .sort(function (a, b) {
        var x = cellKey(a, idx), y = cellKey(b, idx);
        if (typeof x !== typeof y) { x = String(x); y = String(y); }
        return x < y ? -dir : x > y ? dir : 0;
      })
      .forEach(function (r) { tbody.appendChild(r); });
  });

  // ---- 2. Edit & Approve only when the text changed (fix #2) -------------
  // Approve  -> sends the suggestion exactly as written (textarea reset to original).
  // Edit & Approve -> enabled only once the textarea differs from original_message.
  function syncEdit(form) {
    var ta = form.querySelector('textarea[name="message_text"]');
    var orig = form.querySelector('input[name="original_message"]');
    var edit = form.querySelector('button[value="edit"]');
    if (!ta || !orig || !edit) return;
    edit.disabled = ta.value.trim() === orig.value.trim();
  }
  document.addEventListener('input', function (e) {
    var form = e.target.closest('form.decide');
    if (form) syncEdit(form);
  });
  document.addEventListener('click', function (e) {
    var approve = e.target.closest('form.decide button[value="approve"]');
    if (!approve) return;
    var form = approve.closest('form');
    var ta = form.querySelector('textarea[name="message_text"]');
    var orig = form.querySelector('input[name="original_message"]');
    if (ta && orig) ta.value = orig.value;
  }, true);
  function syncAll(root) { (root || document).querySelectorAll('form.decide').forEach(syncEdit); }
  document.addEventListener('DOMContentLoaded', function () { syncAll(); });
  document.addEventListener('htmx:afterSwap', function (e) { syncAll(e.target); });

  // ---- 3. Copy to clipboard ------------------------------------------------
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-action="copy"]');
    if (!btn) return;
    var ta = btn.closest('form').querySelector('textarea');
    if (!ta) return;
    var label = btn.querySelector('.copy-label');
    var done = function () {
      if (!label) return;
      label.textContent = 'Copied';
      setTimeout(function () { label.textContent = 'Copy'; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(ta.value).then(done, function () { ta.select(); document.execCommand('copy'); done(); });
    } else { ta.select(); document.execCommand('copy'); done(); }
  });
})();
