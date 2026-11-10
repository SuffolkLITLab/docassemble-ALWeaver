/* Render large reports without blocking the editor's UI thread. */
'use strict';
importScripts('editor_screen_preview.js', 'editor_interview_report.js');
self.onmessage = function (event) {
  try {
    var data = event.data;
    self.postMessage({html: self.ALWeaverInterviewReport.buildReport(data.steps, data.blocks, data.options)});
  } catch (error) {
    self.postMessage({error: error.message || String(error)});
  }
};
