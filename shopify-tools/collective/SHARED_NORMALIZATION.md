# Shared Normalization

Common mappings and conversions used by all Collective suppliers in [`importer.js`](importer.js). Supplier-specific rules (which option holds size, which Body labels hold condition / box / title, condition vocabulary) live in `{PREFIX}_NORMALIZATION_RULES.md` — e.g. [`KCP_NORMALIZATION_RULES.md`](KCP_NORMALIZATION_RULES.md).

Canonical output strings are defined as `NORMALIZED_CONDITION`, `NORMALIZED_BOX`, and `NORMALIZED_CATEGORY` in `importer.js` (e.g. `NORMALIZED_BOX.NO_BOX` → `"No Box"`). Maps and helpers use those constants.

---

## Size parse / convert

**Input:** a size *token* already extracted by the supplier parser (not the full option string).

**Outputs:** `resolveSize` returns `normalizedMSize` and `normalizedWSize` (US men’s / women’s as strings) plus a size error (`child-size`, `unknown-size`, `inconsistent-size`, or empty). Any error leaves both sizes empty. Supplier parsers only pick the size token and pass it in.

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

| Pattern | Error |
|---|---|
| Youth **below 3.5Y** (`3Y`, `3Y / 4.5W`) or broken `Y / 1.5W` | `child-size` |
| Child / PS (`9C`, `13.5C`) | `child-size` |
| Any size that resolves **below men's 3.5** (`3`, `3M`, `4.5W`, `EU36`) | `child-size` |
| Letter sizes, URL slugs, `Default Title`, other junk | `unknown-size` |

### M/W consistency

When both M and W are set, pairing must match the source system:

| System | Rule |
|---|---|
| US (incl. youth→adult) | `W = M + 1.5` |
| EU (`EU##` conversion) | `W = M + 2` |

Otherwise both sizes are cleared and the error is `inconsistent-size`.

---

## Condition

**Outputs:** `normalizedCondition` = `Brand New` | `Worn` | empty, plus `normalizedConditionNote` (lowercase detail, may be empty).

Condition vocabularies differ by supplier, so each supplier defines its own map (e.g. `KCP_CONDITION_MAP` — see [`KCP_NORMALIZATION_RULES.md`](KCP_NORMALIZATION_RULES.md)).

---

## Body reader (`parseBody`)

Splits product Body (HTML or plain text with newlines) into:

- **`name`:** first non-empty line, unless that line is a `Label:` line.
- **`fields`:** every `Label: value` line, keyed by lowercase label. First occurrence wins. An empty value stays empty (never borrows the next line).

`<br>`, `</p>`, `</li>`, `</div>` become line breaks; other tags are removed; common entities (`&amp;`, `&nbsp;`, …) are decoded.

---

## Box map

**Outputs:** `With Box` | `Damaged Box` | `Replacement Box` | `No Box` | `With Box - Missing Lid` | empty (unmapped).

### Exact `BOX_MAP`

| Raw (case-insensitive) | Normalized |
|---|---|
| `good box` / `original box` | With Box |
| `damaged box` | Damaged Box |
| `replacement` / `replacement box` | Replacement Box |
| `no box` | No Box |
| `missing lid` | With Box - Missing Lid |

### Default

When the supplier gives no box value and the condition is Brand New, `normalizedBox` = With Box (`defaultBox`, applied after the supplier parser). An unrecognised box value (`unknown-box`) stays empty.

---

## Category

| Input | Normalized | GID |
|---|---|---|
| Category name exact or contains a `CATEGORY_MAP` key (`shoes`, `sneakers`, …) | mapped value | `CATEGORY_GIDS[…]`, e.g. Sneakers → `gid://shopify/TaxonomyCategory/aa-8-8` |
| Product type in `PRODUCT_TYPE_MAP` | mapped value | same |
| Else | empty | *(empty)* — callers may flag `unknown-category` |

Suppliers with `categorySource: 'product-type'` (KCP) skip the category name and use Type only.

---

## Title

`normalizedTitle` = sanitized shoe name + ` (Size {normalizedMSize})`.

- **Shoe name:** supplier-specific (`deriveShoeName` dispatches on the supplier's `shoeName` strategy). It has no size and is already cleaned up, e.g. KCP removes `(Women's)`. Unknown suppliers use Title as-is.
- **Size suffix:** shared (`buildNormalizedTitle`). Left off when size is unknown (the size error is flagged separately).

Example: `Jordan 3 Cool Grey` + `10` → `Jordan 3 Cool Grey (Size 10)`.

---

## Description (by product type)

Format is shared across suppliers and chosen from `normalizedCategory` (not supplier config).

### Sneakers

`{condition} ({note}), {box in lowercase}` — any empty part (and its punctuation) is left out.

| Condition | Note | Box | Description |
|---|---|---|---|
| Worn | light wear | With Box | `Worn (light wear), with box` |
| Worn | VNDS, no soles | No Box | `Worn (VNDS, no soles), no box` |
| Brand New | *(empty)* | With Box | `Brand New, with box` |
| Worn | light wear | *(empty)* | `Worn (light wear)` |
| Worn | *(empty)* | *(empty)* | `Worn` |
| *(empty)* | *(empty)* | No Box | `no box` |
| *(empty)* | *(empty)* | *(empty)* | empty |

`normalizedBox` itself keeps its capitals; only the description lowercases it.

### Other categories

Empty for now (add formatters when non-sneaker types are supported).
