/* Centralized HTTP client for the graphical editor. */
(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverApiClient = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  function EditorApiError(message, options) {
    options = options || {};
    this.name = 'EditorApiError';
    this.message = String(message || 'The editor request failed.');
    this.status = Number(options.status || 0);
    this.code = String(options.code || 'request_failed');
    this.details = options.details || {};
    this.requestId = options.requestId || null;
    if (Error.captureStackTrace) Error.captureStackTrace(this, EditorApiError);
  }
  EditorApiError.prototype = Object.create(Error.prototype);
  EditorApiError.prototype.constructor = EditorApiError;

  function defaultRequestId() {
    if (root.crypto && typeof root.crypto.randomUUID === 'function') {
      return root.crypto.randomUUID();
    }
    return 'editor-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
  }

  function discoverCsrfToken() {
    if (!root.document) return null;
    var meta = root.document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    var input = root.document.querySelector('input[name="csrf_token"]');
    if (input && input.value) return input.value;
    var match = String(root.document.cookie || '').match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }

  function requestKey(method, path) {
    try {
      return method + ':' + new URL(path, 'http://editor.invalid').pathname;
    } catch (_error) {
      return method + ':' + String(path).split('?')[0];
    }
  }

  function resolveUrl(baseUrl, path) {
    var value = String(path || '');
    if (/^https?:\/\//i.test(value)) return value;
    if (baseUrl && value.indexOf(baseUrl + '/') === 0) return value;
    return baseUrl + value;
  }

  function createClient(options) {
    options = options || {};
    var baseUrl = options.baseUrl || '';
    var fetchImpl = options.fetchImpl || root.fetch;
    var onError = typeof options.onError === 'function' ? options.onError : null;
    var requestIdFactory = options.requestIdFactory || defaultRequestId;
    var timeoutMs = Number(options.timeoutMs || 30000);
    var sequences = {};
    var controllers = {};

    if (typeof fetchImpl !== 'function') {
      throw new Error('A fetch implementation is required');
    }

    function emit(error) {
      if (onError && error.code !== 'stale_response' && error.code !== 'request_cancelled') {
        onError(error);
      }
      return error;
    }

    function request(method, path, body, requestOptions) {
      requestOptions = requestOptions || {};
      var key = requestOptions.staleKey || requestKey(method, path);
      var preventStale = requestOptions.preventStale !== undefined
        ? Boolean(requestOptions.preventStale)
        : (method === 'GET' || method === 'HEAD');
      var sequence = preventStale ? (sequences[key] || 0) + 1 : 0;
      if (preventStale) sequences[key] = sequence;
      if (preventStale && controllers[key] && requestOptions.cancelPrevious !== false) {
        controllers[key].abort();
      }

      var AbortControllerImpl = root.AbortController;
      var controller = typeof AbortControllerImpl === 'function' ? new AbortControllerImpl() : null;
      if (controller && preventStale) controllers[key] = controller;
      var timedOut = false;
      var requestId = requestIdFactory();
      var headers = Object.assign({}, requestOptions.headers || {});
      headers['X-Request-ID'] = requestId;
      var csrfToken = options.csrfToken || discoverCsrfToken();
      if (method !== 'GET' && method !== 'HEAD' && csrfToken) {
        headers['X-CSRF-Token'] = csrfToken;
      }
      var fetchOptions = {
        method: method,
        credentials: 'same-origin',
        headers: headers,
      };
      if (body !== undefined) {
        if (requestOptions.json === false) {
          fetchOptions.body = body;
        } else {
          headers['Content-Type'] = 'application/json';
          fetchOptions.body = JSON.stringify(body);
        }
      }
      if (controller) fetchOptions.signal = controller.signal;

      var timeout = controller && timeoutMs > 0
        ? setTimeout(function () {
          timedOut = true;
          controller.abort();
        }, timeoutMs)
        : null;

      return Promise.resolve()
        .then(function () {
          return fetchImpl(resolveUrl(baseUrl, path), fetchOptions);
        })
        .catch(function (cause) {
          if (preventStale && sequences[key] !== sequence) {
            throw new EditorApiError('A newer response replaced this request.', {
              code: 'stale_response', requestId: requestId,
            });
          }
          var cancelled = cause && cause.name === 'AbortError';
          throw emit(new EditorApiError(
            timedOut ? 'The editor server took too long to respond.' :
              (cancelled ? 'The request was cancelled.' : 'Unable to reach the editor server.'),
            {
              code: timedOut ? 'request_timeout' : (cancelled ? 'request_cancelled' : 'network_error'),
              requestId: requestId,
              details: { cause: cause && cause.message ? cause.message : String(cause || '') },
            }
          ));
        })
        .then(function (response) {
          return response.text().then(function (text) {
            if (preventStale && sequences[key] !== sequence) {
              throw new EditorApiError('A newer response replaced this request.', {
                code: 'stale_response', requestId: requestId,
              });
            }
            var contentType = response.headers.get('content-type') || '';
            if (contentType.toLowerCase().indexOf('json') === -1) {
              throw emit(new EditorApiError('The server returned an unexpected response type.', {
                status: response.status,
                code: 'invalid_content_type',
                requestId: requestId,
                details: { contentType: contentType },
              }));
            }
            var payload;
            try {
              payload = text ? JSON.parse(text) : null;
            } catch (_error) {
              throw emit(new EditorApiError('The server returned invalid JSON.', {
                status: response.status,
                code: 'invalid_json',
                requestId: requestId,
              }));
            }
            if (!response.ok || !payload || payload.success === false) {
              var serverError = payload && payload.error ? payload.error : (payload || {});
              var serverMessage = typeof serverError === 'string' ? serverError : serverError.message;
              var serverCode = typeof serverError === 'object' && serverError
                ? (serverError.code || serverError.type)
                : null;
              var serverDetails = typeof serverError === 'object' && serverError
                ? (serverError.details || serverError)
                : {};
              throw emit(new EditorApiError(serverMessage || ('Request failed with status ' + response.status + '.'), {
                status: response.status,
                code: serverCode || 'http_error',
                details: serverDetails,
                requestId: payload && payload.request_id ? payload.request_id : requestId,
              }));
            }
            if (requestOptions.includeResponse) {
              return {
                body: payload,
                status: response.status,
                contentType: contentType,
              };
            }
            return payload;
          });
        })
        .finally(function () {
          if (timeout) clearTimeout(timeout);
          if (preventStale && controllers[key] === controller) delete controllers[key];
        });
    }

    return {
      get: function (path, requestOptions) {
        return request('GET', path, undefined, requestOptions);
      },
      post: function (path, body, requestOptions) {
        return request('POST', path, body, requestOptions);
      },
      upload: function (path, formData, requestOptions) {
        requestOptions = Object.assign({}, requestOptions || {}, { json: false });
        return request('POST', path, formData, requestOptions);
      },
      getDetailed: function (path, requestOptions) {
        requestOptions = Object.assign({}, requestOptions || {}, { includeResponse: true });
        return request('GET', path, undefined, requestOptions);
      },
      uploadDetailed: function (path, formData, requestOptions) {
        requestOptions = Object.assign({}, requestOptions || {}, {
          includeResponse: true,
          json: false,
        });
        return request('POST', path, formData, requestOptions);
      },
      cancel: function (key) {
        if (controllers[key]) controllers[key].abort();
      },
    };
  }

  return {
    EditorApiError: EditorApiError,
    createClient: createClient,
  };
});
