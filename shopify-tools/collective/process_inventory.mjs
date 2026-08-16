import fs from 'fs';
import path from 'path';
import main from './importer.js';

function parseCSV(text) {
  const rows = [];
  let currentRow = [];
  let currentField = '';
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    const nextChar = text[i + 1];

    if (inQuotes) {
      if (char === '"' && nextChar === '"') {
        currentField += '"';
        i++;
      } else if (char === '"') {
        inQuotes = false;
      } else {
        currentField += char;
      }
    } else {
      if (char === '"') {
        inQuotes = true;
      } else if (char === ',') {
        currentRow.push(currentField);
        currentField = '';
      } else if (char === '\r' && nextChar === '\n') {
        currentRow.push(currentField);
        rows.push(currentRow);
        currentRow = [];
        currentField = '';
        i++;
      } else if (char === '\n' || char === '\r') {
        currentRow.push(currentField);
        rows.push(currentRow);
        currentRow = [];
        currentField = '';
      } else {
        currentField += char;
      }
    }
  }
  if (currentField !== '' || currentRow.length > 0) {
    currentRow.push(currentField);
    rows.push(currentRow);
  }
  return rows;
}

function escapeCSVField(val) {
  if (val === null || val === undefined) return '""';
  const str = String(val);
  return '"' + str.replace(/"/g, '""') + '"';
}

function processInventory() {
  const csvData = fs.readFileSync('kc-inventory.csv', 'utf8');
  const rows = parseCSV(csvData);
  if (rows.length === 0) return;

  const headers = rows[0];
  const headerMap = {};
  headers.forEach((h, idx) => {
    headerMap[h.trim()] = idx;
  });

  const outputHeaders = [
    'Handle',
    'inputVariantSku',
    'inputVendor',
    'inputTitle',
    'inputBodyHtml',
    'inputProductCategory',
    'inputType',
    'inputOption1Name',
    'inputOption1Value',
    'inputOption2Name',
    'inputOption2Value',
    'inputOption3Name',
    'inputOption3Value',
    'prefix',
    'originalSku',
    'newSku',
    'normalizedMSize',
    'normalizedWSize',
    'normalizedCondition',
    'normalizedBox',
    'originalTitle',
    'originalDescription',
    'normalizedTitle',
    'normalizedDescription',
    'normalizedCategory',
    'normalizedCategoryGid',
    'importErrors',
    'hasImportErrors'
  ];

  const outputRows = [outputHeaders.map(escapeCSVField).join(',')];

  // Map to track product-level fields by handle
  const productMap = {};

  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    if (!row || row.length === 0) continue;

    const getVal = (colName) => {
      const idx = headerMap[colName];
      return idx !== undefined && row[idx] ? row[idx] : '';
    };

    const handle = getVal('Handle');
    const sku = getVal('Variant SKU');
    const opt1Val = getVal('Option1 Value');

    // Skip image-only rows (rows without SKU and without Option values)
    if (!sku && !opt1Val) continue;

    // Cache/update product info for this handle
    if (handle) {
      if (!productMap[handle]) {
        productMap[handle] = {
          vendor: '',
          title: '',
          description: '',
          category: '',
          productType: ''
        };
      }
      if (getVal('Vendor')) productMap[handle].vendor = getVal('Vendor');
      if (getVal('Title')) productMap[handle].title = getVal('Title');
      if (getVal('Body (HTML)')) productMap[handle].description = getVal('Body (HTML)');
      if (getVal('Product Category')) productMap[handle].category = getVal('Product Category');
      if (getVal('Type')) productMap[handle].productType = getVal('Type');
    }

    const parent = (handle && productMap[handle]) ? productMap[handle] : {
      vendor: getVal('Vendor'),
      title: getVal('Title'),
      description: getVal('Body (HTML)'),
      category: getVal('Product Category'),
      productType: getVal('Type')
    };

    const selectedOptions = [];
    for (let optNum = 1; optNum <= 3; optNum++) {
      const optName = getVal(`Option${optNum} Name`);
      const val = getVal(`Option${optNum} Value`);
      if (val) {
        selectedOptions.push({ name: optName || '', value: val });
      }
    }

    const input = {
      productVariant: {
        id: `gid://shopify/ProductVariant/${i}`,
        sku: sku,
        selectedOptions: selectedOptions,
        product: {
          vendor: 'Kicks Collective PA',
          title: parent.title,
          description: parent.description,
          category: parent.category ? { name: parent.category } : null,
          productType: parent.productType
        }
      }
    };

    const result = main(input);

    const outRow = [
      escapeCSVField(handle),
      escapeCSVField(sku),
      escapeCSVField(parent.vendor),
      escapeCSVField(parent.title),
      escapeCSVField(parent.description),
      escapeCSVField(parent.category),
      escapeCSVField(parent.productType),
      escapeCSVField(getVal('Option1 Name')),
      escapeCSVField(getVal('Option1 Value')),
      escapeCSVField(getVal('Option2 Name')),
      escapeCSVField(getVal('Option2 Value')),
      escapeCSVField(getVal('Option3 Name')),
      escapeCSVField(getVal('Option3 Value')),
      escapeCSVField(result.prefix),
      escapeCSVField(result.originalSku),
      escapeCSVField(result.newSku),
      escapeCSVField(result.normalizedMSize),
      escapeCSVField(result.normalizedWSize),
      escapeCSVField(result.normalizedCondition),
      escapeCSVField(result.normalizedBox),
      escapeCSVField(result.originalTitle),
      escapeCSVField(result.originalDescription),
      escapeCSVField(result.normalizedTitle),
      escapeCSVField(result.normalizedDescription),
      escapeCSVField(result.normalizedCategory),
      escapeCSVField(result.normalizedCategoryGid),
      escapeCSVField(result.importErrors),
      escapeCSVField(result.hasImportErrors)
    ];

    outputRows.push(outRow.join(','));
  }

  fs.writeFileSync('kc-output.csv', outputRows.join('\n'), 'utf8');
  console.log(`Processed ${outputRows.length - 1} variant records -> kc-output.csv`);
}

processInventory();

