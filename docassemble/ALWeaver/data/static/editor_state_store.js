/* Central state container for the graphical editor. */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverStateStore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function clone(value) {
    if (value === undefined) return undefined;
    return JSON.parse(JSON.stringify(value));
  }

  function createInitialState(overrides) {
    return Object.assign({
      projects: [],
      project: null,
      files: [],
      filename: null,
      blocks: [],
      metadataIndices: [],
      includeIndices: [],
      defaultSpIndices: [],
      orderIndices: [],
      orderSteps: [],
      orderStepMap: {},
      activeOrderBlockId: null,
      orderBuilderLoading: false,
      orderDirty: false,
      orderCollapsed: {},
      selectedOrderStepIds: {},
      symbolCatalog: {
        loadedFor: null,
        all: [],
        topLevel: [],
        groups: {},
      },
      rawYaml: '',
      revision: null,
      metadataRawYaml: '',
      selectedBlockId: null,
      currentView: 'interview',
      canvasMode: 'project-selector',
      questionEditMode: 'preview',
      questionBlockTab: 'screen',
      advancedOpen: false,
      advancedShowMore: false,
      reviewMetaOpen: false,
      openReviewItemIndex: null,
      jumpTarget: 'questions',
      fullYamlTab: 'full',
      searchQuery: '',
      projectSearchQuery: '',
      sectionFiles: {
        templates: [],
        modules: [],
        static: [],
        data: [],
      },
      sectionSelectedFile: {
        templates: null,
        modules: null,
        static: null,
        data: null,
      },
      sectionDirty: false,
      sectionSavedContent: {},
      markdownPreviewMode: false,
      insertAfterBlockId: null,
      fullYamlStash: {},
      validationErrors: [],
      validationOpen: false,
      validationMode: 'validation',
      validationSourceScope: 'saved_source',
      validationBaseRevisionMatches: null,
      runtimeTargetSession: null,
      requests: {},
      dialogs: {},
      notifications: [],
    }, clone(overrides || {}));
  }

  function defaultReducer(state, action) {
    if (!action || typeof action.type !== 'string') {
      throw new TypeError('State actions require a type.');
    }
    if (action.type === 'merge') {
      return Object.assign({}, state, clone(action.value || {}));
    }
    if (action.type === 'replace') {
      return createInitialState(action.value || {});
    }
    return state;
  }

  function createStore(initialState, reducer) {
    var currentState = initialState || createInitialState();
    var reduce = reducer || defaultReducer;
    var subscribers = [];

    function notify(action) {
      subscribers.slice().forEach(function (subscriber) {
        subscriber(currentState, action);
      });
    }

    return {
      getState: function () { return currentState; },
      getSnapshot: function () { return clone(currentState); },
      dispatch: function (action) {
        var nextState = reduce(currentState, action);
        if (!nextState || typeof nextState !== 'object') {
          throw new TypeError('The state reducer must return an object.');
        }
        if (nextState !== currentState) {
          currentState = nextState;
          notify(action);
        }
        return action;
      },
      mutateLegacy: function (mutator, description) {
        if (typeof mutator !== 'function') throw new TypeError('A state mutator is required.');
        mutator(currentState);
        notify({ type: 'legacy-mutation', description: description || '' });
      },
      subscribe: function (subscriber) {
        if (typeof subscriber !== 'function') throw new TypeError('A subscriber is required.');
        subscribers.push(subscriber);
        return {
          dispose: function () {
            subscribers = subscribers.filter(function (candidate) {
              return candidate !== subscriber;
            });
          },
        };
      },
    };
  }

  function createEditorStore(overrides) {
    return createStore(createInitialState(overrides));
  }

  return {
    createInitialState: createInitialState,
    createStore: createStore,
    createEditorStore: createEditorStore,
  };
});
