# KCP Normalization Rules

**Vendor:** Kicks Collective PA  
**Prefix:** `KCP`  
**Code:** [`importer.js`](importer.js) supplier key `'Kicks Collective PA'`, parser `kcp-size-option`

How KCP **segments** option values and **cascades** product fields when a segment is missing. Shared size conversion, `CONDITION_MAP`, and `BOX_MAP` are documented in [`SHARED_NORMALIZATION.md`](SHARED_NORMALIZATION.md).

---

## Identity

| Field | Rule |
|---|---|
| `prefix` | Always `KCP` when vendor is Kicks Collective PA |
| `originalSku` | Supplier variant SKU as-is |
| `newSku` | `KCP-{numericVariantId}` from Shopify GID |
| Local CSV runner | Forces vendor to `Kicks Collective PA` regardless of brand in the export |

**Formatters:** `title-case` for titles. Description uses the shared sneaker formatter when category is Sneakers (see [`SHARED_NORMALIZATION.md`](SHARED_NORMALIZATION.md)).

**Size option names:** `Size`, `Shoe size`, or blank (Shopify CSV continuation rows).

---

## Segmentation (` - `-separated Size option)

| Form | Example | Segments |
|---|---|---|
| Composite | `12.5M/14W - Brand New - No Box` | size \| condition \| box |
| Size only | `12M / 13.5W`, `10.5`, `7Y` | size only (condition/box from cascade) |

1. Read the Size option value (names above).
2. Split on ` - `. Segment 1 → size text; segment 2 → condition; segment 3 → box.
3. Strip trailing `(…)` from the size text before calling shared size parse (paren may still be a box signal).  
   Example: `12M / 13.5W (Missing Lid)` → size `12M / 13.5W`.

If no matching option exists (e.g. `Title` / `Default Title`), sizes stay empty and condition/box are not normalized.

**Gate:** Shared size parse + consistency must succeed before condition or box run. On `child-size` / `unknown-size` / `inconsistent-size`, leave condition and box unset.

---

## Condition cascade

**When:** size parsed OK, and there is **no** condition segment on the Size option.

**Order (first hit wins)** — each field scanned with shared `conditionFromText`:

1. Metafield `custom.productcondition`
2. Body labeled `Condition:` only (HTML wrapping optional; free prose ignored)
3. Tags
4. Product type
5. Title
6. Else → **leave unset** (empty). Not an import error.

**When a condition segment is present** (e.g. `10M - Pre-Owned - No Box`):

- Exact `CONDITION_MAP` only (no substring scan).
- Unmapped text → empty + `unknown-condition` (do not cascade).

**Not used:** unlabeled Body prose; `Restock` alone; Body `Condition: Not Specified` (no signal).

---

## Box cascade

**When:** size parsed OK, and there is **no** box segment on the Size option.

**Order (first hit wins)** — each candidate mapped with shared `BOX_MAP`:

1. Trailing paren on size text — e.g. `12M / 13.5W (Missing Lid)`
2. Tags — comma-separated, exact map keys (`no_box`, `special-no_box`, …)
3. Body labeled `Box:` only  
   Example: `Box: Replacement Box` or `<strong>Box:</strong> No Box`
4. Else → **leave unset**. Not an import error. **No default** `With Box`.

**When a box segment is present** (third ` - ` piece):

- Exact `BOX_MAP` only.
- Unmapped text → empty + `unknown-box` (do not cascade).

---

## Import errors (KCP context)

| Code | When (under this parser) |
|---|---|
| `unknown-supplier` | Vendor not in `SUPPLIERS` |
| `child-size` / `unknown-size` / `inconsistent-size` | Shared size rules (see shared doc); condition/box stay empty |
| `unknown-condition` | Condition segment present but not in `CONDITION_MAP` |
| `unknown-box` | Box segment present but not in `BOX_MAP` |
| `unknown-category` | Shared category unresolved |

`hasImportErrors` is true if any code is present. Missing cascade signals leave fields empty and do **not** set `unknown-condition` / `unknown-box`.
