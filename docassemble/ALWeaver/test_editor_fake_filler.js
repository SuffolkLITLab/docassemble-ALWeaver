'use strict';
const assert = require('node:assert/strict');
const filler = require('./data/static/editor_fake_filler.js');
const faker = global.ALWeaverFaker;
faker.seed(20261002);

function field(properties = {}) {
  const attributes = properties.attributes || {};
  return {
    type: 'text',
    tagName: 'INPUT',
    minLength: -1,
    maxLength: -1,
    classList: {
      contains: (name) => (properties.classes || []).includes(name),
    },
    getAttribute: (name) => attributes[name] ?? null,
    hasAttribute: (name) => Object.hasOwn(attributes, name),
    ...properties,
  };
}
const samples = filler.createSampleData();
function value(
  variable,
  properties = {},
  datatype = 'text',
  label = '',
  context = samples,
) {
  return filler.sampleValue(
    field(properties),
    { variable, label, datatype },
    context,
  );
}
const streets = new Set();
const cities = new Set();
const zips = new Set();
const phones = new Set();
const names = new Set();
const nationwideStates = new Set();
const lastFourValues = new Set();
for (let i = 0; i < 100; i++) {
  const digits = value('users[i].last_4_of_social', {
    minLength: 4,
    maxLength: 4,
  });
  assert.match(digits, /^\d{4}$/);
  lastFourValues.add(digits);
}
assert.ok(
  lastFourValues.size > 80,
  'identifier digits vary rather than use a fixed sample',
);
assert.ok(
  [...lastFourValues].some((value) => value.startsWith('0')),
  'leading zeroes remain valid digits',
);
assert.match(
  value('answer', {}, 'text', 'last 4 digits of social security number'),
  /^\d{4}$/,
);
assert.match(value('ssn_last_four'), /^\d{4}$/);
assert.match(value('phone_last_4'), /^\d{4}$/);
assert.match(
  value('answer', {}, 'text', 'last 6 digits of account number'),
  /^\d{6}$/,
);
assert.ok(
  /[a-z]/i.test(
    value('answer', {}, 'text', 'last 4 characters of your nickname'),
  ),
);
for (let i = 0; i < 100; i++)
  nationwideStates.add(
    filler.createSampleData().address('person.address.address').state,
  );
assert.ok(
  nationwideStates.size > 30,
  'blank addresses sample states nationwide',
);
for (let i = 0; i < 100; i++) {
  const prefix = `household.members[${i}]`;
  samples.seedAddress(`${prefix}.address.state`, 'state', 'Massachusetts');
  const street = value(`${prefix}.address.address`);
  const city = value(`${prefix}.address.city`);
  const zip = value(`${prefix}.address.zip`, { inputMode: 'numeric' });
  assert.match(street, /^\d+ .+/);
  assert.match(zip, /^0\d{4}$/);
  assert.equal(value(`${prefix}.address.state`), 'MA');
  assert.equal(value(`${prefix}.address.country`), 'US');
  assert.match(value(`${prefix}.address.unit`), /^\d+$/);
  assert.equal(
    value(`${prefix}.address.address`),
    street,
    'address reused across screens',
  );
  const phone = value(`${prefix}.mobile_number`);
  assert.match(phone, /^\d{10}$/);
  assert.ok(
    faker.definitions.phone_number.area_code.includes(phone.slice(0, 3)),
  );
  assert.ok(
    faker.definitions.phone_number.exchange_code.includes(phone.slice(3, 6)),
  );
  assert.equal(value(`${prefix}.mobile_number`), phone);
  assert.notEqual(value(`${prefix}.phone_number`), phone);
  const first = value(`${prefix}.name.first`);
  const last = value(`${prefix}.name.last`);
  assert.equal(value(`${prefix}.name`), `${first} ${last}`);
  assert.match(value(`${prefix}.email`, {}, 'email'), /@example\.com$/);
  streets.add(street);
  cities.add(city);
  zips.add(zip);
  phones.add(phone);
  names.add(`${first} ${last}`);
}
for (const variations of [streets, cities, zips, phones, names]) {
  assert.ok(
    variations.size > 80,
    'Faker produces broad variation across people and addresses',
  );
}
assert.notEqual(
  value('users[0].address.address', {}, 'text', '', filler.createSampleData()),
  value('users[0].address.address'),
);
const address = samples.address('rent_address_one_line');
assert.equal(
  value('rent_address_one_line'),
  `${address.address}, ${address.city}, ${address.state} ${address.zip}`,
);
samples.seedAddress('users[0].address.zip', 'zip', '02108');
assert.equal(value('users[0].address.zip'), '02108');
// Faker has zip tables only for the 50 states; other prefilled states still fill.
for (const state of ['District of Columbia', 'ON', 'Puerto Rico']) {
  const other = filler.createSampleData();
  other.seedAddress('users[0].address.state', 'state', state);
  assert.match(other.address('users[0].address.state').zip, /^\d{5}/);
}
// A typed input gets a value of its type even when its name looks like an address.
assert.match(value('user.years_at_address', {}, 'integer'), /^\d+$/);
assert.match(value('name_change_date', {}, 'date'), /^\d{4}-\d{2}-\d{2}$/);
// ALToolbox's BirthDate day/year parts are bare type=number inputs; numbers
// other than money are whole.
for (let i = 0; i < 50; i++) {
  assert.match(
    value('', { type: 'number', inputMode: 'numeric' }, 'number'),
    /^\d+$/,
  );
  assert.match(value('household_size', {}, 'number'), /^\d+$/);
  assert.match(value('hours', {}, 'float'), /^\d+$/);
}
const thisYear = new Date().getFullYear();
for (let i = 0; i < 50; i++) {
  const birthYear = Number(
    value('birthdate.year', { type: 'number' }, 'number'),
  );
  assert.ok(birthYear >= thisYear - 80 && birthYear <= thisYear - 18);
}
// Currency text controls must win over address-like labels and yield plain numbers.
for (let i = 0; i < 100; i++) {
  const amount = Number(
    value('rent', { classes: ['dacurrency'] }, 'text', 'Rent for this address'),
  );
  assert.ok(amount >= 1 && amount <= 5000);
  const fractional = Number(
    value(
      'cost',
      { attributes: { min: '0.005', max: '0.015', step: '0.005' } },
      'number',
    ),
  );
  assert.ok(fractional >= 0.005 && fractional <= 0.015);
  assert.ok(
    Math.abs(fractional / 0.005 - Math.round(fractional / 0.005)) < 1e-8,
  );
  assert.ok(
    ['3', '5', '7'].includes(
      value(
        'count',
        { attributes: { min: '3', max: '8', step: '2' } },
        'integer',
      ),
    ),
  );
  const bounded = Number(
    value('cost', { attributes: { max: '20', step: '1' } }, 'currency'),
  );
  assert.ok(bounded >= 1 && bounded <= 20 && Number.isInteger(bounded));
  assert.ok(Number.isInteger(Number(value('count', { inputMode: 'numeric' }))));
}
assert.match(
  value('birth_date', { type: 'date' }, 'date'),
  /^\d{4}-\d{2}-\d{2}$/,
);
assert.ok(
  new Date(value('birth_date', {}, 'date')).getFullYear() <=
    new Date().getFullYear() - 18,
);
assert.equal(
  value('hearing_date', { min: '2026-01-01', max: '2026-01-01' }, 'date'),
  '2026-01-01',
);
assert.equal(value('answer', { maxLength: 6 }).length, 6);
assert.equal(value('answer', { minLength: 100 }).length, 100);
console.log('editor_fake_filler.js: all assertions passed');
