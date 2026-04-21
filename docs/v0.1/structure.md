---
title: Structure
---

Notation:

- `!` = required
- `?` = optional
- `map<K,V>` = dictionary/object map
- `enum(...)` = allowed values
- `array<T>` = list of values
- `oneOf(...)` = union type

```yaml
YAML-SPEC:
  version!: string

  api?:
    basePath?: string
    version?: string
    pagination?:
      defaultPageSize?: integer
      maxPageSize?: integer
    operations?:
      defaults?:
        list?: boolean
        get?: boolean
        create?: boolean
        update?: boolean
        replace?: boolean
        delete?: boolean

  security?:
    cors?:
      allowedOrigins?: array<string>
      allowCredentials?: boolean
      allowedMethods?: array<string>
    headers?:
      enableStandard?: boolean
    redaction?:
      enabled?: boolean
      keys?: array<string>

  collections!: map<string, CollectionConfig>

  options?:
    strict?: boolean


CollectionConfig:
  type?: enum(base, auth)                # default: base
  fields!: map<string, FieldConfig>
  auth?:                                 # required when type=auth
    identifier!: string
    via!: oneOf(enum(password, apiKey), array<enum(password, apiKey)>)
  operations?:
    list?: boolean
    get?: boolean
    create?: boolean
    update?: boolean
    replace?: boolean
    delete?: boolean
  access?:
    list?: array<AccessRule>
    get?: array<AccessRule>
    create?: array<AccessRule>
    update?: array<AccessRule>
    replace?: array<AccessRule>
    delete?: array<AccessRule>
  softDelete?: boolean
  indexes?: array<IndexConfig>


FieldConfig:
  type!: enum(string, number, boolean, datetime, enum, array, object, ref, id)
  required?: boolean
  default?: any
  unique?: boolean
  min?: number
  max?: number
  minLength?: integer
  maxLength?: integer
  format?: enum(email, e164, uri)
  values?: array<string>                  # required when type=enum
  items?: FieldConfigLite                 # required when type=array
  properties?: map<string, FieldConfig>   # for typed object
  additionalProperties?: boolean
  ref?: string                            # required when type=ref
  store?: enum(id, embed)
  expand?:
    allowed?: boolean
    always?: boolean
    fields?: array<string>
    maxDepth?: integer

AccessRule:
  effect!: enum(allow, deny)
  principal!:
    type!: enum(public, authenticated, identity)
    collection?: string                    # required when type=identity
  when?: string
  filter?: string
  writeFields?: array<string>
  reason?: string


IndexConfig:
  name?: string
  fields!: array<IndexField>
  unique?: boolean
  sparse?: boolean
  ttlSeconds?: integer
  text?: boolean


IndexField:
  field!: string
  order?: enum(asc, desc)
```
