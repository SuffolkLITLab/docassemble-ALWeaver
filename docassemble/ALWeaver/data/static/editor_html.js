/* HTML serialization helpers shared by the graphical editor and its tests. */
(function (/** @type {any} */ root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverEditorHtml = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /**
   * Escape text that will be interpolated into HTML, including quoted
   * attributes such as title and data-bs-content.
   */
  function escapeAttribute(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  return {
    escapeAttribute: escapeAttribute,
  };
});
