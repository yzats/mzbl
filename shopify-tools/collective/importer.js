var CATEGORY_GIDS = {
  Sneakers: 'gid://shopify/TaxonomyCategory/aa-sneakers'
};

// Add future suppliers here. If a supplier encodes size/condition/box
// differently, give it a different parser name and add that parser below.
var SUPPLIERS = {
  'Kicks Collective PA': {
    // Prefix added to Shopify's variant SKU.
    prefix: 'KCP',

    // Chooses which parser function handles this supplier's option format.
    parser: 'composite-shoe',

    // KCP title wording is usable as-is; normalize capitalization only.
    titleFormatter: 'title-case',

    // Description is generated from normalized data, not supplier prose.
    descriptionFormatter: 'condition-box',

    // Option names to search when looking for supplier size/details.
    sizeOptionNames: ['Size', 'Shoe size', ''],

    // Keys are normalized to lowercase before lookup.
    conditionMap: {
      'brand new': 'Brand New',
      'new': 'Brand New',
      'pre-owned': 'Worn',
      'worn': 'Worn',
      'used': 'Worn',
      'tried on': 'Worn',
      'vnds': 'Worn',
      'lightly worn': 'Worn',
      'moderately worn': 'Worn',
      'heavily worn': 'Worn'
    },

    // Keys are normalized to lowercase before lookup.
    boxMap: {
      'original box (good)': 'With Box',
      'original box (damaged)': 'Damaged Box',
      'damaged box': 'Damaged Box',
      'replacement box': 'Replacement Box',
      'no box': 'No Box',
      'no_box': 'No Box',
      'special-no_box': 'No Box',
      'missing lid': 'With Box - Missing Lid'
    }
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
  
  // Capture the supplier's original SKU as-is for reference
  var originalSku = productVariant.sku || '';

  // Supplier parsing is isolated here so future suppliers can differ without
  // changing the output fields expected by the rest of the workflow.
  var selectedOptions = Array.isArray(productVariant.selectedOptions)
    ? productVariant.selectedOptions
    : [];
  var parsedDetails = supplier
    ? parseSupplierDetails(supplier, selectedOptions, product)
    : blankDetails();

  // Category is product-level; size/condition/box are variant-level metafields.
  var originalTitle = product.title || '';
  var originalDescription = product.description || '';
  var normalizedTitle = normalizeTitle(product.title || '', supplier);
  var normalizedDescription = normalizeDescription(parsedDetails, supplier);
  var normalizedCategory = normalizeCategory(product.category, product.productType);
  var normalizedCategoryGid = CATEGORY_GIDS[normalizedCategory] || '';

  // A comma-separated error string is easier to pass through Shopify Flow than
  // an array, while hasImportErrors remains convenient for conditions.
  var importErrors = collectImportErrors(supplier, parsedDetails, normalizedCategory);

  // Keep this return shape aligned with the Run code output schema in Shopify.
  return {
    prefix: supplierCode,
    variantId: variantId,
    newSku: newSku,
    originalSku: originalSku,
    normalizedMSize: parsedDetails.normalizedMSize.toString(),
    normalizedWSize: parsedDetails.normalizedWSize.toString(),
    normalizedCondition: parsedDetails.normalizedCondition,
    normalizedBox: parsedDetails.normalizedBox,
    originalTitle: originalTitle,
    originalDescription: originalDescription,
    normalizedTitle: normalizedTitle,
    normalizedDescription: normalizedDescription,
    normalizedCategory: normalizedCategory,
    normalizedCategoryGid: normalizedCategoryGid,
    importErrors: importErrors.join(','),
    hasImportErrors: importErrors.length > 0
  };
}

function normalizeDescription(details, supplier) {
  if (!supplier) return '';

  // Add future description strategies here when suppliers need a different
  // product description format.
  if (supplier.descriptionFormatter === 'condition-box') {
    return buildConditionBoxDescription(details);
  }

  return '';
}

function buildConditionBoxDescription(details) {
  // Public description from whatever we resolved.
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
    at: true,
    by: true,
    for: true,
    in: true,
    of: true,
    on: true,
    or: true,
    the: true,
    to: true,
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

function parseSupplierDetails(supplier, selectedOptions, product) {
  // Add new parser dispatches here, for example:
  // if (supplier.parser === 'separate-options') return parseSeparateOptions(...);
  if (supplier.parser === 'composite-shoe') {
    return parseCompositeShoeDetails(supplier, selectedOptions, product || {});
  }

  // Unknown parser names fail safely and create review tags downstream.
  return blankDetails();
}

function parseCompositeShoeDetails(supplier, selectedOptions, product) {
  // Size option values are either composite or size-only, split on " - ":
  //   "12.5M/14W - Brand New - No Box"  →  [size, condition, box]
  //   "10.5M / 12W"                     →  [size]
  //   "7Y - Pre-Owned"                  →  [size, condition]
  var sizeOption = findOption(selectedOptions, supplier.sizeOptionNames || ['Size']);
  if (!sizeOption) return blankDetails('unknown-size');

  var segments = optionValueText(sizeOption.value).split(/\s+-\s+/);
  var sizeText = segments[0] || '';
  var conditionText = segments[1] || '';
  var boxText = segments[2] || '';
  var sizes = parseUsSizeText(sizeText);

  // Size gates condition/box. Examples that stop here (leave condition/box unset):
  //   "3Y", "9C", "Y / 1.5W" → child-size
  //   "Default Title", "copyt:temporary:size" → unknown-size
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

  // Condition: prefer the Size-option condition segment when present.
  //   "10M - Pre-Owned - No Box" → map "Pre-Owned"
  //   "10M - Refurbished - No Box" → empty + unknown-condition
  //   "10.5M / 12W" (no condition segment) → metafield / Body / tags / type / title
  var normalizedCondition = '';
  var conditionError = '';
  if (conditionText) {
    normalizedCondition = supplier.conditionMap[normalizeKey(conditionText)] || '';
    if (!normalizedCondition) conditionError = 'unknown-condition';
  } else {
    normalizedCondition = resolveCondition(supplier, product);
  }

  // Box: prefer the Size-option box segment when present.
  //   "10M - Pre-Owned - No Box" → map "No Box"
  //   "10M - Brand New - Custom Acrylic Case" → empty + unknown-box
  //   "12M / 13.5W (Missing Lid)" → paren / tags / Body Box: cascade
  var normalizedBox = '';
  var boxError = '';
  if (boxText) {
    normalizedBox = supplier.boxMap[normalizeKey(boxText)] || '';
    if (!normalizedBox) boxError = 'unknown-box';
  } else {
    normalizedBox = resolveBox(supplier, sizeText, product);
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

function classifyUnparsedSize(sizeText) {
  // Strip trailing paren notes the same way size parsing does,
  // e.g. "7Y (Missing Lid)" → "7Y".
  var text = (sizeText || '').trim().replace(/\s*\([^)]*\)\s*$/, '').trim();
  if (!text) return 'unknown-size';

  // Youth / GS below 3.5Y, or broken values without a youth number.
  // Examples: "3Y", "3Y / 4.5W", "Y / 1.5W"
  // (3.5Y+ is converted to adult M/W in parseUsSizeText.)
  if (/\d(?:\.\d+)?\s*Y\b/i.test(text) || /^Y(?:\s*\/|\s*$)/i.test(text)) {
    return 'child-size';
  }

  // Child / PS, e.g. "9C", "13.5C"
  if (/\d(?:\.\d+)?\s*C\b/i.test(text)) {
    return 'child-size';
  }

  return 'unknown-size';
}

function resolveCondition(supplier, product) {
  // Used when the Size option has no condition segment (size-only values).
  // Example: option "10.5M / 12W" with metafield "Pre-Owned" → Worn.
  // Sources, first hit wins: metafield → Body "Condition:" → tags → type → title.
  // No hit → empty string (unset), not an import error.
  var sources = [
    product.conditionMetafield,
    bodyField(product.description, 'Condition'),
    product.tags,
    product.productType,
    product.title
  ];

  for (var i = 0; i < sources.length; i++) {
    var mapped = conditionFromText(supplier, sources[i]);
    if (mapped) return mapped;
  }

  return '';
}

function resolveBox(supplier, sizeText, product) {
  // Used when the Size option has no box segment.
  // Try, in order:
  //   1) trailing paren on size text — "12M / 13.5W (Missing Lid)"
  //   2) tags — "no_box", "special-no_box"
  //   3) Body labeled field — "Box: No Box" / "<strong>Box:</strong> Replacement Box"
  // No signal → leave unset (do not invent With Box).

  var parenMatch = (sizeText || '').match(/\(([^)]+)\)\s*$/);
  if (parenMatch) {
    var fromParen = mapBox(supplier, parenMatch[1]);
    if (fromParen) return fromParen;
  }

  var fromTags = boxFromTags(supplier, product.tags);
  if (fromTags) return fromTags;

  var fromBody = mapBox(supplier, bodyField(product.description, 'Box'));
  if (fromBody) return fromBody;

  return '';
}

function mapBox(supplier, raw) {
  if (!raw) return '';
  return supplier.boxMap[normalizeKey(raw)] || '';
}

function boxFromTags(supplier, tags) {
  if (!tags) return '';

  var parts = tags.toString().split(',');
  for (var i = 0; i < parts.length; i++) {
    var mapped = mapBox(supplier, parts[i]);
    if (mapped) return mapped;
  }

  return '';
}

function bodyField(html, label) {
  // Read "Label: value" from Body regardless of wrapping tags
  // (e.g. <strong>Box:</strong> No Box or plain "Condition: Pre-Owned").
  if (!html || !label) return '';

  var text = html.toString()
    .replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/<\/p>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&');

  var escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  var re = new RegExp('(?:^|\\n)\\s*' + escaped + ':\\s*([^\\n]+)', 'i');
  var match = text.match(re);
  return match ? match[1].trim() : '';
}

function conditionFromText(supplier, text) {
  var key = normalizeKey(text);
  if (!key) return '';

  // Exact map hit (e.g. metafield "Brand New" / "Pre-Owned").
  if (supplier.conditionMap[key]) return supplier.conditionMap[key];

  // Substring signals. Check worn/pre-owned/used before brand new when both appear.
  if (key.indexOf('pre-owned') !== -1 || key.indexOf('pre owned') !== -1) {
    return supplier.conditionMap['pre-owned'] || '';
  }
  if (key.indexOf('lightly worn') !== -1 ||
      key.indexOf('moderately worn') !== -1 ||
      key.indexOf('heavily worn') !== -1 ||
      key.indexOf('lightly_worn') !== -1 ||
      key.indexOf('moderately_worn') !== -1 ||
      key.indexOf('heavily_worn') !== -1) {
    return supplier.conditionMap['pre-owned'] || '';
  }
  if (/\bworn\b/.test(key) || /\bused\b/.test(key)) {
    return supplier.conditionMap['worn'] || supplier.conditionMap['used'] || supplier.conditionMap['pre-owned'] || '';
  }
  if (key.indexOf('brand new') !== -1) {
    return supplier.conditionMap['brand new'] || '';
  }
  // Standalone "new" means Brand New; skip the brand name "New Balance".
  if (/\bnew\b/.test(key) && key.indexOf('new balance') === -1) {
    return supplier.conditionMap['brand new'] || supplier.conditionMap['new'] || '';
  }

  return '';
}

function mapCondition(supplier, raw) {
  return conditionFromText(supplier, raw);
}

function parseUsSizeText(sizeText) {
  // Parse the size segment only (first " - "-separated segment of the Size option).
  // Examples that must match as a whole token (no partial matches):
  //   "12.5M/14W", "10.5M / 12W", "10.5M", "11.5W", "10.5", "EU44", "3.5Y", "7Y / 8.5W"
  // Examples that stay unparsed: "Y / 1.5W", "3Y", "9C", "Default Title"
  var text = (sizeText || '').trim();

  // Drop trailing notes glued onto size-only options,
  // e.g. "12M / 13.5W (Missing Lid)" → "12M / 13.5W".
  text = text.replace(/\s*\([^)]*\)\s*$/, '').trim();

  // European size conversion (e.g., "EU44", "EU 44", "EU44.5")
  var euMatch = text.match(/^EU\s*([0-9]+(?:\.[0-9]+)?)$/i);
  if (euMatch) {
    var euVal = parseFloat(euMatch[1]);
    if (!isNaN(euVal)) {
      return { m: (euVal - 33).toString(), w: (euVal - 31).toString() };
    }
  }

  // Men's and women's sizes in the common "12.5M/14W" order (spaces optional).
  var match = text.match(/^(?:US\s*)?([0-9]+(?:\.[0-9]+)?)\s*M(?:en'?s)?\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*W$/i);
  if (match) return { m: match[1], w: match[2] };

  // Same data in reverse order, e.g. "14W/12.5M".
  match = text.match(/^(?:US\s*)?([0-9]+(?:\.[0-9]+)?)\s*W(?:omen'?s)?\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*M$/i);
  if (match) return { m: match[2], w: match[1] };

  // Men's-only size. Derive women's as men's + 1.5 (standard US pairing).
  match = text.match(/^(?:US\s*)?([0-9]+(?:\.[0-9]+)?)\s*M(?:en'?s)?$/i);
  if (match) return { m: match[1], w: offsetUsSize(match[1], 1.5) };

  // Women's-only size. Derive men's as women's - 1.5.
  match = text.match(/^(?:US\s*)?([0-9]+(?:\.[0-9]+)?)\s*W(?:omen'?s)?$/i);
  if (match) return { m: offsetUsSize(match[1], -1.5), w: match[1] };

  // Bare number (common on pre-owned single-SKU rows) — treat as men's.
  match = text.match(/^([0-9]+(?:\.[0-9]+)?)$/);
  if (match) return { m: match[1], w: offsetUsSize(match[1], 1.5) };

  // Youth (GS) 3.5Y and up map onto adult US sizing: men's = youth number,
  // women's = youth + 1.5 (or as written when a Y/W pair is present).
  //   "3.5Y" → M 3.5 / W 5
  //   "7Y" → M 7 / W 8.5
  //   "6.5Y / 8W" → M 6.5 / W 8
  // Below 3.5Y and child (C) sizes stay unparsed → child-size.
  match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*Y\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*W$/i);
  if (match && parseFloat(match[1]) >= 3.5) {
    return { m: match[1], w: match[2] };
  }

  match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*W\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*Y$/i);
  if (match && parseFloat(match[2]) >= 3.5) {
    return { m: match[2], w: match[1] };
  }

  match = text.match(/^([0-9]+(?:\.[0-9]+)?)\s*Y$/i);
  if (match && parseFloat(match[1]) >= 3.5) {
    return { m: match[1], w: offsetUsSize(match[1], 1.5) };
  }

  // Unknown size format. The caller turns this into child-size or unknown-size.
  return { m: '', w: '' };
}

function offsetUsSize(sizeText, delta) {
  // US shoe sizes step in halves; round to nearest 0.5 to avoid float noise.
  var value = Math.round((parseFloat(sizeText) + delta) * 2) / 2;
  return value.toString();
}

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

  // Match if category is or contains shoes or sneakers (e.g., 'Apparel & Accessories > Shoes > Sneakers')
  if (categoryKey === 'shoes' || categoryKey === 'sneakers' ||
      categoryKey.indexOf('shoes') !== -1 || categoryKey.indexOf('sneakers') !== -1) {
    return 'Sneakers';
  }

  // Fallback match for all footwear product types present in inventory
  var validShoeTypes = [
    "men's shoes",
    "women's shoes",
    "kid's shoes",
    "kids's shoes",
    "toddler's",
    "toddlers",
    "preschool",
    "shoes",
    "sneakers",
    "pre-owned sneakers"
  ];

  if (validShoeTypes.indexOf(productTypeKey) !== -1) return 'Sneakers';

  return '';
}

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