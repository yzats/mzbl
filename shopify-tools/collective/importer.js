/**
 * Collective inventory normalizer for Shopify Flow (Run Code) and the local
 * CSV runner (process_inventory.mjs).
 *
 * Takes one productVariant (+ product) from a configured supplier and maps
 * supplier-specific encodings into stable fields for downstream metafield
 * updates and review tags.
 *
 * Shared across suppliers (see SHARED_NORMALIZATION.md):
 *   - BOX_MAP and Body "Label: value" reader
 *   - size parse / US·EU conversion / M↔W consistency / min size → size errors
 *   - category → Sneakers, sneaker condition/box description
 *
 * Supplier-specific (see KCP_NORMALIZATION_RULES.md for KCP):
 *   - which option holds size, which Body labels hold condition / box
 *   - condition label vocabulary and note wording
 *   - sanitized shoe name (source + cleanup); the size suffix is shared
 *
 * Each field resolves independently: a size error leaves sizes empty but
 * condition / box / title are still derived. Unresolved values stay empty
 * (never the string "unknown"); problems are reported via importErrors instead.
 *
 * Input (Flow Run Code query):
 *   productVariant { id sku selectedOptions { name value }
 *     product { vendor title descriptionHtml productType category { name } } }
 *
 * Outputs — derived:
 *   supplierCode              e.g. "KCP"
 *   variantId                 e.g. "4521987654321"
 *   newSku                    e.g. "KCP-4521987654321"
 *   normalizedMSize           e.g. "10.5", "12"  (empty if size failed)
 *   normalizedWSize           e.g. "12", "13.5"  (empty if size failed)
 *   normalizedCondition       NORMALIZED_CONDITION.BRAND_NEW | NORMALIZED_CONDITION.WORN | ""
 *   normalizedConditionNote   lowercase detail, e.g. "light wear",
 *                             "VNDS, no soles", "moderate wear, yellowing on the soles", or ""
 *   normalizedBox             NORMALIZED_BOX.WITH_BOX | NORMALIZED_BOX.DAMAGED_BOX | NORMALIZED_BOX.REPLACEMENT_BOX |
 *                             NORMALIZED_BOX.NO_BOX | NORMALIZED_BOX.WITH_BOX_MISSING_LID | ""
 *   normalizedTitle           sanitized shoe name (per supplier) + " (Size {normalizedMSize})"
 *                             when size is known, e.g. "Jordan 3 Cool Grey (Size 10)"
 *   normalizedDescription     e.g. "Worn (light wear), with box", "Brand New",
 *                             "Worn", "no box", or ""
 *   normalizedCategory        NORMALIZED_CATEGORY.SNEAKERS | ""
 *   normalizedCategoryGid     e.g. "gid://shopify/TaxonomyCategory/aa-8-8"
 *                             or ""
 *   importErrors              comma-separated codes, e.g. "unknown-size" or
 *                             "child-size,unknown-category" ("" if none)
 *   hasImportErrors           true | false
 *
 * Outputs — supplier (copied):
 *   supplierSku               supplier variant SKU as-is
 *   supplierTitle             product title as-is
 *   supplierDescription       product Body (HTML) as-is
 *
 * importErrors may include: unknown-supplier, child-size, unknown-size,
 * inconsistent-size, size-mismatch, unknown-condition, unknown-box,
 * unknown-title, title-mismatch, unknown-category.
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
// Shopify Standard Product Taxonomy: Apparel & Accessories > Shoes > Sneakers.
CATEGORY_GIDS[NORMALIZED_CATEGORY.SNEAKERS] = 'gid://shopify/TaxonomyCategory/aa-8-8';

// Smallest men's size we process; anything below is child-size
// (3.5Y = men's 3.5 is the first youth size mapped onto adult sizing).
var MIN_MENS_SIZE = 3.5;

// Keys are normalized to lowercase before lookup.
var BOX_MAP = {
  'good box': NORMALIZED_BOX.WITH_BOX,
  'original box': NORMALIZED_BOX.WITH_BOX,
  'damaged box': NORMALIZED_BOX.DAMAGED_BOX,
  'replacement': NORMALIZED_BOX.REPLACEMENT_BOX,
  'replacement box': NORMALIZED_BOX.REPLACEMENT_BOX,
  'no box': NORMALIZED_BOX.NO_BOX,
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
// Supplier configs & vocabularies
// ---------------------------------------------------------------------------

// KCP Body "Condition:" base values (lowercase keys) → normalized condition
// and note base. Note bases are lowercase; "vnds" is upper-cased on output.
var KCP_CONDITION_MAP = {
  'new': { condition: NORMALIZED_CONDITION.BRAND_NEW, note: '' },
  'pre-owned': { condition: NORMALIZED_CONDITION.WORN, note: '' },
  'tried on': { condition: NORMALIZED_CONDITION.WORN, note: 'tried on' },
  'vnds': { condition: NORMALIZED_CONDITION.WORN, note: 'vnds' },
  'lightly worn': { condition: NORMALIZED_CONDITION.WORN, note: 'light wear' },
  'moderately worn': { condition: NORMALIZED_CONDITION.WORN, note: 'moderate wear' },
  'heavily worn': { condition: NORMALIZED_CONDITION.WORN, note: 'heavy wear' }
};

// Add future suppliers here. If a supplier encodes size/condition/box
// differently, give it a different parser name and add that parser below.
var SUPPLIERS = {
  'Kicks Collective PA': {
    prefix: 'KCP',
    parser: 'kcp-body',
    shoeName: 'kcp-body-name',
    categorySource: 'product-type',
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

  var supplierTitle = product.title || '';
  var supplierDescription = product.descriptionHtml || '';
  var body = parseBody(supplierDescription);

  // Supplier parsing is isolated here so future suppliers can differ without
  // changing the output fields expected by the rest of the workflow.
  var selectedOptions = Array.isArray(productVariant.selectedOptions)
    ? productVariant.selectedOptions
    : [];
  var parsedDetails = supplier
    ? parseSupplierDetails(supplier, selectedOptions, body)
    : blankDetails();
  parsedDetails.normalizedBox = defaultBox(parsedDetails);

  // Title = supplier-specific sanitized shoe name + shared size suffix.
  var shoeName = deriveShoeName(supplier, supplierTitle, body);
  var normalizedTitle = buildNormalizedTitle(shoeName.name, parsedDetails.normalizedMSize);

  // Category is product-level; size/condition/box are variant-level metafields.
  var categoryInput = supplier && supplier.categorySource === 'product-type' ? null : product.category;
  var normalizedCategory = normalizeCategory(categoryInput, product.productType);
  var normalizedCategoryGid = CATEGORY_GIDS[normalizedCategory] || '';
  // Description format is shared and product-type based (not supplier-based).
  var normalizedDescription = normalizeDescription(parsedDetails, normalizedCategory);

  // A comma-separated error string is easier to pass through Shopify Flow than
  // an array, while hasImportErrors remains convenient for conditions.
  var importErrors = collectImportErrors(supplier, parsedDetails, shoeName.errors, normalizedCategory);

  // Keep this return shape aligned with the Run code output schema in Shopify.
  return {
    supplierCode: supplierCode,
    variantId: variantId,
    newSku: newSku,
    supplierSku: supplierSku,
    normalizedMSize: parsedDetails.normalizedMSize.toString(),
    normalizedWSize: parsedDetails.normalizedWSize.toString(),
    normalizedCondition: parsedDetails.normalizedCondition,
    normalizedConditionNote: parsedDetails.normalizedConditionNote,
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
  // Sneaker public description from resolved condition / note / box:
  //   "Worn (light wear), with box"
  //   "Brand New"       (no note, no box)
  //   "Worn"            (no note, no box)
  //   "no box"          (box only)
  var condition = details.normalizedCondition || '';
  var note = details.normalizedConditionNote || '';
  var box = (details.normalizedBox || '').toLowerCase();

  var head = condition;
  if (condition && note) head = condition + ' (' + note + ')';

  if (head && box) return head + ', ' + box;
  return head || box;
}

function deriveShoeName(supplier, title, body) {
  // Returns { name, errors }: the supplier's sanitized shoe name, without size.
  // Unknown suppliers / strategies keep the title as-is.
  if (supplier && supplier.shoeName === 'kcp-body-name') {
    return kcpShoeName(title, body);
  }

  return { name: title, errors: [] };
}

function buildNormalizedTitle(shoeName, mensSize) {
  // "Jordan 3 Cool Grey" + "10" → "Jordan 3 Cool Grey (Size 10)".
  // No name or no size → name unchanged.
  if (!shoeName || !mensSize) return shoeName;
  return shoeName + ' (Size ' + mensSize + ')';
}

// ---------------------------------------------------------------------------
// Shared: Body reader
// ---------------------------------------------------------------------------

function bodyPlainText(html) {
  // Convert Body HTML to plain text with line breaks preserved.
  if (!html) return '';
  return html.toString()
    .replace(/\r\n?/g, '\n')
    .replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/<\/(?:p|li|div)>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/&amp;/gi, '&');
}

function parseBody(html) {
  // Split Body into a leading name line and "Label: value" fields.
  //   "Jordan 3 Retro OG Black Cement (2024)<br>SKU: DN3707-010<br>Condition: Lightly Worn"
  //   → { name: "Jordan 3 Retro OG Black Cement (2024)",
  //       fields: { sku: "DN3707-010", condition: "Lightly Worn" } }
  // Field keys are lowercase labels. A label with nothing after the colon
  // yields "" (it never borrows the next line). First occurrence wins.
  var result = { name: '', fields: {} };
  var lines = bodyPlainText(html).split('\n');
  var seenContent = false;

  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim();
    if (!line) continue;

    var labeled = line.match(/^([A-Za-z][A-Za-z ]{0,29}):\s*(.*)$/);
    if (labeled) {
      var key = normalizeKey(labeled[1]);
      if (!Object.prototype.hasOwnProperty.call(result.fields, key)) {
        result.fields[key] = labeled[2].trim();
      }
    } else if (!seenContent) {
      result.name = line;
    }
    seenContent = true;
  }

  return result;
}

// ---------------------------------------------------------------------------
// Shared: box text → normalized values
// ---------------------------------------------------------------------------

function mapBox(raw) {
  if (!raw) return '';
  return BOX_MAP[normalizeKey(raw)] || '';
}

function defaultBox(details) {
  // Brand New with no box specified → With Box. An unrecognised box value
  // (boxError) stays empty so it is still reviewed.
  if (details.normalizedBox || details.boxError) return details.normalizedBox;
  if (details.normalizedCondition === NORMALIZED_CONDITION.BRAND_NEW) return NORMALIZED_BOX.WITH_BOX;
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
  var text = (sizeText || '').toString().trim();

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
  if (match && parseFloat(match[1]) >= MIN_MENS_SIZE) {
    return { m: match[1], w: match[2], system: 'us' };
  }

  match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*W\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*Y$/i);
  if (match && parseFloat(match[2]) >= MIN_MENS_SIZE) {
    return { m: match[2], w: match[1], system: 'us' };
  }

  match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*Y$/i);
  if (match && parseFloat(match[1]) >= MIN_MENS_SIZE) {
    return { m: match[1], w: offsetUsSize(match[1], 1.5), system: 'us' };
  }

  // Unknown size format. The caller turns this into child-size or unknown-size.
  return { m: '', w: '' };
}

function resolveSize(sizeText) {
  // Size token → normalized M/W plus a size error. Any error leaves both
  // sizes empty. Examples:
  //   "", "Default Title" → unknown-size
  //   "3Y", "9C", "Y / 1.5W" → child-size
  //   "14M/12.5W", "7Y / 1.5W" → inconsistent-size (US: W ≠ M+1.5)
  //   "3", "3M", "4.5W" → child-size (below men's 3.5)
  var sizes = parseSizeText(sizeText);
  var sizeError = '';
  if (!sizes.m && !sizes.w) sizeError = classifyUnparsedSize(sizeText);
  else if (!sizesAreConsistent(sizes)) sizeError = 'inconsistent-size';
  else if (isBelowMinSize(sizes)) sizeError = 'child-size';

  if (sizeError) return { m: '', w: '', sizeError: sizeError };
  return { m: sizes.m, w: sizes.w, sizeError: '' };
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

function isBelowMinSize(sizes) {
  // Any format that resolves under men's 3.5, e.g. "3", "3M", "4.5W", "EU36".
  return parseFloat(sizes.m) < MIN_MENS_SIZE;
}

function sameSizes(a, b) {
  return parseFloat(a.m) === parseFloat(b.m) && parseFloat(a.w) === parseFloat(b.w);
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
  var categoryKey = normalizeKey(category && category.name);
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

function collectImportErrors(supplier, details, titleErrors, normalizedCategory) {
  // These codes are intended for tags/review workflows and quick debugging.
  var errors = [];

  if (!supplier) errors.push('unknown-supplier');
  if (details.sizeError) errors.push(details.sizeError);
  if (details.sizeCheckError) errors.push(details.sizeCheckError);
  if (details.conditionError) errors.push(details.conditionError);
  if (details.boxError) errors.push(details.boxError);
  for (var i = 0; i < titleErrors.length; i++) errors.push(titleErrors[i]);
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
  var text = (valueText || '').toString().trim().replace(/\s*\([^)]*\)\s*$/, '').trim();
  if (!text) return false;
  return (
    /^(?:US\s*)?\d/i.test(text) ||
    /^EU\s*\d/i.test(text) ||
    /^\d+(?:\.\d+)?\s*[MWYCmwyc]\b/i.test(text) ||
    /^[YW]\s*\//i.test(text)
  );
}

function normalizeKey(value) {
  // Shared normalization for option names and map keys.
  return (value || '').toString().trim().toLowerCase();
}

function blankDetails() {
  // Unknown supplier or parser: nothing can be parsed.
  return {
    normalizedMSize: '',
    normalizedWSize: '',
    normalizedCondition: '',
    normalizedConditionNote: '',
    normalizedBox: '',
    sizeError: 'unknown-size',
    sizeCheckError: '',
    conditionError: '',
    boxError: ''
  };
}

// ---------------------------------------------------------------------------
// Supplier parsers — KCP (Size option + structured Body)
// ---------------------------------------------------------------------------

function parseSupplierDetails(supplier, selectedOptions, body) {
  // Add new parser dispatches here, for example:
  // if (supplier.parser === 'other-vendor-…') return parseOtherVendor(...);
  if (supplier.parser === 'kcp-body') {
    return parseKcpBody(supplier, selectedOptions, body);
  }

  // Unknown parser names fail safely and create review tags downstream.
  return blankDetails();
}

function parseKcpBody(supplier, selectedOptions, body) {
  // KCP export (Sept 2026+): size from the variant's Size option, everything
  // else from the Body template:
  //   <name>
  //   SKU: CP9652
  //   Size: 10.5M / 12W            (single-variant listings only)
  //   Condition: Moderately Worn (yellowing on the soles)
  //   Box Condition: Original Box  (pre-owned listings only)
  //   Release Date: 2017-02-11
  var sizeOption = findOption(selectedOptions, supplier.sizeOptionNames || ['Size']);
  var sizeText = sizeOption ? optionValueText(sizeOption.value) : '';
  // Size errors leave sizes empty but do not stop condition/box.
  var sizes = resolveSize(sizeText);

  // Body "Size:" is a cross-check only; unparseable Body sizes are ignored.
  var sizeCheckError = '';
  var bodySizes = parseSizeText(body.fields['size']);
  if (!sizes.sizeError && (bodySizes.m || bodySizes.w) && !sameSizes(sizes, bodySizes)) {
    sizeCheckError = 'size-mismatch';
  }

  var condition = resolveKcpCondition(body.fields['condition']);
  var box = resolveKcpBox(body.fields['box condition']);

  return {
    normalizedMSize: sizes.m,
    normalizedWSize: sizes.w,
    normalizedCondition: condition.normalizedCondition,
    normalizedConditionNote: condition.normalizedConditionNote,
    normalizedBox: box.normalizedBox,
    sizeError: sizes.sizeError,
    sizeCheckError: sizeCheckError,
    conditionError: condition.conditionError,
    boxError: box.boxError
  };
}

function resolveKcpCondition(raw) {
  // Body "Condition:" → base value + optional trailing "(note)".
  //   "Lightly Worn"                          → Worn, "light wear"
  //   "VNDS (no soles)"                       → Worn, "VNDS, no soles"
  //   "Pre-Owned"                             → Worn, ""
  //   "New"                                   → Brand New, ""
  //   missing / "" / unlisted base            → "", "" + unknown-condition
  var unknown = { normalizedCondition: '', normalizedConditionNote: '', conditionError: 'unknown-condition' };
  var value = (raw || '').trim();
  if (!value) return unknown;

  var parts = value.match(/^(.*?)\s*\(([^)]*)\)$/);
  var base = parts ? parts[1] : value;
  var extra = parts ? parts[2].trim() : '';

  var entry = KCP_CONDITION_MAP[normalizeKey(base)];
  if (!entry) return unknown;

  var noteParts = [];
  if (entry.note) noteParts.push(entry.note);
  if (extra) noteParts.push(extra);
  var note = noteParts.join(', ').toLowerCase().replace(/\bvnds\b/g, 'VNDS');

  return { normalizedCondition: entry.condition, normalizedConditionNote: note, conditionError: '' };
}

function resolveKcpBox(raw) {
  // Body "Box Condition:" → BOX_MAP. Missing or empty stays unset without an
  // error (New listings omit the line; shared defaultBox fills in With Box).
  var value = (raw || '').trim();
  if (!value) return { normalizedBox: '', boxError: '' };

  var mapped = mapBox(value);
  if (!mapped) return { normalizedBox: '', boxError: 'unknown-box' };
  return { normalizedBox: mapped, boxError: '' };
}

function kcpShoeName(title, body) {
  // Shoe name = Body name line as written, minus a women's qualifier and a
  // trailing size.
  // Title is only used to flag disagreement with the raw name line after
  // removing Title's listing suffix.
  if (!body.name) return { name: '', errors: ['unknown-title'] };

  var errors = [];
  if (title) {
    var name = comparableTitle(body.name);
    var candidates = kcpTitleCandidates(title);
    var matched = false;
    for (var i = 0; i < candidates.length; i++) {
      if (comparableTitle(candidates[i]) === name) matched = true;
    }
    if (!matched) errors.push('title-mismatch');
  }
  return { name: stripTrailingSize(stripWomensQualifier(body.name)), errors: errors };
}

function stripTrailingSize(name) {
  // Remove a size at the end of the name; it is re-added from the Size option.
  //   "…Canary 8.5W"          → "…Canary"
  //   "…Mocha Size 10"        → "…Mocha"
  //   "…Bone White 6.5M/8W"   → "…Bone White"
  // A bare trailing number is part of the model ("Yeezy 500", "Kobe 6"), and
  // so is a token that is not a valid size ("Air Force 1 3M").
  var match = name.match(/\s+(?:size\s+)?([0-9]+(?:\.[0-9]+)?\s*[MWYC]?(?:\s*\/\s*[0-9]+(?:\.[0-9]+)?\s*W)?)$/i);
  if (!match) return name;
  var hasSizeMarker = /^\s+size\s/i.test(match[0]) || /[MWYC]/i.test(match[1]);
  if (!hasSizeMarker || resolveSize(match[1]).sizeError) return name;
  return name.slice(0, match.index).trim();
}

function stripWomensQualifier(name) {
  // Remove a bracketed women's qualifier anywhere in the name:
  //   "Jordan 4 Retro Seafoam (Women's)" → "Jordan 4 Retro Seafoam"
  // Other brackets stay, e.g. "(GS)", "(2021)", "(with Socks)".
  return name
    .replace(/\s*\((?:women(?:['’]?s)?|wmns|w)\)/gi, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function kcpTitleCandidates(title) {
  // Title with its listing suffix removed step by step. Any step may equal the
  // Body name, so a model number at the end ("…Shadow 2.0") is not mistaken
  // for a size when Title has no suffix.
  //   "Jordan 3 Retro OG Black Cement (2024) 12 (Pre-Owned)" → "Jordan 3 Retro OG Black Cement (2024)"
  //   "…Olive (Women's) Size 11.5W (Pre-Owned)"            → "…Olive (Women's)"
  //   "adidas Yeezy 500 Bone White (2019) 6.5M/8W (Pre-Owned)" → "adidas Yeezy 500 Bone White (2019)"
  var full = title.toString().trim();
  var noCondition = full.replace(/\s*\((?:pre-owned|tried on|new)\)$/i, '').trim();
  var noSize = noCondition
    .replace(/\s+(?:size\s+)?[0-9]+(?:\.[0-9]+)?\s*[MWYC]?(?:\s*\/\s*[0-9]+(?:\.[0-9]+)?\s*W)?$/i, '')
    .trim();
  return [full, noCondition, noSize];
}

function comparableTitle(value) {
  return normalizeKey(value).replace(/\s+/g, ' ');
}

export { NORMALIZED_CONDITION, NORMALIZED_BOX, NORMALIZED_CATEGORY, BOX_MAP, PRODUCT_TYPE_MAP, CATEGORY_MAP, CATEGORY_GIDS, KCP_CONDITION_MAP };
