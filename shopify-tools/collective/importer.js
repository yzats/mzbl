/**
 * Collective inventory normalizer for Shopify Flow (Run Code) and the local
 * CSV runner (process_inventory.mjs).
 *
 * Takes one productVariant (+ product) from a configured supplier and maps
 * supplier-specific encodings into stable fields for downstream metafield
 * updates and review tags.
 *
 * Shared across suppliers (see SHARED_NORMALIZATION.md):
 *   - CONDITION_MAP / BOX_MAP and text→normalized mappers
 *   - size parse / US·EU conversion / M↔W consistency
 *   - category → Sneakers, title-case, sneaker condition/box description
 *
 * Supplier-specific (see KCP_NORMALIZATION_RULES.md for KCP):
 *   - how size / condition / box are segmented from options
 *   - which fields to cascade when a segment is missing
 *
 * Size is required: if US M/W size cannot be derived, condition and box are
 * left unset. Unresolved values stay empty (never the string "unknown");
 * problems are reported via importErrors instead.
 *
 * Outputs — derived:
 *   supplierCode            e.g. "KCP"
 *   variantId               e.g. "4521987654321"
 *   newSku                  e.g. "KCP-4521987654321"
 *   normalizedMSize         e.g. "10.5", "12"  (empty if size failed)
 *   normalizedWSize         e.g. "12", "13.5"  (empty if size failed)
 *   normalizedCondition     NORMALIZED_CONDITION.BRAND_NEW | NORMALIZED_CONDITION.WORN | ""
 *   normalizedBox           NORMALIZED_BOX.WITH_BOX | NORMALIZED_BOX.DAMAGED_BOX | NORMALIZED_BOX.REPLACEMENT_BOX |
 *                           NORMALIZED_BOX.NO_BOX | NORMALIZED_BOX.WITH_BOX_MISSING_LID | ""
 *   normalizedTitle         title-cased product title
 *   normalizedDescription   e.g. "Worn (No Box)", "Brand New",
 *                           "Replacement Box", or ""
 *   normalizedCategory      NORMALIZED_CATEGORY.SNEAKERS | ""
 *   normalizedCategoryGid   e.g. "gid://shopify/TaxonomyCategory/aa-sneakers"
 *                           or ""
 *   importErrors            comma-separated codes, e.g. "unknown-size" or
 *                           "child-size,unknown-category" ("" if none)
 *   hasImportErrors         true | false
 *
 * Outputs — supplier (copied):
 *   supplierSku             supplier variant SKU as-is
 *   supplierTitle           product title as-is
 *   supplierDescription     product description / Body HTML as-is
 *
 * importErrors may include: unknown-supplier, child-size, unknown-size,
 * inconsistent-size, unknown-condition, unknown-box, unknown-category.
 */

// ---------------------------------------------------------------------------
// Shared maps & taxonomy
// ---------------------------------------------------------------------------

// Canonical normalized field values (outputs / map targets).
var NORMALIZED_CONDITION = {
  BRAND_NEW: 'Brand New',
  WORN: 'Worn'
};

var NORMALIZED_BOX = {
  WITH_BOX: 'With Box',
  DAMAGED_BOX: 'Damaged Box',
  REPLACEMENT_BOX: 'Replacement Box',
  NO_BOX: 'No Box',
  WITH_BOX_MISSING_LID: 'With Box - Missing Lid'
};

var NORMALIZED_CATEGORY = {
  SNEAKERS: 'Sneakers'
};

var CATEGORY_GIDS = {};
CATEGORY_GIDS[NORMALIZED_CATEGORY.SNEAKERS] = 'gid://shopify/TaxonomyCategory/aa-sneakers';

// Keys are normalized to lowercase before lookup.
// Note: bare "new" is NOT here — it is Body-only (see mapBodyCondition).
var CONDITION_MAP = {
  'brand new': NORMALIZED_CONDITION.BRAND_NEW,
  'pre-owned': NORMALIZED_CONDITION.WORN,
  'worn': NORMALIZED_CONDITION.WORN,
  'used': NORMALIZED_CONDITION.WORN,
  'tried on': NORMALIZED_CONDITION.WORN,
  'vnds': NORMALIZED_CONDITION.WORN,
  'lightly worn': NORMALIZED_CONDITION.WORN,
  'moderately worn': NORMALIZED_CONDITION.WORN,
  'heavily worn': NORMALIZED_CONDITION.WORN
};

// Keys are normalized to lowercase before lookup.
var BOX_MAP = {
  'original box (good)': NORMALIZED_BOX.WITH_BOX,
  'original box (damaged)': NORMALIZED_BOX.DAMAGED_BOX,
  'damaged box': NORMALIZED_BOX.DAMAGED_BOX,
  'replacement box': NORMALIZED_BOX.REPLACEMENT_BOX,
  'no box': NORMALIZED_BOX.NO_BOX,
  'no_box': NORMALIZED_BOX.NO_BOX,
  'special-no_box': NORMALIZED_BOX.NO_BOX,
  'missing lid': NORMALIZED_BOX.WITH_BOX_MISSING_LID
};

// Product type → normalized category (keys lowercase).
var PRODUCT_TYPE_MAP = {
  "men's shoes": NORMALIZED_CATEGORY.SNEAKERS,
  "women's shoes": NORMALIZED_CATEGORY.SNEAKERS,
  "kid's shoes": NORMALIZED_CATEGORY.SNEAKERS,
  "kids's shoes": NORMALIZED_CATEGORY.SNEAKERS,
  "toddler's": NORMALIZED_CATEGORY.SNEAKERS,
  'toddlers': NORMALIZED_CATEGORY.SNEAKERS,
  'preschool': NORMALIZED_CATEGORY.SNEAKERS,
  'shoes': NORMALIZED_CATEGORY.SNEAKERS,
  'sneakers': NORMALIZED_CATEGORY.SNEAKERS,
  'pre-owned sneakers': NORMALIZED_CATEGORY.SNEAKERS
};

// Shopify taxonomy / category name tokens → normalized category (keys lowercase).
// Matched exactly or as a substring of the category path
// (e.g. "Apparel & Accessories > Shoes > Sneakers").
var CATEGORY_MAP = {
  'shoes': NORMALIZED_CATEGORY.SNEAKERS,
  'sneakers': NORMALIZED_CATEGORY.SNEAKERS
};

// ---------------------------------------------------------------------------
// Supplier configs — encoding / cascade strategy only (not shared maps)
// ---------------------------------------------------------------------------

// Add future suppliers here. If a supplier encodes size/condition/box
// differently, give it a different parser name and add that parser below.
var SUPPLIERS = {
  'Kicks Collective PA': {
    prefix: 'KCP',
    parser: 'kcp-size-option',
    titleFormatter: 'title-case',
    // Option names to search when looking for the Size option.
    sizeOptionNames: ['Size', 'Shoe size', '']
  }
};

export default function main(input) {
  // Keep input extraction defensive. If Shopify omits a field, the workflow
  // should produce reviewable empty outputs + error codes rather than throwing.
  var safeInput = input || {};
  var productVariant = safeInput.productVariant || {};
  var product = productVariant.product || {};
  var supplier = SUPPLIERS[product.vendor] || null;

  // Extract the numeric variant ID from the full GID (e.g., gid://shopify/ProductVariant/4521987654321)
  var variantId = productVariant.id ? productVariant.id.toString().split('/').pop() : '';

  // Get the supplier code from the SUPPLIERS lookup
  var supplierCode = supplier ? supplier.prefix : 'UNK';

  // Build the new SKU in format {SUPPLIER_CODE}-{variantId}
  // e.g., KCP-4521987654321
  var newSku = supplierCode + '-' + variantId;

  // Capture the supplier's SKU as-is for reference
  var supplierSku = productVariant.sku || '';

  // Supplier parsing is isolated here so future suppliers can differ without
  // changing the output fields expected by the rest of the workflow.
  var selectedOptions = Array.isArray(productVariant.selectedOptions)
    ? productVariant.selectedOptions
    : [];
  var parsedDetails = supplier
    ? parseSupplierDetails(supplier, selectedOptions, product)
    : blankDetails();

  // Category is product-level; size/condition/box are variant-level metafields.
  var supplierTitle = product.title || '';
  var supplierDescription = product.description || '';
  var normalizedTitle = normalizeTitle(product.title || '', supplier);
  var normalizedCategory = normalizeCategory(product.category, product.productType);
  var normalizedCategoryGid = CATEGORY_GIDS[normalizedCategory] || '';
  // Description format is shared and product-type based (not supplier-based).
  var normalizedDescription = normalizeDescription(parsedDetails, normalizedCategory);

  // A comma-separated error string is easier to pass through Shopify Flow than
  // an array, while hasImportErrors remains convenient for conditions.
  var importErrors = collectImportErrors(supplier, parsedDetails, normalizedCategory);

  // Keep this return shape aligned with the Run code output schema in Shopify.
  return {
    supplierCode: supplierCode,
    variantId: variantId,
    newSku: newSku,
    supplierSku: supplierSku,
    normalizedMSize: parsedDetails.normalizedMSize.toString(),
    normalizedWSize: parsedDetails.normalizedWSize.toString(),
    normalizedCondition: parsedDetails.normalizedCondition,
    normalizedBox: parsedDetails.normalizedBox,
    supplierTitle: supplierTitle,
    supplierDescription: supplierDescription,
    normalizedTitle: normalizedTitle,
    normalizedDescription: normalizedDescription,
    normalizedCategory: normalizedCategory,
    normalizedCategoryGid: normalizedCategoryGid,
    importErrors: importErrors.join(','),
    hasImportErrors: importErrors.length > 0
  };
}

// ---------------------------------------------------------------------------
// Shared: title / description
// ---------------------------------------------------------------------------

function normalizeDescription(details, normalizedCategory) {
  // Description strategy follows product type/category, not supplier.
  // Add branches for apparel / other types as needed.
  if (normalizedCategory === NORMALIZED_CATEGORY.SNEAKERS) {
    return buildSneakerDescription(details);
  }

  return '';
}

function buildSneakerDescription(details) {
  // Sneaker public description from resolved condition / box.
  //   both set  → "Worn (No Box)"
  //   condition → "Worn"
  //   box only  → "Replacement Box"
  //   neither   → ""
  var condition = details.normalizedCondition || '';
  var box = details.normalizedBox || '';

  if (condition && box) return condition + ' (' + box + ')';
  if (condition) return condition;
  if (box) return box;
  return '';
}

function normalizeTitle(title, supplier) {
  if (!supplier) return title;

  // Add future title strategies here when suppliers need different cleanup.
  if (supplier.titleFormatter === 'title-case') {
    return toTitleCase(title);
  }

  // Unknown formatter means "do not alter the supplier title".
  return title;
}

function toTitleCase(title) {
  var smallWords = {
    a: true,
    an: true,
    and: true,
    as: true,
    at: true,
    but: true,
    by: true,
    for: true,
    if: true,
    in: true,
    nor: true,
    of: true,
    on: true,
    or: true,
    so: true,
    the: true,
    to: true,
    via: true,
    with: true
  };

  var words = (title || '').toString().trim().split(/\s+/);
  for (var i = 0; i < words.length; i++) {
    var lower = words[i].toLowerCase();

    // Keep short uppercase model codes readable, e.g. "SB", "OG", "SP".
    if (/^[A-Z0-9]{2,}$/.test(words[i])) continue;

    if (i > 0 && i < words.length - 1 && smallWords[lower]) {
      words[i] = lower;
    } else {
      words[i] = lower.charAt(0).toUpperCase() + lower.slice(1);
    }
  }

  return words.join(' ');
}

// ---------------------------------------------------------------------------
// Shared: condition / box text → normalized values
// ---------------------------------------------------------------------------

function mapBox(raw) {
  if (!raw) return '';
  return BOX_MAP[normalizeKey(raw)] || '';
}

function isBareNewToken(text) {
  // Whole value is exactly "new" (optional period). Not a substring scan —
  // used for option segments, metafield, tags, and Body Condition / own-line.
  return /^new\.?$/i.test((text || '').toString().trim());
}

function mapConditionExact(raw) {
  // Exact CONDITION_MAP lookup, plus exact bare "new" → Brand New.
  // Used for Size-option condition segments.
  if (!raw) return '';
  var key = normalizeKey(raw);
  if (CONDITION_MAP[key]) return CONDITION_MAP[key];
  if (isBareNewToken(raw)) return NORMALIZED_CONDITION.BRAND_NEW;
  return '';
}

function conditionScanForm(value) {
  // Collapse punctuation so map phrases match free text variants
  // ("pre-owned" / "pre owned", "lightly_worn" / "lightly worn").
  return normalizeKey(value).replace(/[_-]/g, ' ').replace(/\s+/g, ' ').trim();
}

function conditionFromText(text) {
  // Map-driven: exact hit first, then scan CONDITION_MAP phrases inside free text.
  // Worn beats Brand New when both appear. Short keys (worn/used) use word
  // boundaries so they do not match inside longer tokens.
  // Bare "new" is intentionally absent from CONDITION_MAP — use isBareNewToken
  // / mapConditionExact / mapBodyCondition / conditionFromTags instead.
  var exactKey = normalizeKey(text);
  if (!exactKey) return '';
  if (CONDITION_MAP[exactKey]) return CONDITION_MAP[exactKey];

  var scan = conditionScanForm(text);
  if (!scan) return '';

  var wornHit = false;
  var brandNewHit = false;

  for (var mapKey in CONDITION_MAP) {
    if (!Object.prototype.hasOwnProperty.call(CONDITION_MAP, mapKey)) continue;

    var phrase = conditionScanForm(mapKey);
    if (!phrase) continue;

    var matched;
    if (phrase === 'worn' || phrase === 'used') {
      matched = new RegExp('\\b' + phrase + '\\b').test(scan);
    } else {
      matched = scan.indexOf(phrase) !== -1;
    }
    if (!matched) continue;

    if (CONDITION_MAP[mapKey] === NORMALIZED_CONDITION.WORN) {
      wornHit = true;
    } else if (CONDITION_MAP[mapKey] === NORMALIZED_CONDITION.BRAND_NEW) {
      brandNewHit = true;
    }
  }

  if (wornHit) return NORMALIZED_CONDITION.WORN;
  if (brandNewHit) return NORMALIZED_CONDITION.BRAND_NEW;

  return '';
}

function conditionFromTags(tags) {
  // Scan full tag string for CONDITION_MAP phrases, then each tag for exact
  // bare "new" (e.g. tags "new, Restock").
  if (!tags) return '';

  var mapped = conditionFromText(tags);
  if (mapped) return mapped;

  var parts = tags.toString().split(',');
  for (var i = 0; i < parts.length; i++) {
    if (isBareNewToken(parts[i])) return NORMALIZED_CONDITION.BRAND_NEW;
  }

  return '';
}

function boxFromTags(tags) {
  if (!tags) return '';

  var parts = tags.toString().split(',');
  for (var i = 0; i < parts.length; i++) {
    var mapped = mapBox(parts[i]);
    if (mapped) return mapped;
  }

  return '';
}

function bodyPlainText(html) {
  // Convert Body HTML to plain text with line breaks preserved.
  if (!html) return '';
  return html.toString()
    .replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/<\/p>/gi, '\n')
    .replace(/<\/li>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&');
}

function bodyField(html, label) {
  // Read "Label: value" from Body regardless of wrapping tags
  // (e.g. <strong>Box:</strong> No Box or plain "Condition: Pre-Owned").
  if (!html || !label) return '';

  var text = bodyPlainText(html);
  var escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  var re = new RegExp('(?:^|\\n)\\s*' + escaped + ':\\s*([^\\n]+)', 'i');
  var match = text.match(re);
  return match ? match[1].trim() : '';
}

function descriptionHasOwnLineNew(html) {
  // KCP Restock template puts a bare "new" on its own line after Released:
  //   ...Released: …<br>new<br><br><ul>…
  var text = bodyPlainText(html);
  if (!text) return false;

  var lines = text.split(/\n/);
  for (var i = 0; i < lines.length; i++) {
    if (isBareNewToken(lines[i])) return true;
  }
  return false;
}

function mapBodyCondition(html) {
  // Body bare "new" → Brand New:
  //   1) labeled Condition: New
  //   2) else own-line "new"
  // All other phrases use shared CONDITION_MAP via conditionFromText.
  var labeled = bodyField(html, 'Condition');
  if (labeled) {
    var mapped = conditionFromText(labeled);
    if (mapped) return mapped;
    if (isBareNewToken(labeled)) return NORMALIZED_CONDITION.BRAND_NEW;
    return '';
  }
  if (descriptionHasOwnLineNew(html)) return NORMALIZED_CONDITION.BRAND_NEW;
  return '';
}

function mapMetafieldCondition(raw) {
  // Metafield: CONDITION_MAP scan/exact, then exact bare "new".
  var mapped = conditionFromText(raw);
  if (mapped) return mapped;
  if (isBareNewToken(raw)) return NORMALIZED_CONDITION.BRAND_NEW;
  return '';
}

// ---------------------------------------------------------------------------
// Shared: size parse / convert / consistency
// ---------------------------------------------------------------------------

function parseSizeText(sizeText) {
  // Parse a size token into US M/W (or EU-derived M/W). Caller supplies the
  // size text only — suppliers decide how to extract it from options.
  // Examples that must match as a whole token (no partial matches):
  //   "12.5M/14W", "10.5M / 12W", "10.5M", "11.5W", "10.5", "EU44", "3.5Y", "7Y / 8.5W"
  // Examples that stay unparsed: "Y / 1.5W", "3Y", "9C", "Default Title"
  var text = (sizeText || '').trim();

  // Drop trailing notes, e.g. "12M / 13.5W (Missing Lid)" → "12M / 13.5W".
  text = text.replace(/\s*\([^)]*\)\s*$/, '').trim();

  // European size conversion (e.g., "EU44", "EU 44", "EU44.5")
  // Formula used here: M = EU−33, W = EU−31 → always W = M + 2.
  var euMatch = text.match(/^EU\s*([0-9]+(?:\.[0-9]+)?)$/i);
  if (euMatch) {
    var euVal = parseFloat(euMatch[1]);
    if (!isNaN(euVal)) {
      return { m: (euVal - 33).toString(), w: (euVal - 31).toString(), system: 'eu' };
    }
  }

  // Men's and women's sizes in the common "12.5M/14W" order (spaces optional).
  var match = text.match(/^(?:US\s*)?([0-9]+(?:\.[0-9]+)?)\s*M(?:en'?s)?\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*W$/i);
  if (match) return { m: match[1], w: match[2], system: 'us' };

  // Same data in reverse order, e.g. "14W/12.5M".
  match = text.match(/^(?:US\s*)?([0-9]+(?:\.[0-9]+)?)\s*W(?:omen'?s)?\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*M$/i);
  if (match) return { m: match[2], w: match[1], system: 'us' };

  // Men's-only size. Derive women's as men's + 1.5 (standard US pairing).
  match = text.match(/^(?:US\s*)?([0-9]+(?:\.[0-9]+)?)\s*M(?:en'?s)?$/i);
  if (match) return { m: match[1], w: offsetUsSize(match[1], 1.5), system: 'us' };

  // Women's-only size. Derive men's as women's - 1.5.
  match = text.match(/^(?:US\s*)?([0-9]+(?:\.[0-9]+)?)\s*W(?:omen'?s)?$/i);
  if (match) return { m: offsetUsSize(match[1], -1.5), w: match[1], system: 'us' };

  // Bare number — treat as men's.
  match = text.match(/^([0-9]+(?:\.[0-9]+)?)$/);
  if (match) return { m: match[1], w: offsetUsSize(match[1], 1.5), system: 'us' };

  // Youth (GS) 3.5Y and up map onto adult US sizing: men's = youth number,
  // women's = youth + 1.5 (or as written when a Y/W pair is present).
  // Below 3.5Y and child (C) sizes stay unparsed → child-size.
  match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*Y\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*W$/i);
  if (match && parseFloat(match[1]) >= 3.5) {
    return { m: match[1], w: match[2], system: 'us' };
  }

  match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*W\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*Y$/i);
  if (match && parseFloat(match[2]) >= 3.5) {
    return { m: match[2], w: match[1], system: 'us' };
  }

  match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*Y$/i);
  if (match && parseFloat(match[1]) >= 3.5) {
    return { m: match[1], w: offsetUsSize(match[1], 1.5), system: 'us' };
  }

  // Unknown size format. The caller turns this into child-size or unknown-size.
  return { m: '', w: '' };
}

function offsetUsSize(sizeText, delta) {
  // US shoe sizes step in halves; round to nearest 0.5 to avoid float noise.
  var value = Math.round((parseFloat(sizeText) + delta) * 2) / 2;
  return value.toString();
}

function sizesAreConsistent(sizes) {
  // Fixed pairing by source system:
  //   US (incl. youth→adult): W = M + 1.5
  //   EU conversion:          W = M + 2
  var m = parseFloat(sizes.m);
  var w = parseFloat(sizes.w);
  if (isNaN(m) || isNaN(w)) return false;

  var expectedDelta = sizes.system === 'eu' ? 2 : 1.5;
  return Math.abs((w - m) - expectedDelta) < 0.01;
}

function classifyUnparsedSize(sizeText) {
  // Strip trailing paren notes the same way size parsing does,
  // e.g. "7Y (Missing Lid)" → "7Y".
  var text = (sizeText || '').trim().replace(/\s*\([^)]*\)\s*$/, '').trim();
  if (!text) return 'unknown-size';

  // Youth / GS below 3.5Y, or broken values without a youth number.
  // Examples: "3Y", "3Y / 4.5W", "Y / 1.5W"
  // (3.5Y+ is converted to adult M/W in parseSizeText.)
  if (/\d(?:\.\d+)?\s*Y\b/i.test(text) || /^Y(?:\s*\/|\s*$)/i.test(text)) {
    return 'child-size';
  }

  // Child / PS, e.g. "9C", "13.5C"
  if (/\d(?:\.\d+)?\s*C\b/i.test(text)) {
    return 'child-size';
  }

  return 'unknown-size';
}

// ---------------------------------------------------------------------------
// Shared: category
// ---------------------------------------------------------------------------

function normalizeCategory(category, productType) {
  // Normalize known sneaker/shoe categories. Accept either a Shopify-style
  // { name: "..." } object or a plain category string (CSV runner).
  var categoryName = '';
  if (category && typeof category === 'object') {
    categoryName = category.name || '';
  } else if (category) {
    categoryName = category;
  }
  var categoryKey = normalizeKey(categoryName);
  var productTypeKey = normalizeKey(productType);

  var fromCategory = categoryFromName(categoryKey);
  if (fromCategory) return fromCategory;

  if (PRODUCT_TYPE_MAP[productTypeKey]) return PRODUCT_TYPE_MAP[productTypeKey];

  return '';
}

function categoryFromName(categoryKey) {
  if (!categoryKey) return '';
  if (CATEGORY_MAP[categoryKey]) return CATEGORY_MAP[categoryKey];

  for (var mapKey in CATEGORY_MAP) {
    if (!Object.prototype.hasOwnProperty.call(CATEGORY_MAP, mapKey)) continue;
    if (categoryKey.indexOf(mapKey) !== -1) return CATEGORY_MAP[mapKey];
  }

  return '';
}

// ---------------------------------------------------------------------------
// Shared: errors / option helpers / blanks
// ---------------------------------------------------------------------------

function collectImportErrors(supplier, details, normalizedCategory) {
  // These codes are intended for tags/review workflows and quick debugging.
  var errors = [];

  if (!supplier) errors.push('unknown-supplier');
  if (details.sizeError) errors.push(details.sizeError);
  if (details.conditionError) errors.push(details.conditionError);
  if (details.boxError) errors.push(details.boxError);
  if (!normalizedCategory) errors.push('unknown-category');

  return errors;
}

function findOption(selectedOptions, optionNames) {
  // Shopify option names can vary by capitalization; compare normalized names.
  // Prefer an option whose name matches a configured size name. Blank names are
  // only accepted when the value looks like a size (CSV continuation rows), so
  // a blank-named Color/"Red" ahead of Size does not steal the match.
  var normalizedNames = [];
  var allowBlankName = false;
  for (var i = 0; i < optionNames.length; i++) {
    var normalized = normalizeKey(optionNames[i]);
    normalizedNames.push(normalized);
    if (normalized === '') allowBlankName = true;
  }

  var blankNameCandidate = null;

  for (var j = 0; j < selectedOptions.length; j++) {
    var option = selectedOptions[j];
    if (!option || typeof option !== 'object') continue;

    var optionName = normalizeKey(option.name);
    var valueText = optionValueText(option.value);

    if (optionName && normalizedNames.indexOf(optionName) !== -1) {
      return option;
    }

    if (allowBlankName && optionName === '' && !blankNameCandidate && looksLikeSizeValue(valueText)) {
      blankNameCandidate = option;
    }
  }

  return blankNameCandidate;
}

function optionValueText(value) {
  if (value === null || value === undefined) return '';
  return value.toString();
}

function looksLikeSizeValue(valueText) {
  // Cheap gate for blank-named CSV continuation rows. Full parsing still runs
  // afterward; this only decides whether a blank-named option may be Size.
  var text = (valueText || '').toString().trim();
  if (!text) return false;
  var sizePart = text.split(/\s+-\s+/)[0] || '';
  sizePart = sizePart.replace(/\s*\([^)]*\)\s*$/, '').trim();
  return (
    /^(?:US\s*)?\d/i.test(sizePart) ||
    /^EU\s*\d/i.test(sizePart) ||
    /^\d+(?:\.\d+)?\s*[MWYCmwyc]\b/i.test(sizePart) ||
    /^[YW]\s*\//i.test(sizePart)
  );
}

function normalizeKey(value) {
  // Shared normalization for option names and map keys.
  return (value || '').toString().trim().toLowerCase();
}

function blankDetails(sizeError) {
  // No usable Size option (or unknown parser). Leave condition/box unset —
  // size gates those fields.
  return {
    normalizedMSize: '',
    normalizedWSize: '',
    normalizedCondition: '',
    normalizedBox: '',
    sizeError: sizeError || 'unknown-size',
    conditionError: '',
    boxError: ''
  };
}

// ---------------------------------------------------------------------------
// Supplier parsers — KCP size option (dash segments + cascades)
// ---------------------------------------------------------------------------

function parseSupplierDetails(supplier, selectedOptions, product) {
  // Add new parser dispatches here, for example:
  // if (supplier.parser === 'other-vendor-…') return parseOtherVendor(...);
  if (supplier.parser === 'kcp-size-option') {
    return parseKcpSizeOption(supplier, selectedOptions, product || {});
  }

  // Unknown parser names fail safely and create review tags downstream.
  return blankDetails();
}

function parseKcpSizeOption(supplier, selectedOptions, product) {
  // KCP Size option: optional " - "-separated size | condition | box segments.
  //   "12.5M/14W - Brand New - No Box"  →  [size, condition, box]
  //   "10.5M / 12W"                     →  [size]
  //   "7Y - Pre-Owned"                  →  [size, condition]
  var sizeOption = findOption(selectedOptions, supplier.sizeOptionNames || ['Size']);
  if (!sizeOption) return blankDetails('unknown-size');

  var segments = optionValueText(sizeOption.value).split(/\s+-\s+/);
  var sizeText = segments[0] || '';
  var conditionText = segments[1] || '';
  var boxText = segments[2] || '';
  var sizes = parseSizeText(sizeText);

  // Size gates condition/box. Examples that stop here (leave condition/box unset):
  //   "3Y", "9C", "Y / 1.5W" → child-size
  //   "Default Title", "copyt:temporary:size" → unknown-size
  //   "14M/12.5W", "7Y / 1.5W" → inconsistent-size (US: W ≠ M+1.5)
  if (!sizes.m && !sizes.w) {
    return {
      normalizedMSize: '',
      normalizedWSize: '',
      normalizedCondition: '',
      normalizedBox: '',
      sizeError: classifyUnparsedSize(sizeText),
      conditionError: '',
      boxError: ''
    };
  }

  if (!sizesAreConsistent(sizes)) {
    return {
      normalizedMSize: '',
      normalizedWSize: '',
      normalizedCondition: '',
      normalizedBox: '',
      sizeError: 'inconsistent-size',
      conditionError: '',
      boxError: ''
    };
  }

  // Condition: prefer the Size-option condition segment when present.
  //   "10M - Pre-Owned - No Box" → map "Pre-Owned"
  //   "10M - Refurbished - No Box" → empty + unknown-condition
  //   "10.5M / 12W" (no condition segment) → metafield / Body / tags / type / title
  var normalizedCondition = '';
  var conditionError = '';
  if (conditionText) {
    normalizedCondition = mapConditionExact(conditionText);
    if (!normalizedCondition) conditionError = 'unknown-condition';
  } else {
    normalizedCondition = resolveKcpCondition(product);
  }

  // Box: prefer the Size-option box segment when present.
  //   "10M - Pre-Owned - No Box" → map "No Box"
  //   "10M - Brand New - Custom Acrylic Case" → empty + unknown-box
  //   "12M / 13.5W (Missing Lid)" → paren / tags / Body Box: cascade
  var normalizedBox = '';
  var boxError = '';
  if (boxText) {
    normalizedBox = mapBox(boxText);
    if (!normalizedBox) boxError = 'unknown-box';
  } else {
    normalizedBox = resolveKcpBox(sizeText, product);
  }

  return {
    normalizedMSize: sizes.m || '',
    normalizedWSize: sizes.w || '',
    normalizedCondition: normalizedCondition,
    normalizedBox: normalizedBox,
    sizeError: '',
    conditionError: conditionError,
    boxError: boxError
  };
}

function resolveKcpCondition(product) {
  // KCP cascade when the Size option has no condition segment.
  // Sources, first hit wins: metafield → Body → tags → type → title.
  // Exact bare "new" is accepted on metafield, Body, tags, and option segments
  // (mapConditionExact) — not on title/type free text.
  // No hit → empty string (unset), not an import error.
  var mapped = mapMetafieldCondition(product.conditionMetafield);
  if (mapped) return mapped;

  mapped = mapBodyCondition(product.description);
  if (mapped) return mapped;

  mapped = conditionFromTags(product.tags);
  if (mapped) return mapped;

  mapped = conditionFromText(product.productType);
  if (mapped) return mapped;

  return conditionFromText(product.title) || '';
}

function resolveKcpBox(sizeText, product) {
  // KCP cascade when the Size option has no box segment.
  // Try, in order:
  //   1) trailing paren on size text — "12M / 13.5W (Missing Lid)"
  //   2) tags — "no_box", "special-no_box"
  //   3) Body labeled field — "Box: No Box" / "<strong>Box:</strong> Replacement Box"
  // No signal → leave unset (do not invent With Box).

  var parenMatch = (sizeText || '').match(/\(([^)]+)\)\s*$/);
  if (parenMatch) {
    var fromParen = mapBox(parenMatch[1]);
    if (fromParen) return fromParen;
  }

  var fromTags = boxFromTags(product.tags);
  if (fromTags) return fromTags;

  var fromBody = mapBox(bodyField(product.description, 'Box'));
  if (fromBody) return fromBody;

  return '';
}

export { NORMALIZED_CONDITION, NORMALIZED_BOX, NORMALIZED_CATEGORY, CONDITION_MAP, BOX_MAP, PRODUCT_TYPE_MAP, CATEGORY_MAP, CATEGORY_GIDS };
