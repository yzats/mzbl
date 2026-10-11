# KCP Normalization Rules

**Vendor:** Kicks Collective PA  
**Prefix:** `KCP`  
**Code:** [`importer.js`](importer.js) supplier key `'Kicks Collective PA'`, parser `kcp-body`

Size comes from the variant's Size option. Condition, box and title come from the structured product Body. Category comes from Type. Shared size conversion, `BOX_MAP`, category maps and the description format are in [`SHARED_NORMALIZATION.md`](SHARED_NORMALIZATION.md).

---

## Body template

KCP exports (Sept 2026 onward) use this Body layout, one item per line (`<br>`-separated):

```text
Jordan 3 Retro OG Black Cement (2024)
SKU: DN3707-010
Size: 12M / 13.5W
Condition: Moderately Worn (yellowing on the soles)
Box Condition: Original Box
Release Date: 2024-11-23
```

- **Name line:** first non-empty line that is not a `Label:` line.
- **`Size:`:** single-size listings only (all pre-owned, some New). New size runs (one product, many size variants) omit it.
- **`Box Condition:`:** pre-owned listings only; New listings omit it.
- **Labels:** matched case-insensitively at the start of a line. An empty value (`Condition:` with nothing after it) is empty — it never reads the next line.

---

## Identity

| Field | Rule |
|---|---|
| `supplierCode` | Always `KCP` when vendor is Kicks Collective PA |
| `supplierSku` | Supplier variant SKU as-is: variant metafield `custom.supplier_sku` when set, else `sku` |
| `supplierTitle` / `supplierDescription` | Product metafields `custom.supplier_title` / `custom.supplier_description` when set, else `title` / `descriptionHtml`. Body parsing and the title check use these. |
| `newSku` | `KCP-{numericVariantId}` from Shopify GID |
| Local CSV runner | Forces vendor to `Kicks Collective PA` regardless of brand in the export |

**Size option names:** `Size`, `Shoe size`, or blank (Shopify CSV continuation rows).

---

## Size → `normalizedMSize`, `normalizedWSize`

1. Read the Size option value and pass it to the shared `resolveSize`. A trailing `(…)` note such as `(No Box)` is ignored. An appended condition in the older option format is dropped first, e.g. `15M/16.5W - Brand New` → `15M/16.5W`. Condition still comes from Body.
2. On a size error (`child-size`, `unknown-size` or `inconsistent-size`, shared rules) both sizes stay empty. Condition, box and title are still read from Body.
3. If Body has `Size:` and it parses to different M/W than the option → `size-mismatch`. Sizes still come from the option. An unparseable Body size is ignored, and the check is skipped when the option size already failed.

No matching option (e.g. `Title` / `Default Title` on Draft placeholders) → `unknown-size`.

---

## Condition → `normalizedCondition`, `normalizedConditionNote`

Read Body `Condition:`. Split into a base value and an optional trailing `(note)`.

| Base (case-insensitive) | normalizedCondition | Note base |
|---|---|---|
| New | Brand New | *(empty)* |
| Pre-Owned | Worn | *(empty)* |
| Tried On | Worn | tried on |
| VNDS | Worn | VNDS |
| Lightly Worn | Worn | light wear |
| Moderately Worn | Worn | moderate wear |
| Heavily Worn | Worn | heavy wear |

`normalizedConditionNote` = note base and bracketed note joined with `", "` (empty parts skipped), lowercased, with `VNDS` kept in capitals.

| Body `Condition:` | normalizedCondition | normalizedConditionNote |
|---|---|---|
| `Lightly Worn` | Worn | light wear |
| `VNDS (no soles)` | Worn | VNDS, no soles |
| `Moderately Worn (yellowing on the soles)` | Worn | moderate wear, yellowing on the soles |
| `Pre-Owned` | Worn | *(empty)* |
| `New` | Brand New | *(empty)* |

Missing line, empty value, or any other base → both empty + `unknown-condition` (the bracketed note is dropped too).

Type is **not** used: some listings typed `Pre-Owned Sneakers` say `Condition: New`.

---

## Box → `normalizedBox`

Read Body `Box Condition:` and map with shared `BOX_MAP`:

| Body `Box Condition:` | normalizedBox |
|---|---|
| Good Box, Original Box | With Box |
| Damaged Box | Damaged Box |
| Replacement, Replacement Box | Replacement Box |
| No Box | No Box |
| Missing Lid | With Box - Missing Lid |

- **No line or empty value:** no error (New listings omit the line). Brand New → With Box (shared default); otherwise empty.
- **Unlisted value:** empty + `unknown-box`.

---

## Shoe name → `normalizedTitle`

`normalizedTitle` = KCP shoe name + shared ` (Size {normalizedMSize})` suffix (see [`SHARED_NORMALIZATION.md`](SHARED_NORMALIZATION.md)).

The size suffix is added only when Body has a non-empty `Size:` line (single-size listing). Size runs get the shoe name only, so every variant of the product gets the same title, e.g. `Jordan 12 Retro Field Purple`. Sizes themselves still come from the Size option either way.

KCP shoe name (strategy `kcp-body-name`):

- **Source:** Body name line, casing as written (`adidas`, `sacai`, `MoMA`).
- **Women's qualifier removed** (bracketed, anywhere in the name, case-insensitive): `(Women's)`, `(Womens)`, `(Women)`, `(WMNS)`, `(W)`. Other brackets stay: `(GS)`, `(2021)`, `(with Socks)`, `(A Star Is Born)`.
- **Trailing size removed** when it has a size marker and is a valid size: `8.5W`, `10.5M`, `6.5Y`, `6.5M/8W`, `Size 10`. A bare number (`Yeezy 500`, `Kobe 6`) or a non-size token (`3M`) stays.

Examples:
- `Jordan 3 Cool Grey` + Size option `10M / 11.5W` → `Jordan 3 Cool Grey (Size 10)`
- `Jordan 4 Retro Seafoam (Women's)` + `11.5W` → `Jordan 4 Retro Seafoam (Size 10)`
- `Jordan 1 Retro Low OG SP Travis Scott Canary (Women's) 8.5W` + `8.5W` → `Jordan 1 Retro Low OG SP Travis Scott Canary (Size 7)`
- Youth sizes use the converted men's size: `6.5Y` → `(Size 6.5)`
- Size unknown → shoe name only (the size error is already flagged)
- **No name line:** empty + `unknown-title` (Draft placeholders, old-format Bodies that start with `Release Date:`).
- **`title-mismatch`:** Title is compared with the name line, ignoring case and extra spaces, after removing its listing suffix step by step:
  1. trailing `(Pre-Owned)`, `(Tried On)` or `(New)`;
  2. then a trailing size: `10.5`, `12W`, `6.5Y`, `6.5M/8W`, `Size 10`, `Size 11.5W`.

  A match at any step passes, so a model number at the end (`…Shadow 2.0`) is not treated as a size. The comparison uses the name line before the size suffix is added. No match → `title-mismatch`; `normalizedTitle` still comes from Body. Skipped when there is no name line.

---

## Category

Type only (`sneakers`, `pre-owned sneakers` → Sneakers via shared `PRODUCT_TYPE_MAP`). Empty or unmapped Type → `unknown-category`.

---

## Import errors (KCP context)

| Code | When |
|---|---|
| `unknown-supplier` | Vendor not in `SUPPLIERS` |
| `child-size` / `unknown-size` / `inconsistent-size` | Size option unusable (shared rules); sizes stay empty, other fields still resolve |
| `size-mismatch` | Body `Size:` parses to different M/W than the Size option |
| `unknown-condition` | Body `Condition:` missing, empty, or not in the table above |
| `unknown-box` | Body `Box Condition:` present but not in `BOX_MAP` |
| `unknown-title` | Body has no name line |
| `title-mismatch` | Title (minus listing suffix) ≠ Body name line |
| `unknown-category` | Type empty or unmapped |

`variantImportErrors` lists this variant's codes. `productImportErrors` adds them to the saved `custom.import_errors` codes (no duplicates), so the product collects every variant's errors. `hasVariantImportErrors` / `hasProductImportErrors` are true when the matching list is not empty.
