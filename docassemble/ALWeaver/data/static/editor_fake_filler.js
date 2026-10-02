/* Faker sample answers adapted to Docassemble's field shapes and validation. */
(function (/** @type {any} */ root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports && !root.ALWeaverFaker) {
    var fakerBundle = './faker_en_us.js';
    require(fakerBundle);
  }
  var api = factory(root.ALWeaverFaker);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ALWeaverFakeFiller = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (faker) {
  'use strict';

  function createSampleData() {
    var people = new Map();
    var addresses = new Map();
    var phones = new Map();
    function addressKey(variable) {
      var marker = variable.indexOf('.address.');
      return marker >= 0
        ? variable.slice(0, marker + 8)
        : variable.replace(/\.[^.]+$/, '');
    }
    function person(variable) {
      var marker = variable.indexOf('.name');
      var key =
        marker >= 0
          ? variable.slice(0, marker)
          : variable.replace(/\.[^.]+$/, '');
      if (!people.has(key))
        people.set(key, {
          first: faker.person.firstName(),
          middle: faker.person.firstName(),
          last: faker.person.lastName(),
        });
      return people.get(key);
    }
    function address(variable) {
      var key = addressKey(variable);
      if (!addresses.has(key)) {
        var state = faker.location.state({ abbreviated: true });
        addresses.set(key, {
          address: faker.location.streetAddress(),
          unit: faker.string.numeric({
            length: { min: 1, max: 3 },
            allowLeadingZeros: false,
          }),
          city: faker.location.city(),
          state: state,
          zip: zipCode(state),
          country: 'US',
        });
      }
      return addresses.get(key);
    }
    function zipCode(state) {
      try {
        return faker.location.zipCode({ state: state });
      } catch {
        // Faker knows only the 50 states; D.C., territories and provinces throw.
        return faker.location.zipCode();
      }
    }
    function stateCode(value) {
      var index = faker.definitions.location.state.findIndex(function (name) {
        return name.toLowerCase() === value.toLowerCase();
      });
      return index >= 0
        ? faker.definitions.location.state_abbr[index]
        : value.toUpperCase();
    }
    function seedAddress(variable, part, value) {
      var record = address(variable);
      if (part === 'state') {
        record.state = stateCode(value);
        record.zip = zipCode(record.state);
      } else record[part] = value;
    }
    function phone(variable) {
      if (!phones.has(variable))
        phones.set(
          variable,
          faker.helpers.arrayElement(faker.definitions.phone_number.area_code) +
            faker.helpers.arrayElement(
              faker.definitions.phone_number.exchange_code,
            ) +
            faker.string.numeric(4),
        );
      return phones.get(variable);
    }
    return {
      person: person,
      address: address,
      phone: phone,
      seedAddress: seedAddress,
    };
  }

  var formSamples = new WeakMap();

  function decode(value, view) {
    try {
      return view.atob(value);
    } catch {
      return value;
    }
  }

  function metadata(form, name) {
    var input = form.querySelector('input[name="' + name + '"]');
    try {
      return input
        ? JSON.parse(decode(input.value, form.ownerDocument.defaultView))
        : {};
    } catch {
      return {};
    }
  }

  function fieldInfo(field, names, types) {
    var view = field.ownerDocument.defaultView;
    var encoded = names[field.name] || field.name || field.id;
    var variable = decode(encoded || '', view);
    // ALToolbox's three-part dates (BirthDate, ThreePartsDate) name each part
    // _ignore_<encoded variable>_<part>.
    var datePart = /^_ignore_(.+)_(day|month|year)$/.exec(encoded || '');
    if (datePart) variable = decode(datePart[1], view) + '.' + datePart[2];
    // Standard list questions use users[i]; the sought variable names the
    // concrete item. Keep that person's data together across screens.
    var sought = field.ownerDocument.querySelector('#sought_variable');
    var concrete =
      sought && decode(sought.getAttribute('data-variable') || '', view);
    var indexed = concrete && concrete.match(/^(\w+)\[(\d+)\]/);
    if (indexed && variable.startsWith(indexed[1] + '['))
      variable = variable.replace(/\[[ijk]\]/, '[' + indexed[2] + ']');
    var labels = Array.from(field.labels || []).map(function (label) {
      return label.textContent;
    });
    return {
      variable: variable.toLowerCase(),
      label: labels.join(' ').toLowerCase(),
      datatype: types[encoded] || types[field.name] || field.type,
    };
  }

  function visible(field) {
    if (field.disabled || field.readOnly || field.type === 'hidden')
      return false;
    if (field.closest('[hidden], .d-none')) return false;
    var view = field.ownerDocument.defaultView;
    // Labelauty and select widgets visually hide the native control. Inspect
    // their visible label/widget, while respecting conditional containers.
    var target = field;
    if (field.type === 'radio' || field.type === 'checkbox') {
      target = (field.labels && field.labels[0]) || field;
    } else if (field.tagName === 'SELECT' && !field.getClientRects().length) {
      target = field.closest('.da-field-container') || field.parentElement;
    }
    return (
      target.getClientRects().length > 0 &&
      view.getComputedStyle(target).visibility !== 'hidden'
    );
  }

  function numericValue(field, datatype) {
    var rules = fieldRules(field);
    var minimum = Number(rules.min);
    var maximum = Number(rules.max);
    var lower = Number.isFinite(minimum) ? minimum : 1;
    var defaultUpper = datatype === 'currency' ? 5000 : 5;
    var upper = Number.isFinite(maximum)
      ? maximum
      : Math.max(lower, defaultUpper);
    lower = Math.min(lower, upper);
    // Only money gets cents. Other numbers (a day, a count, an age) are whole
    // unless the field's own limits leave no whole number to choose.
    var value;
    if (datatype === 'currency')
      value = Number(faker.finance.amount({ min: lower, max: upper, dec: 2 }));
    else if (Math.ceil(lower) <= Math.floor(upper))
      value = faker.number.int({
        min: Math.ceil(lower),
        max: Math.floor(upper),
      });
    else
      value = faker.number.float({ min: lower, max: upper, fractionDigits: 2 });
    value = Math.max(lower, Math.min(upper, value));
    var step = Number(rules.step);
    if (step > 0) {
      var base = Number.isFinite(minimum) ? minimum : 0;
      value = base + Math.round((value - base) / step) * step;
      if (Number.isFinite(maximum) && value > maximum) value -= step;
    }
    return String(Number(value.toFixed(10)));
  }

  function fieldRules(field) {
    // Docassemble keeps most YAML limits in its validation settings instead
    // of HTML attributes. Read those settings without depending on jQuery.
    var view = field.ownerDocument && field.ownerDocument.defaultView;
    var settings = view && view.daValidationRules;
    var rules = Object.assign(
      {},
      settings && settings.rules && settings.rules[field.name],
    );
    ['min', 'max', 'step', 'minlength', 'maxlength'].forEach(function (name) {
      if (field.hasAttribute(name)) rules[name] = field.getAttribute(name);
    });
    if (Array.isArray(rules.range)) {
      rules.min = rules.range[0];
      rules.max = rules.range[1];
    }
    return rules;
  }

  function identifierDigitCount(info) {
    var hint = (info.variable + ' ' + info.label).replace(/_/g, ' ');
    var lastDigits = hint.match(/\b(?:last|final)\s*(\d{1,2}|four)\b/);
    if (!lastDigits) return 0;
    // A text datatype can still represent a numeric identifier. Preserve
    // leading zeroes and do not interpret ordinary four-character text as one.
    var numericIdentifier =
      /\bdigits?\b|\bssn\b|social security|\bphone\b|\bmobile\b|\bfax\b|\baccount\b|\bcard\b/.test(
        hint,
      ) || /\b(?:last|final)\s*(?:\d{1,2}|four)\s+of\s+social\b/.test(hint);
    if (!numericIdentifier) return 0;
    var count = lastDigits[1] === 'four' ? 4 : Number(lastDigits[1]);
    return count > 0 && count <= 32 ? count : 0;
  }

  function sampleValue(field, info, samples) {
    samples = samples || createSampleData();
    var variable = info.variable;
    var label = info.label;
    var hint = variable + ' ' + label;
    var datatype = info.datatype;
    if (field.classList.contains('dacurrency') || datatype === 'currency')
      return numericValue(field, 'currency');
    var digits = identifierDigitCount(info);
    if (digits) return faker.string.numeric(digits);
    // The input's type wins over guesses from its name: an integer field named
    // years_at_address must not get a street address.
    if (/^(date|datetime|datetime-local|time|month|week)$/.test(datatype)) {
      var generated = /birth|dob/.test(hint)
        ? faker.date.birthdate({ min: 18, max: 80, mode: 'age' })
        : faker.date.past({ years: 2 });
      var iso = generated.toISOString();
      var dates = {
        date: iso.slice(0, 10),
        datetime: iso.slice(0, 16),
        'datetime-local': iso.slice(0, 16),
        time: iso.slice(11, 16),
        month: iso.slice(0, 7),
        week:
          iso.slice(0, 4) +
          '-W' +
          String(faker.number.int({ min: 1, max: 52 })).padStart(2, '0'),
      };
      var date = dates[datatype];
      if (field.min && date < field.min) date = field.min;
      if (field.max && date > field.max) date = field.max;
      return date;
    }
    // A year, not a count of years: years_at_address wants a small number.
    if (/(^|[^a-z])year([^a-z]|$)/i.test(hint)) {
      var thisYear = new Date().getFullYear();
      // Match the birth dates above: an adult, 18 to 80 years old.
      return String(
        /birth|dob/.test(hint)
          ? faker.number.int({ min: thisYear - 80, max: thisYear - 18 })
          : faker.number.int({ min: thisYear - 10, max: thisYear }),
      );
    }
    if (/^(number|float|integer|range)$/.test(datatype))
      return numericValue(field, datatype);
    if (/zip|postal/.test(hint)) return samples.address(variable).zip;
    if (/\bcountry\b/.test(hint)) return samples.address(variable).country;
    if (/\bstate\b|province/.test(hint)) return samples.address(variable).state;
    if (/\bcity\b|\btown\b/.test(hint)) return samples.address(variable).city;
    if (/email/.test(hint) || field.type === 'email')
      return faker.internet.email({
        firstName: samples.person(variable).first,
        lastName: samples.person(variable).last,
        provider: 'example.com',
      });
    if (/phone|mobile|fax/.test(hint) || field.type === 'tel')
      return samples.phone(variable);
    if (/unit|apartment|\bapt\b|suite/.test(hint))
      return samples.address(variable).unit;
    if (/address.*one_line|address.*one line/.test(hint)) {
      var address = samples.address(variable);
      return [
        address.address,
        address.city,
        address.state + ' ' + address.zip,
      ].join(', ');
    }
    if (/address|street/.test(hint)) return samples.address(variable).address;
    if (/name\.first|first_name|first name|given name/.test(hint))
      return samples.person(variable).first;
    if (/name\.last|last_name|last name|surname/.test(hint))
      return samples.person(variable).last;
    if (/middle/.test(hint)) return samples.person(variable).middle;
    if (/name/.test(hint))
      return (
        samples.person(variable).first + ' ' + samples.person(variable).last
      );
    if (field.type === 'url') return faker.internet.url();
    // Only a hint: zip and phone inputs also ask for a numeric keyboard.
    if (
      field.classList.contains('danumeric') ||
      /^(numeric|decimal)$/.test(field.inputMode)
    )
      return numericValue(
        field,
        field.inputMode === 'numeric' ? 'integer' : datatype,
      );
    var value =
      field.tagName === 'TEXTAREA'
        ? faker.lorem.sentences(2)
        : faker.word.words(3);
    return limitLength(field, value);
  }

  function limitLength(field, value) {
    var rules = fieldRules(field);
    var minLength = Number(rules.minlength ?? field.minLength);
    var maxLength = Number(rules.maxlength ?? field.maxLength);
    if (minLength > value.length) value = value.padEnd(minLength, 'x');
    if (maxLength >= 0) value = value.slice(0, maxLength);
    return value;
  }

  function notify(field) {
    var view = field.ownerDocument.defaultView;
    ['input', 'change', 'blur'].forEach(function (name) {
      field.dispatchEvent(new view.Event(name, { bubbles: true }));
    });
  }

  function fillSelect(field, info, samples) {
    if (
      field.multiple
        ? Array.from(field.selectedOptions).some(function (option) {
            return option.value;
          })
        : field.value
    )
      return 0;
    var options = Array.from(field.options).filter(function (option) {
      return option.value && !option.disabled && !option.parentElement.disabled;
    });
    var preferred = sampleValue(field, info, samples).toLowerCase();
    var stateIndex = faker.definitions.location.state_abbr.indexOf(
      preferred.toUpperCase(),
    );
    var stateName =
      stateIndex >= 0
        ? faker.definitions.location.state[stateIndex].toLowerCase()
        : '';
    var option =
      options.find(function (item) {
        var text = item.textContent.trim().toLowerCase();
        return (
          item.value.toLowerCase() === preferred ||
          text === preferred ||
          text === stateName ||
          (preferred === 'us' && text === 'united states')
        );
      }) || options[0];
    if (!option) return 0;
    option.selected = true;
    notify(field);
    return 1;
  }

  function fillField(field, form, names, types, samples) {
    if (!visible(field)) return 0;
    var info = fieldInfo(field, names, types);
    if (field.tagName === 'SELECT') return fillSelect(field, info, samples);
    if (field.type === 'radio') {
      var group = Array.from(
        form.querySelectorAll('input[type="radio"]'),
      ).filter(function (item) {
        return item.name === field.name;
      });
      if (
        group.some(function (item) {
          return item.checked;
        })
      )
        return 0;
      // Finish list gathering instead of endlessly creating another item.
      var choice = /there_is_another|there_are_any/.test(info.variable)
        ? group.find(function (item) {
            return item.value === 'False';
          }) || field
        : field;
      choice.checked = true;
      notify(choice);
      return 1;
    }
    if (field.type === 'checkbox') {
      if (field.checked || field.classList.contains('danone')) return 0;
      var container = field.closest(
        '.da-field-checkboxes, .da-field-object_checkboxes',
      );
      if (container && container.querySelector('input:checked')) return 0;
      field.checked = true;
      notify(field);
      return 1;
    }
    if (
      /^(file|button|submit|reset|image|color)$/.test(field.type) ||
      field.value
    )
      return 0;
    field.value = limitLength(field, sampleValue(field, info, samples));
    notify(field);
    return 1;
  }

  function fillForm(form, samples) {
    var names = metadata(form, '_varnames');
    var types = metadata(form, '_datatypes');
    samples = samples || formSamples.get(form) || createSampleData();
    formSamples.set(form, samples);
    // Respect supplied address parts, especially the interview's state default.
    var fields = Array.from(form.querySelectorAll('input, textarea, select'));
    fields.sort(function (left, right) {
      // Seed defaults before other parts so a supplied ZIP always wins.
      return (
        Number(/\.state$/.test(fieldInfo(right, names, types).variable)) -
        Number(/\.state$/.test(fieldInfo(left, names, types).variable))
      );
    });
    fields.forEach(function (field) {
      if (!field.value || field.type === 'hidden' || !visible(field)) return;
      var info = fieldInfo(field, names, types);
      var part = info.variable.match(
        /\.address\.(address|unit|city|state|zip|country)$/,
      );
      if (part) samples.seedAddress(info.variable, part[1], field.value);
    });
    var total = 0;
    // Change handlers can reveal additional fields on this same screen.
    for (var pass = 0; pass < 10; pass += 1) {
      var count = 0;
      Array.from(form.querySelectorAll('input, textarea, select')).forEach(
        function (field) {
          count += fillField(field, form, names, types, samples);
        },
      );
      total += count;
      if (!count) break;
    }
    var manual = Array.from(form.querySelectorAll('input[type="file"]')).some(
      function (field) {
        return visible(field) && !field.value;
      },
    );
    return { count: total, manual: manual };
  }

  function submitButton(form) {
    return Array.from(
      form.querySelectorAll('button[type="submit"], input[type="submit"]'),
    ).find(function (button) {
      return (
        visible(button) && !button.classList.contains('daquestionbackbutton')
      );
    });
  }

  function createController(frame, button, onStatus) {
    var samples = createSampleData();
    var filledForm = null;
    var observer = null;
    var disposed = false;

    function getForm() {
      try {
        return (
          frame.contentDocument &&
          frame.contentDocument.querySelector('#daform')
        );
      } catch {
        return null;
      }
    }

    function refresh() {
      var form = getForm();
      if (form !== filledForm) filledForm = null;
      button.textContent = filledForm ? 'Continue' : 'Fill sample answers';
      button.disabled = !form || !submitButton(form);
      button.title = button.disabled
        ? "Use the interview's controls on this screen."
        : 'Fill unanswered fields with sample data, then click again to continue.';
    }

    function attach() {
      if (disposed) return;
      if (observer) observer.disconnect();
      filledForm = null;
      refresh();
      if (frame.contentDocument) {
        observer = new frame.contentWindow.MutationObserver(refresh);
        observer.observe(frame.contentDocument, {
          childList: true,
          subtree: true,
        });
      }
    }

    function click() {
      var form = getForm();
      if (!form) return;
      if (filledForm === form) {
        // A real click preserves Docassemble's submitter values, AJAX, and
        // client/server validation. Never call form.submit() to bypass them.
        var submit = submitButton(form);
        if (submit) submit.click();
        onStatus(
          'Continue requested. Check the interview for any validation messages.',
        );
      } else {
        var result = fillForm(form, samples);
        filledForm = form;
        onStatus(
          'Sample answers filled. Review them, then click Continue.' +
            (result.manual
              ? ' Choose a file manually for the upload field.'
              : ''),
        );
      }
      refresh();
    }

    button.addEventListener('click', click);
    frame.addEventListener('load', attach);
    attach();
    return {
      dispose: function () {
        disposed = true;
        if (observer) observer.disconnect();
        frame.removeEventListener('load', attach);
        button.removeEventListener('click', click);
      },
    };
  }

  return {
    createSampleData: createSampleData,
    sampleValue: sampleValue,
    fillForm: fillForm,
    createController: createController,
  };
});
