var UNKNOWN = 'unknown';

// Shopify's productUpdate mutation expects taxonomy category GIDs, not display
// names. Keep this map small and explicit so unsupported categories are easy to
// spot and review.
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
      'pre-owned': 'Worn'
    },

    // Keys are normalized to lowercase before lookup.
    boxMap: {
      'original box (good)': 'With Box',
      'original box (damaged)': 'Damaged Box',
      'replacement box': 'Replacement Box',
      'no box': 'No Box',
      'missing lid': 'With Box - Missing Lid'
    },

    // Used when the supplier option has no explicit box segment.
    defaultBox: 'With Box'
  }
};

export default function main(input) {
  // Keep input extraction defensive. If Shopify omits a field, the workflow
  // should produce reviewable "unknown" outputs rather than throwing.
  var productVariant = input.productVariant || {};
  var product = productVariant.product || {};
  var supplier = SUPPLIERS[product.vendor] || null;

  // Extract the numeric variant ID from the full GID (e.g., gid://shopify/ProductVariant/4521987654321)
  var variantId = productVariant.id ? productVariant.id.split('/').pop() : '';
  
  // Get the supplier code from the SUPPLIERS lookup
  var supplierCode = supplier ? supplier.prefix : 'UNK';
  
  // Build the new SKU in format {SUPPLIER_CODE}-{variantId}
  // e.g., KCP-4521987654321
  var newSku = supplierCode + '-' + variantId;
  
  // Capture the supplier's original SKU as-is for reference
  var originalSku = productVariant.sku || '';

  // Supplier parsing is isolated here so future suppliers can differ without
  // changing the output fields expected by the rest of the workflow.
  var parsedDetails = supplier
    ? parseSupplierDetails(supplier, productVariant.selectedOptions || [])
    : blankDetails();

  // Category is product-level; size/condition/box are variant-level metafields.
  var originalTitle = product.title || '';
  var originalDescription = product.description || '';
  var normalizedTitle = normalizeTitle(product.title || '', supplier);
  var normalizedDescription = normalizeDescription(parsedDetails, supplier);
  var normalizedCategory = normalizeCategory(product.category, product.productType);
  var normalizedCategoryGid = CATEGORY_GIDS[normalizedCategory] || '';
  var hasUnknownSize = !parsedDetails.normalizedMSize && !parsedDetails.normalizedWSize;

  // A comma-separated error string is easier to pass through Shopify Flow than
  // an array, while hasImportErrors remains convenient for conditions.
  var importErrors = collectImportErrors(supplier, parsedDetails, normalizedCategory, hasUnknownSize);

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
  // Keep the public description compact and derived from normalized values only.
  return details.normalizedCondition + ' (' + details.normalizedBox + ')';
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

function parseSupplierDetails(supplier, selectedOptions) {
  // Add new parser dispatches here, for example:
  // if (supplier.parser === 'separate-options') return parseSeparateOptions(...);
  if (supplier.parser === 'composite-shoe') {
    return parseCompositeShoeDetails(supplier, selectedOptions);
  }

  // Unknown parser names fail safely and create review tags downstream.
  return blankDetails();
}

function parseCompositeShoeDetails(supplier, selectedOptions) {
  // KCP currently stores multiple facts in one option value:
  // "12.5M/14W - Brand New - No Box"
  var sizeOption = findOption(selectedOptions, supplier.sizeOptionNames || ['Size']);
  if (!sizeOption) return blankDetails();

  // Split into size, shoe condition, and optional box condition.
  var parts = (sizeOption.value || '').split(/\s+-\s+/);
  var sizes = parseUsSizeText(parts[0]);

  return {
    normalizedMSize: sizes.m || '',
    normalizedWSize: sizes.w || '',
    normalizedCondition: supplier.conditionMap[normalizeKey(parts[1])] || UNKNOWN,
    normalizedBox: parts[2]
      ? (supplier.boxMap[normalizeKey(parts[2])] || UNKNOWN)
      : (supplier.defaultBox || UNKNOWN)
  };
}

function parseUsSizeText(sizeText) {
  var text = (sizeText || '').trim();

  // European size conversion (e.g., "EU44", "EU 44", "EU44.5")
  var euMatch = text.match(/^(?:EU\s*)?([0-9]+(?:\.[0-9]+)?)$/i) || text.match(/^EU\s*([0-9]+(?:\.[0-9]+)?)$/i);
  if (euMatch) {
    var euVal = parseFloat(euMatch[1]);
    if (!isNaN(euVal)) {
      var mVal = (euVal - 33).toString();
      var wVal = (euVal - 31).toString();
      return { m: mVal, w: wVal };
    }
  }

  // Men's and women's sizes in the common "12.5M/14W" order.
  var match = text.match(/([0-9]+(?:\.[0-9]+)?)\s*M(?:en'?s)?\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*W/i);
  if (match) return { m: match[1], w: match[2] };

  // Same data in reverse order, e.g. "14W/12.5M".
  match = text.match(/([0-9]+(?:\.[0-9]+)?)\s*W(?:omen'?s)?\s*\/\s*([0-9]+(?:\.[0-9]+)?)\s*M/i);
  if (match) return { m: match[2], w: match[1] };

  // Men's-only size.
  match = text.match(/(?:US\s*)?([0-9]+(?:\.[0-9]+)?)\s*M(?:en'?s)?/i);
  if (match) return { m: match[1], w: '' };

  // Women's-only size.
  match = text.match(/(?:US\s*)?([0-9]+(?:\.[0-9]+)?)\s*W(?:omen'?s)?/i);
  if (match) return { m: '', w: match[1] };

  // Unknown size format. The caller turns this into an import error.
  return { m: '', w: '' };
}

function normalizeCategory(category, productType) {
  // Normalize known sneaker/shoe categories.
  var categoryName = category && category.name ? category.name : '';
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
    "sneakers"
  ];

  if (validShoeTypes.indexOf(productTypeKey) !== -1) return 'Sneakers';

  return UNKNOWN;
}

function collectImportErrors(supplier, details, normalizedCategory, hasUnknownSize) {
  // These codes are intended for tags/review workflows and quick debugging.
  var errors = [];

  if (!supplier) errors.push('unknown-supplier');
  if (hasUnknownSize) errors.push('unknown-size');
  if (details.normalizedCondition === UNKNOWN) errors.push('unknown-condition');
  if (details.normalizedBox === UNKNOWN) errors.push('unknown-box');
  if (normalizedCategory === UNKNOWN) errors.push('unknown-category');

  return errors;
}

function findOption(selectedOptions, optionNames) {
  // Shopify option names can vary by capitalization; compare normalized names.
  var normalizedNames = [];
  for (var i = 0; i < optionNames.length; i++) {
    normalizedNames.push(normalizeKey(optionNames[i]));
  }

  for (var j = 0; j < selectedOptions.length; j++) {
    if (normalizedNames.indexOf(normalizeKey(selectedOptions[j].name)) !== -1) {
      return selectedOptions[j];
    }
  }

  return null;
}

function normalizeKey(value) {
  // Shared normalization for option names and map keys.
  return (value || '').toString().trim().toLowerCase();
}

function blankDetails() {
  // Consistent empty parse result. Downstream error collection handles review
  // decisions from these unknown values.
  return {
    normalizedMSize: '',
    normalizedWSize: '',
    normalizedCondition: UNKNOWN,
    normalizedBox: UNKNOWN
  };
}