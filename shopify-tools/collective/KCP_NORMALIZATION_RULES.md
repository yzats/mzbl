# KCP Normalization Rules

**Vendor:** Kicks Collective PA  
**Prefix:** `KCP`  
**Code:** [`importer.js`](importer.js) supplier key `'Kicks Collective PA'`, parser `composite-shoe`

These rules define how Collective import normalizes Kicks Collective PA Shopify product/variant data (Flow Run Code and the local CSV runner) into Flow-ready fields. Keep this file in sync when changing KCP behavior in `importer.js`.

---

## Identity

| Field | Rule |
|---|---|
| `prefix` | Always `KCP` when vendor is Kicks Collective PA |
| `originalSku` | Supplier variant SKU as-is |
| `newSku` | `KCP-{numericVariantId}` from Shopify GID |
| Local CSV runner | Forces vendor to `Kicks Collective PA` regardless of brand in the export |

---

## Size

**Input:** variant selected option — name `Size`, `Shoe size`, or blank (Shopify CSV continuation rows). Value may be composite or size-only:

| Form | Example | Segments (` - `-separated) |
|---|---|---|
| Composite | `12.5M/14W - Brand New - No Box` | size \| condition \| box |
| Size only | `12M / 13.5W`, `10.5`, `7Y` | size only (condition/box from other fields) |

**Outputs:** `normalizedMSize` and `normalizedWSize` (US men’s / women’s as strings), or both empty with `child-size` / `unknown-size`.

**Gate:** Size must parse successfully before condition or box are normalized. If size cannot be determined, leave condition and box unset.

### Where the size text comes from

1. Read the Size option value (names above).
2. If the value has ` - `-separated segments, use **only the first segment** as the size text.  
   Example: `10M - Pre-Owned - No Box` → size text `10M`.
3. If that size text ends with a parenthetical note, drop the note before parsing size (box may still read it).  
   Example: `12M / 13.5W (Missing Lid)` → size text `12M / 13.5W`.

If no matching option exists (e.g. `Title` / `Default Title`), sizes stay empty and condition/box are not normalized.

### Accepted adult size patterns

The whole size text must match one pattern (no partial matches):

| Pattern | Examples | Result |
|---|---|---|
| Men’s + women’s pair | `12.5M/14W`, `10.5M / 12W`, `US 10M / 11.5W` | M and W as written |
| Women’s + men’s pair | `14W/12.5M` | Swapped to M / W |
| Men’s only | `10.5M`, `US 10M`, `10 Men's` | M as written; W = M + 1.5 |
| Women’s only | `8.5W`, `11.5W` | W as written; M = W − 1.5 |
| Bare number | `10`, `10.5` | Treated as men’s; W = M + 1.5 |
| EU (must say `EU`) | `EU44`, `EU 45` | M = EU−33, W = EU−31 |
| Youth **3.5Y and up** | `3.5Y`, `7Y`, `6.5Y / 8W` | M = youth number; W = youth + 1.5 (or as written in a Y/W pair) |

Optional `Men's` / `Women's` spellings and an optional `US` prefix are allowed where shown above.

### Not accepted (adult)

These leave both sizes empty and leave condition/box unset:

| Pattern | Error |
|---|---|
| Youth **below 3.5Y** (`3Y`, `3Y / 4.5W`) or broken `Y / 1.5W` | `child-size` |
| Child / PS (`9C`, `13.5C`) | `child-size` |
| Letter sizes, URL slugs, `Default Title`, other junk | `unknown-size` |

---

## Condition

**Input (in order):** Size-option condition segment → metafield → Body `Condition:` → tags → product type → title.

**Outputs:** `Brand New` | `Worn` | empty (unset).  
`unknown-condition` is flagged only when an explicit Size-option condition text is unmapped (field stays empty).

### Source order (first hit wins)

1. **Condition text in the Size option** — if the Size value has two or more ` - `-separated segments, use the second one (exact `conditionMap` only).  
   Example: `10M - Pre-Owned - No Box` → `Worn`.  
   If that segment is present but not in `conditionMap` → leave empty + `unknown-condition`.
2. **Metafield** `custom.productcondition` (CSV: `Condition (product.metafields.custom.productcondition)`)
3. **Body** — labeled `Condition:` only (HTML wrapping optional; free prose ignored)
4. **Tags**
5. **Product type**
6. **Title**
7. Else → **leave unset** (empty string). Not an import error.

Requires a parseable size (see [Size](#size)). If size is unknown, condition stays unset (cascade does not run).

**Not used:** unlabeled Body prose; `Restock` alone (no default Brand New); Body `Condition: Not Specified` (treated as no signal).

### Exact `conditionMap`

| Raw (case-insensitive) | Normalized |
|---|---|
| `brand new` | Brand New |
| `new` | Brand New |
| `pre-owned` | Worn |
| `worn` | Worn |
| `used` | Worn |
| `tried on` | Worn |
| `vnds` | Worn |
| `lightly worn` / `moderately worn` / `heavily worn` | Worn |

### Text signals (metafield / Body Condition / tags / type / title)

Same scanner for each field, in order:

1. contains `pre-owned` or `pre owned` → Worn  
2. contains `lightly|moderately|heavily worn` or `lightly_worn` / `moderately_worn` / `heavily_worn` → Worn  
3. word-boundary `worn` or `used` → Worn  
4. contains `brand new` → Brand New  
5. word-boundary `new` → Brand New, unless text contains `new balance`

If worn/pre-owned/used and new both appear in the **same** field, **Worn wins**.

---

## Box

**Input (in order):** Size-option box segment → trailing `(…)` on the size text → product tags → Body labeled `Box:`. Same Size-option forms as in [Size](#size).

**Outputs:** `With Box` | `Damaged Box` | `Replacement Box` | `No Box` | `With Box - Missing Lid` | empty (unset).  
`unknown-box` is flagged only when an explicit Size-option box text is unmapped (field stays empty).

Runs only after size is successfully parsed. If size is unknown, box stays unset. **No default** — if nothing derives a box value, leave unset (same idea as condition).

### Source order (first hit wins)

1. **Box text in the Size option** — if the Size value has three ` - `-separated segments, use the last one (exact `boxMap` only).  
   Example: `10M - Pre-Owned - No Box` → `No Box`.  
   If that last segment is present but not in `boxMap` → leave empty + `unknown-box` (do not keep looking).
2. **Parenthetical note on the size text** — e.g. `12M / 13.5W (Missing Lid)` → `With Box - Missing Lid`.
3. **Tags** — each comma-separated tag, exact `boxMap` keys (`no_box`, `special-no_box`, …).
4. **Body** — labeled `Box:` only (HTML wrapping optional; free-form sentences ignored).  
   Example: `Box: Replacement Box` or `<strong>Box:</strong> No Box`.
5. Else → **leave unset** (empty string). Not an import error.

### Exact `boxMap`

| Raw (case-insensitive) | Normalized |
|---|---|
| `original box (good)` | With Box |
| `original box (damaged)` | Damaged Box |
| `damaged box` | Damaged Box |
| `replacement box` | Replacement Box |
| `no box` / `no_box` / `special-no_box` | No Box |
| `missing lid` | With Box - Missing Lid |

Parenthetical notes are ignored when parsing the numeric size, and separately checked as a box signal (step 2).

---

## Title

**Formatter:** `title-case` — capitalize words; keep short all-caps tokens (`OG`, `SP`, …); lowercase small words (`a`, `the`, `of`, …) when not first/last.

Does **not** strip size/condition phrases from the title (condition may still be *read* from title for the condition field).

---

## Description

**Formatter:** `condition-box`

| Condition | Box | Description |
|---|---|---|
| set | set | `{condition} ({box})` — e.g. `Worn (No Box)` |
| set | empty | `{condition}` |
| empty | set | `{box}` — e.g. `With Box` |
| empty | empty | empty (e.g. size unknown / nothing resolved) |

---

## Category

| Input | Normalized | GID |
|---|---|---|
| Category name contains `shoes` or `sneakers` | Sneakers | `gid://shopify/TaxonomyCategory/aa-sneakers` |
| Type in: Men's/Women's/Kid's Shoes, Toddler's, Preschool, shoes, sneakers, Pre-Owned Sneakers | Sneakers | same |
| Else | empty + `unknown-category` | *(empty)* |

---

## Import errors

Comma-separated codes when review is needed:

| Code | When |
|---|---|
| `unknown-supplier` | Vendor not in `SUPPLIERS` |
| `child-size` | Youth below 3.5Y, broken `Y / …`, or child (`C`) size |
| `unknown-size` | No parseable adult M/W size (and not child/youth) |
| `unknown-condition` | Size-option condition text present but unmapped (only when size parsed) |
| `unknown-box` | Box segment present but unmapped (only when size parsed) |
| `unknown-category` | Category unresolved |

`hasImportErrors` is true if any code is present.

Missing condition/box signals leave those fields empty and do **not** set `unknown-condition` / `unknown-box`. When size is `child-size` or `unknown-size`, condition and box stay empty.
