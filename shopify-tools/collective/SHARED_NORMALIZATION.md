# Shared Normalization

Common mappings and conversions used by all Collective suppliers in [`importer.js`](importer.js). Supplier-specific rules (how options are segmented, which fields to cascade) live in `{PREFIX}_NORMALIZATION_RULES.md` — e.g. [`KCP_NORMALIZATION_RULES.md`](KCP_NORMALIZATION_RULES.md).

Canonical output strings are defined as `NORMALIZED_CONDITION`, `NORMALIZED_BOX`, and `NORMALIZED_CATEGORY` in `importer.js` (e.g. `NORMALIZED_BOX.NO_BOX` → `"No Box"`). Maps and helpers use those constants.

---

## Size parse / convert

**Input:** a size *token* already extracted by the supplier parser (not the full option string).

**Outputs:** `normalizedMSize` and `normalizedWSize` (US men’s / women’s as strings), plus an internal `system` of `us` or `eu`. Both empty when unparseable.

### Accepted patterns

| Pattern | Examples | Result |
|---|---|---|
| Men’s + women’s pair | `12.5M/14W`, `10.5M / 12W`, `US 10M / 11.5W` | M and W as written |
| Women’s + men’s pair | `14W/12.5M` | Swapped to M / W |
| Men’s only | `10.5M`, `US 10M`, `10 Men's` | M as written; W = M + 1.5 |
| Women’s only | `8.5W`, `11.5W` | W as written; M = W − 1.5 |
| Bare number | `10`, `10.5` | Treated as men’s; W = M + 1.5 |
| EU (must say `EU`) | `EU44`, `EU 45` | M = EU−33, W = EU−31 |
| Youth **3.5Y and up** | `3.5Y`, `7Y`, `6.5Y / 8W` | M = youth number; W = youth + 1.5 (or as written in a Y/W pair) |

Optional `Men's` / `Women's` spellings and an optional `US` prefix are allowed where shown. Trailing `(…)` notes are stripped before parsing.

### Not accepted

| Pattern | Error (when caller classifies) |
|---|---|
| Youth **below 3.5Y** (`3Y`, `3Y / 4.5W`) or broken `Y / 1.5W` | `child-size` |
| Child / PS (`9C`, `13.5C`) | `child-size` |
| Letter sizes, URL slugs, `Default Title`, other junk | `unknown-size` |

### M/W consistency

When both M and W are set, pairing must match the source system:

| System | Rule |
|---|---|
| US (incl. youth→adult) | `W = M + 1.5` |
| EU (`EU##` conversion) | `W = M + 2` |

Otherwise callers typically clear both sizes and flag `inconsistent-size`.

---

## Condition map

**Outputs:** `Brand New` | `Worn` | empty (unmapped).

### Exact `CONDITION_MAP`

| Raw (case-insensitive) | Normalized |
|---|---|
| `brand new` | Brand New |
| `pre-owned` | Worn |
| `worn` | Worn |
| `used` | Worn |
| `tried on` | Worn |
| `vnds` | Worn |
| `lightly worn` / `moderately worn` / `heavily worn` | Worn |

Bare `new` is **not** in this map. Exact whole-value `new` → Brand New via `isBareNewToken` for option segments, metafield, tags, and Body (`Condition: New` / own-line). Not for title/type free text.

### Text signals (`conditionFromText`)

Used when scanning free text (metafield, tags, type, title, and Body `Condition:` values other than bare `new`):

1. Exact `CONDITION_MAP` hit on the whole field.
2. Else scan for any `CONDITION_MAP` phrase inside the text (`_` / `-` treated as spaces).  
   Short keys `worn` / `used` require a word boundary.
3. If any Worn phrase and any Brand New phrase both hit, **Worn wins**.

### Exact bare `new` (`isBareNewToken`)

Whole value is exactly `new` / `New` / `new.` → Brand New when read from:

| Source | Helper |
|---|---|
| Option condition segment | `mapConditionExact` |
| Metafield | `mapMetafieldCondition` |
| Tags (per comma-separated tag) | `conditionFromTags` |
| Body labeled `Condition:` or own-line | `mapBodyCondition` |

Not applied to title or product type (avoids `NEW SIZE…`, `New Balance`, `New Year`).

Exact option-segment mapping uses `mapConditionExact` (CONDITION_MAP + bare `new`) — no substring scan.

### Body (`mapBodyCondition`)

1. Labeled `Condition:` → `conditionFromText`, else if value is exactly `new` → Brand New.  
2. Else if any whole line is exactly `new` → Brand New.  
3. Else empty (cascade continues).

---

## Box map

**Outputs:** `With Box` | `Damaged Box` | `Replacement Box` | `No Box` | `With Box - Missing Lid` | empty (unmapped).

### Exact `BOX_MAP`

| Raw (case-insensitive) | Normalized |
|---|---|
| `original box (good)` | With Box |
| `original box (damaged)` | Damaged Box |
| `damaged box` | Damaged Box |
| `replacement box` | Replacement Box |
| `no box` / `no_box` / `special-no_box` | No Box |
| `missing lid` | With Box - Missing Lid |

---

## Category

| Input | Normalized | GID |
|---|---|---|
| Category name exact or contains a `CATEGORY_MAP` key (`shoes`, `sneakers`, …) | mapped value | `CATEGORY_GIDS[…]` |
| Product type in `PRODUCT_TYPE_MAP` | mapped value | same |
| Else | empty | *(empty)* — callers may flag `unknown-category` |

---

## Description (by product type)

Format is shared across suppliers and chosen from `normalizedCategory` (not supplier config).

### Sneakers

| Condition | Box | Description |
|---|---|---|
| set | set | `{condition} ({box})` — e.g. `Worn (No Box)` |
| set | empty | `{condition}` |
| empty | set | `{box}` |
| empty | empty | empty |

### Other categories

Empty for now (add formatters when non-sneaker types are supported).
