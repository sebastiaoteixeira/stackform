// Prints the body a generated form sends: the `fields` of `entity` (all of them
// by default) loaded from `record`, after the user enters `inputs`.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const { ENTITY_FIELDS, formValues, payload } = await import(pathToFileURL(process.argv[2]).href);
const { entity, fields = Object.keys(ENTITY_FIELDS[entity]), record = {}, inputs = {} } = JSON.parse(
  readFileSync(0, 'utf8'),
);
const form = Object.fromEntries(fields.map((name: string) => [name, ENTITY_FIELDS[entity][name]]));
console.log(JSON.stringify(payload(form, { ...formValues(form, record), ...inputs })));
