import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import main, { NORMALIZED_CONDITION, NORMALIZED_BOX, NORMALIZED_CATEGORY } from './importer.js';

const KCP = 'Kicks Collective PA';

// Body in the KCP export template. Pass null to omit a line.
function kcpBody({
  name = 'Jordan 3 Retro OG Black Cement (2024)',
  sku = 'DN3707-010',
  size = null,
  condition = 'Lightly Worn',
  box = 'Original Box',
  released = '2024-11-23'
} = {}) {
  const lines = [];
  if (name !== null) lines.push(name);
  if (sku !== null) lines.push(`SKU: ${sku}`);
  if (size !== null) lines.push(`Size: ${size}`);
  if (condition !== null) lines.push(`Condition: ${condition}`);
  if (box !== null) lines.push(`Box Condition: ${box}`);
  if (released !== null) lines.push(`Release Date: ${released}`);
  lines.push('', 'All items are shipped out quickly with safe packaging.');
  return lines.join('<br>');
}

function kcpInput(sizeValue, productExtras = {}) {
  return {
    productVariant: {
      id: 'gid://shopify/ProductVariant/1',
      sku: 'SKU-1',
      selectedOptions: [{ name: 'Size', value: sizeValue }],
      product: {
        vendor: KCP,
        title: 'Jordan 3 Retro OG Black Cement (2024) 12 (Pre-Owned)',
        productType: 'Pre-Owned Sneakers',
        descriptionHtml: kcpBody(),
        ...productExtras
      }
    }
  };
}

describe('Shopify Importer Unit Tests', () => {

  // ==========================================================================
  // 1. SKU & Prefix Normalization
  // ==========================================================================
  describe('SKU & Supplier Prefix Parsing', () => {
    it('constructs new SKU from supplier prefix and numeric Shopify variant ID', () => {
      const raw = main({
        productVariant: {
          id: 'gid://shopify/ProductVariant/4521987654321',
          sku: 'RAW-SKU-99',
          product: { vendor: KCP }
        }
      });
      assert.equal(raw.supplierCode, 'KCP');
      assert.equal(raw.variantId, '4521987654321');
      assert.equal(raw.supplierSku, 'RAW-SKU-99');
      assert.equal(raw.newSku, 'KCP-4521987654321');
    });

    it('falls back to UNK prefix and flags error for unconfigured suppliers', () => {
      const unkSupplier = main({
        productVariant: {
          id: 'gid://shopify/ProductVariant/100',
          sku: 'RAW-100',
          product: { vendor: 'Unknown', title: 'Some Title' }
        }
      });
      assert.equal(unkSupplier.supplierCode, 'UNK');
      assert.equal(unkSupplier.variantId, '100');
      assert.equal(unkSupplier.newSku, 'UNK-100');
      assert.equal(unkSupplier.supplierSku, 'RAW-100');
      assert.equal(unkSupplier.normalizedTitle, 'Some Title');
      assert.ok(unkSupplier.variantImportErrors.includes('unknown-supplier'));
      assert.ok(!unkSupplier.variantImportErrors.includes('unknown-title'));
    });

    it('handles missing productVariant id gracefully', () => {
      const missingId = main({
        productVariant: {
          sku: 'RAW-NO-ID',
          product: { vendor: KCP }
        }
      });
      assert.equal(missingId.supplierCode, 'KCP');
      assert.equal(missingId.variantId, '');
      assert.equal(missingId.newSku, 'KCP-');
      assert.equal(missingId.supplierSku, 'RAW-NO-ID');
    });
  });

  // ==========================================================================
  // 2. Category & Taxonomy Normalization
  // ==========================================================================
  describe('Category & Product Type Normalization', () => {
    const validCategoryInputs = [
      { category: 'Shoes', type: 'Any' },
      { category: 'Sneakers', type: 'Any' },
      { category: 'Apparel & Accessories > Shoes > Sneakers', type: 'Any' },
      { category: 'Apparel & Accessories > Shoes > Athletic Shoes', type: 'Any' },
      { category: 'Apparel & Accessories > Shoes', type: 'Any' },
      { category: 'Clothing', type: "Men's Shoes" },
      { category: 'Clothing', type: "Women's Shoes" },
      { category: 'Clothing', type: "Kid's Shoes" },
      { category: 'Clothing', type: "Toddler's" },
      { category: 'Clothing', type: 'Preschool' },
      { category: 'Clothing', type: 'sneakers' },
      { category: 'Clothing', type: 'Pre-Owned Sneakers' }
    ];

    it('successfully normalizes valid shoe categories and product types to Sneakers', () => {
      for (const tc of validCategoryInputs) {
        const res = main({
          productVariant: { product: { category: { name: tc.category }, productType: tc.type } }
        });
        assert.equal(res.normalizedCategory, NORMALIZED_CATEGORY.SNEAKERS, `Expected Sneakers for category="${tc.category}" type="${tc.type}"`);
        assert.equal(res.normalizedCategoryGid, 'gid://shopify/TaxonomyCategory/aa-8-8');
      }
    });

    it('flags unknown-category error for unexpected or unmapped categories and types', () => {
      const invalidCases = [
        { category: 'Toys & Games', type: 'Action Figures' },
        { category: 'Apparel & Accessories > Clothing', type: 'Apparel' },
        { category: 'Clothing', type: 'Accessories' },
        { category: 'Clothing', type: "Kid's Clothing" }
      ];

      for (const tc of invalidCases) {
        const res = main({
          productVariant: { product: { category: { name: tc.category }, productType: tc.type } }
        });
        assert.equal(res.normalizedCategory, '', `Expected empty category for ${tc.category} / ${tc.type}`);
        assert.equal(res.normalizedCategoryGid, '');
        assert.ok(res.variantImportErrors.includes('unknown-category'));
      }
    });

    it('uses only Type for KCP and ignores Product Category', () => {
      const fromType = main(kcpInput('10.5M / 12W', { productType: 'sneakers', category: { name: 'Uncategorized' } }));
      assert.equal(fromType.normalizedCategory, NORMALIZED_CATEGORY.SNEAKERS);

      const categoryIgnored = main(kcpInput('10.5M / 12W', { productType: '', category: { name: 'Shoes' } }));
      assert.equal(categoryIgnored.normalizedCategory, '');
      assert.ok(categoryIgnored.variantImportErrors.includes('unknown-category'));
    });
  });

  // ==========================================================================
  // 3. Option Matching & Size Text Parsing
  // ==========================================================================
  describe('Option Matching & Size Text Parsing', () => {
    const createInput = (optName, optVal) => ({
      productVariant: {
        sku: 'SKU-1',
        selectedOptions: [{ name: optName, value: optVal }],
        product: { vendor: KCP, productType: 'sneakers', descriptionHtml: kcpBody() }
      }
    });

    const validSizes = [
      { input: '12.5M/14W', m: '12.5', w: '14' },
      { input: '14W/12.5M', m: '12.5', w: '14' },
      { input: '10.5M', m: '10.5', w: '12' },
      { input: '16M', m: '16', w: '17.5' },
      { input: '8.5W', m: '7', w: '8.5' },
      { input: 'US 10M / 11.5W', m: '10', w: '11.5' },
      { input: 'EU44', m: '11', w: '13' },
      { input: 'EU 45', m: '12', w: '14' },
      { input: '10.5M / 12W', m: '10.5', w: '12' },
      { input: '10.5', m: '10.5', w: '12' },
      { input: '11.5W', m: '10', w: '11.5' },
      { input: '12M / 13.5W (Missing Lid)', m: '12', w: '13.5' },
      { input: '13 (Damaged Box)', m: '13', w: '14.5' },
      // Youth 3.5Y+ maps onto adult US sizing (M = Y, W = Y+1.5 or as written)
      { input: '3.5Y', m: '3.5', w: '5' },
      { input: '3.5Y / 5W', m: '3.5', w: '5' },
      { input: '4Y / 5.5W', m: '4', w: '5.5' },
      { input: '6.5Y / 8W', m: '6.5', w: '8' },
      { input: '6.5Y (Replacement Box)', m: '6.5', w: '8' },
      { input: '7Y', m: '7', w: '8.5' }
    ];

    it('successfully parses valid US Men\'s and Women\'s size patterns and EU sizes', () => {
      for (const tc of validSizes) {
        const res = main(createInput('Size', tc.input));
        assert.equal(res.normalizedMSize, tc.m, `Expected MSize ${tc.m} for ${tc.input}`);
        assert.equal(res.normalizedWSize, tc.w, `Expected WSize ${tc.w} for ${tc.input}`);
      }
    });

    it('flags inconsistent-size when M/W pairing does not match US (+1.5) or EU (+2)', () => {
      const inconsistent = ['14M/12.5W', '10.5M / 12.5W', '7Y / 1.5W', '3.5Y / 1.5W'];

      for (const value of inconsistent) {
        const res = main(createInput('Size', value));
        assert.equal(res.normalizedMSize, '', `Expected empty M for ${value}`);
        assert.equal(res.normalizedWSize, '', `Expected empty W for ${value}`);
        assert.ok(res.variantImportErrors.includes('inconsistent-size'), `Expected inconsistent-size for ${value}`);
        assert.ok(!res.variantImportErrors.includes('unknown-size'));
        assert.ok(!res.variantImportErrors.includes('child-size'));
      }

      const euOk = main(createInput('Size', 'EU45'));
      assert.equal(euOk.normalizedMSize, '12');
      assert.equal(euOk.normalizedWSize, '14');
      assert.ok(!euOk.variantImportErrors.includes('inconsistent-size'));
    });

    it('flags child-size for youth/child patterns and unknown-size for other unparseable values', () => {
      const childSizeInputs = ['3Y', '3Y / 4.5W', '2Y / 3.5W', '9C', 'Y / 1.5W', '13.5C', '3', '2.5', '3M', '4.5W', '3M / 4.5W', 'EU36'];

      for (const value of childSizeInputs) {
        const res = main(createInput('Size', value));
        assert.equal(res.normalizedMSize, '');
        assert.equal(res.normalizedWSize, '');
        assert.ok(res.variantImportErrors.includes('child-size'), `Expected child-size for ${value}`);
        assert.ok(!res.variantImportErrors.includes('unknown-size'));
      }

      for (const value of ['3.5', '3.5M', '5W', '3.5Y', 'EU36.5']) {
        const res = main(createInput('Size', value));
        assert.equal(res.normalizedMSize, '3.5', `Expected MSize 3.5 for ${value}`);
        assert.ok(!res.variantImportErrors.includes('child-size'), `Unexpected child-size for ${value}`);
      }

      const unknownSizeInputs = [
        { name: 'Size', value: '10-5-m-11-5-w' },
        { name: 'Size', value: 'copyt:temporary:size' },
        { name: 'Size', value: '10M - Brand New - No Box' },
        { name: 'Title', value: 'Default Title' }
      ];

      for (const tc of unknownSizeInputs) {
        const res = main(createInput(tc.name, tc.value));
        assert.equal(res.normalizedMSize, '');
        assert.equal(res.normalizedWSize, '');
        assert.ok(res.variantImportErrors.includes('unknown-size'), `Expected unknown-size for ${tc.value}`);
        assert.ok(!res.variantImportErrors.includes('child-size'));
      }
    });

    it('still reads condition, box, and title from Body when size fails', () => {
      const failures = [
        { option: '14M/12.5W', error: 'inconsistent-size' },
        { option: '3Y', error: 'child-size' },
        { option: 'Default Title', error: 'unknown-size' }
      ];
      for (const tc of failures) {
        const res = main(kcpInput(tc.option, {
          descriptionHtml: kcpBody({ name: 'Jordan 3 Cool Grey', size: '10M / 11.5W', condition: 'Lightly Worn', box: 'No Box' })
        }));
        assert.ok(res.variantImportErrors.includes(tc.error), `${tc.error} for ${tc.option}`);
        assert.equal(res.normalizedMSize, '');
        assert.equal(res.normalizedCondition, NORMALIZED_CONDITION.WORN);
        assert.equal(res.normalizedConditionNote, 'light wear');
        assert.equal(res.normalizedBox, NORMALIZED_BOX.NO_BOX);
        assert.equal(res.normalizedDescription, 'Worn (light wear), no box');
        assert.equal(res.normalizedTitle, 'Jordan 3 Cool Grey');
        assert.ok(!res.variantImportErrors.includes('size-mismatch'), `size-mismatch for ${tc.option}`);
      }

      const noSizeOption = main({
        productVariant: {
          selectedOptions: [],
          product: { vendor: KCP, productType: 'sneakers', descriptionHtml: kcpBody({ condition: 'New', box: null }) }
        }
      });
      assert.ok(noSizeOption.variantImportErrors.includes('unknown-size'));
      assert.equal(noSizeOption.normalizedCondition, NORMALIZED_CONDITION.BRAND_NEW);
    });

    it('supports "Shoe size" and blank option name as Size option for KCP', () => {
      const shoeSize = main(createInput('Shoe size', '10.5M/12W'));
      assert.equal(shoeSize.normalizedMSize, '10.5');
      assert.equal(shoeSize.normalizedWSize, '12');

      const blankOptName = main(createInput('', '10.5M/12W'));
      assert.equal(blankOptName.normalizedMSize, '10.5');
      assert.equal(blankOptName.normalizedWSize, '12');
    });

    it('flags size-mismatch when Body Size disagrees with the Size option', () => {
      const agree = [
        { option: '10.5M / 12W', body: '10.5M / 12W' },
        { option: '12M/13.5W', body: '12M / 13.5W' },
        { option: '13 (Damaged Box)', body: '13' },
        { option: '6.5Y (No Box)', body: '6.5Y' },
        { option: '11.5W', body: '11.5W' }
      ];
      for (const tc of agree) {
        const res = main(kcpInput(tc.option, { descriptionHtml: kcpBody({ size: tc.body }) }));
        assert.ok(!res.variantImportErrors.includes('size-mismatch'), `Unexpected size-mismatch for ${tc.option} vs ${tc.body}`);
      }

      const mismatch = main(kcpInput('10.5M / 12W', { descriptionHtml: kcpBody({ size: '11M / 12.5W' }) }));
      assert.ok(mismatch.variantImportErrors.includes('size-mismatch'));
      assert.equal(mismatch.normalizedMSize, '10.5');
      assert.equal(mismatch.normalizedWSize, '12');
      assert.equal(mismatch.normalizedCondition, NORMALIZED_CONDITION.WORN);

      const youthVsAdult = main(kcpInput('7Y / 8.5W', { descriptionHtml: kcpBody({ size: '7' }) }));
      assert.ok(!youthVsAdult.variantImportErrors.includes('size-mismatch'));

      const unparseableBody = main(kcpInput('10.5M / 12W', { descriptionHtml: kcpBody({ size: 'see photos' }) }));
      assert.ok(!unparseableBody.variantImportErrors.includes('size-mismatch'));

      const noBodySize = main(kcpInput('10.5M / 12W'));
      assert.ok(!noBodySize.variantImportErrors.includes('size-mismatch'));
    });
  });

  // ==========================================================================
  // 4. Condition & Box Condition (Body)
  // ==========================================================================
  describe('Condition & Box Mapping', () => {
    const withBody = (bodyOpts, extras = {}) =>
      main(kcpInput('10.5M / 12W', { descriptionHtml: kcpBody(bodyOpts), ...extras }));

    it('maps each KCP condition value to condition + note', () => {
      const cases = [
        { input: 'New', cond: NORMALIZED_CONDITION.BRAND_NEW, note: '' },
        { input: 'Pre-Owned', cond: NORMALIZED_CONDITION.WORN, note: '' },
        { input: 'Tried On', cond: NORMALIZED_CONDITION.WORN, note: 'tried on' },
        { input: 'VNDS', cond: NORMALIZED_CONDITION.WORN, note: 'VNDS' },
        { input: 'Lightly Worn', cond: NORMALIZED_CONDITION.WORN, note: 'light wear' },
        { input: 'Moderately Worn', cond: NORMALIZED_CONDITION.WORN, note: 'moderate wear' },
        { input: 'Heavily Worn', cond: NORMALIZED_CONDITION.WORN, note: 'heavy wear' },
        { input: 'lightly worn', cond: NORMALIZED_CONDITION.WORN, note: 'light wear' }
      ];
      for (const tc of cases) {
        const res = withBody({ condition: tc.input });
        assert.equal(res.normalizedCondition, tc.cond, `condition for ${tc.input}`);
        assert.equal(res.normalizedConditionNote, tc.note, `note for ${tc.input}`);
        assert.ok(!res.variantImportErrors.includes('unknown-condition'));
      }
    });

    it('appends bracketed notes, lowercased, keeping VNDS capitalized', () => {
      const cases = [
        { input: 'VNDS (no soles)', cond: NORMALIZED_CONDITION.WORN, note: 'VNDS, no soles' },
        { input: 'Moderately Worn (yellowing on the soles)', cond: NORMALIZED_CONDITION.WORN, note: 'moderate wear, yellowing on the soles' },
        { input: 'Lightly Worn (Nike ID in a beautiful colorway)', cond: NORMALIZED_CONDITION.WORN, note: 'light wear, nike id in a beautiful colorway' },
        { input: 'Pre-Owned (No Insoles)', cond: NORMALIZED_CONDITION.WORN, note: 'no insoles' },
        { input: 'New (Moma socks included)', cond: NORMALIZED_CONDITION.BRAND_NEW, note: 'moma socks included' }
      ];
      for (const tc of cases) {
        const res = withBody({ condition: tc.input });
        assert.equal(res.normalizedCondition, tc.cond, `condition for ${tc.input}`);
        assert.equal(res.normalizedConditionNote, tc.note, `note for ${tc.input}`);
      }
    });

    it('flags unknown-condition for missing, empty, or unlisted Body condition', () => {
      const cases = [
        { condition: null },
        { condition: '' },
        { condition: 'Refurbished' },
        { condition: 'Refurbished (new laces)' },
        { condition: 'Brand New' }
      ];
      for (const opts of cases) {
        const res = withBody(opts);
        assert.equal(res.normalizedCondition, '', `condition for ${JSON.stringify(opts)}`);
        assert.equal(res.normalizedConditionNote, '', `note for ${JSON.stringify(opts)}`);
        assert.ok(res.variantImportErrors.includes('unknown-condition'), `unknown-condition for ${JSON.stringify(opts)}`);
      }
    });

    it('does not read the next line when the Condition value is empty', () => {
      const res = withBody({ condition: '', box: 'Original Box' });
      assert.equal(res.normalizedCondition, '');
      assert.equal(res.normalizedBox, NORMALIZED_BOX.WITH_BOX);
      assert.ok(res.variantImportErrors.includes('unknown-condition'));
    });

    it('ignores Type, tags, metafield, and Title for condition', () => {
      const newTypedPreOwned = withBody({ condition: 'New', box: null }, {
        productType: 'Pre-Owned Sneakers',
        title: 'Nike Air Max 90 Recraft Rose 10 (Pre-Owned)',
        tags: 'pre-owned, lightly_worn',
        conditionMetafield: 'Pre-Owned'
      });
      assert.equal(newTypedPreOwned.normalizedCondition, NORMALIZED_CONDITION.BRAND_NEW);

      const noBodyCondition = withBody({ condition: null }, { tags: 'lightly_worn', conditionMetafield: 'Pre-Owned' });
      assert.equal(noBodyCondition.normalizedCondition, '');
      assert.ok(noBodyCondition.variantImportErrors.includes('unknown-condition'));
    });

    it('maps KCP box values', () => {
      const cases = [
        { input: 'Good Box', box: NORMALIZED_BOX.WITH_BOX },
        { input: 'Original Box', box: NORMALIZED_BOX.WITH_BOX },
        { input: 'Damaged Box', box: NORMALIZED_BOX.DAMAGED_BOX },
        { input: 'Replacement', box: NORMALIZED_BOX.REPLACEMENT_BOX },
        { input: 'Replacement Box', box: NORMALIZED_BOX.REPLACEMENT_BOX },
        { input: 'No Box', box: NORMALIZED_BOX.NO_BOX },
        { input: 'Missing Lid', box: NORMALIZED_BOX.WITH_BOX_MISSING_LID },
        { input: 'original box', box: NORMALIZED_BOX.WITH_BOX }
      ];
      for (const tc of cases) {
        const res = withBody({ box: tc.input });
        assert.equal(res.normalizedBox, tc.box, `box for ${tc.input}`);
        assert.ok(!res.variantImportErrors.includes('unknown-box'));
      }
    });

    it('defaults missing or empty Box Condition to With Box for Brand New only', () => {
      const cases = [
        { condition: 'New', box: null, expected: NORMALIZED_BOX.WITH_BOX },
        { condition: 'New', box: '', expected: NORMALIZED_BOX.WITH_BOX },
        { condition: 'New (Moma socks included)', box: null, expected: NORMALIZED_BOX.WITH_BOX },
        { condition: 'Lightly Worn', box: null, expected: '' },
        { condition: 'Pre-Owned', box: '', expected: '' },
        { condition: null, box: null, expected: '' }
      ];
      for (const tc of cases) {
        const res = withBody({ condition: tc.condition, box: tc.box });
        assert.equal(res.normalizedBox, tc.expected, `box for ${JSON.stringify(tc)}`);
        assert.ok(!res.variantImportErrors.includes('unknown-box'), `unknown-box for ${JSON.stringify(tc)}`);
      }

      const newExplicitNoBox = withBody({ condition: 'New', box: 'No Box' });
      assert.equal(newExplicitNoBox.normalizedBox, NORMALIZED_BOX.NO_BOX);
    });

    it('flags unknown-box for unlisted Box Condition values', () => {
      const res = withBody({ box: 'Custom Acrylic Case' });
      assert.equal(res.normalizedBox, '');
      assert.ok(res.variantImportErrors.includes('unknown-box'));

      const newUnknown = withBody({ condition: 'New', box: 'Custom Acrylic Case' });
      assert.equal(newUnknown.normalizedBox, '');
      assert.ok(newUnknown.variantImportErrors.includes('unknown-box'));
    });

    it('ignores box notes on the Size option and box tags', () => {
      const res = main(kcpInput('9 (No Box)', {
        descriptionHtml: kcpBody({ size: '9', box: 'Damaged Box' }),
        tags: 'special-no_box'
      }));
      assert.equal(res.normalizedBox, NORMALIZED_BOX.DAMAGED_BOX);
    });

    it('reads Body from plain text with newlines and from wrapped HTML', () => {
      const plain = main(kcpInput('10.5M / 12W', {
        descriptionHtml: 'Nike Dunk Low\nSKU: X\nSize: 10.5M / 12W\nCondition: Moderately Worn\nBox Condition: No Box'
      }));
      assert.equal(plain.normalizedCondition, NORMALIZED_CONDITION.WORN);
      assert.equal(plain.normalizedBox, NORMALIZED_BOX.NO_BOX);
      assert.equal(plain.normalizedTitle, 'Nike Dunk Low (Size 10.5)');

      const wrapped = main(kcpInput('10.5M / 12W', {
        descriptionHtml: '<p>Nike Dunk Low</p><p><strong>Size:</strong> 10.5M / 12W</p><p><strong>Condition:</strong> Tried On</p><p><strong>Box Condition:</strong> Replacement Box</p>'
      }));
      assert.equal(wrapped.normalizedConditionNote, 'tried on');
      assert.equal(wrapped.normalizedBox, NORMALIZED_BOX.REPLACEMENT_BOX);
      assert.equal(wrapped.normalizedTitle, 'Nike Dunk Low (Size 10.5)');
    });

    it('reads supplier SKU, title, and Body from saved metafields over overwritten fields', () => {
      const originalTitle = "Jordan 1 Retro Low OG SP Travis Scott Canary (Women's) 8.5W (Pre-Owned)";
      const originalBody = kcpBody({ name: "Jordan 1 Retro Low OG SP Travis Scott Canary (Women's) 8.5W", size: '8.5W', condition: 'Lightly Worn' });
      const input = kcpInput('8.5W', {
        title: 'Jordan 1 Retro Low OG SP Travis Scott Canary (Size 7)',
        descriptionHtml: 'Worn (light wear), with box',
        supplierTitle: { value: originalTitle },
        supplierDescription: { value: originalBody }
      });
      input.productVariant.sku = 'KCP-1';
      input.productVariant.supplierSku = { value: 'DZ4137-700' };

      const res = main(input);
      assert.equal(res.supplierSku, 'DZ4137-700');
      assert.equal(res.supplierTitle, originalTitle);
      assert.equal(res.supplierDescription, originalBody);
      assert.equal(res.normalizedTitle, 'Jordan 1 Retro Low OG SP Travis Scott Canary (Size 7)');
      assert.equal(res.normalizedConditionNote, 'light wear');
      assert.equal(res.variantImportErrors, '');
    });

    it('falls back to sku, title, and descriptionHtml when metafields are unset or blank', () => {
      for (const unset of [undefined, null, { value: null }, { value: '' }, { value: '  ' }]) {
        const input = kcpInput('10.5M / 12W', {
          supplierTitle: unset,
          supplierDescription: unset
        });
        input.productVariant.supplierSku = unset;
        const res = main(input);
        assert.equal(res.supplierSku, 'SKU-1', `sku for ${JSON.stringify(unset)}`);
        assert.equal(res.supplierTitle, input.productVariant.product.title, `title for ${JSON.stringify(unset)}`);
        assert.equal(res.supplierDescription, input.productVariant.product.descriptionHtml);
        assert.equal(res.normalizedConditionNote, 'light wear');
      }
    });

    it('keeps variant errors separate and accumulates product errors from custom.import_errors', () => {
      const withSaved = (saved, sizeValue) =>
        main(kcpInput(sizeValue, { importErrors: saved === undefined ? undefined : { value: saved } }));

      const clean = withSaved(undefined, '10.5M / 12W');
      assert.equal(clean.variantImportErrors, '');
      assert.equal(clean.hasVariantImportErrors, false);
      assert.equal(clean.productImportErrors, '');
      assert.equal(clean.hasProductImportErrors, false);

      const first = withSaved(undefined, '3Y');
      assert.equal(first.variantImportErrors, 'child-size');
      assert.equal(first.productImportErrors, 'child-size');

      const keepsSaved = withSaved('child-size', '10.5M / 12W');
      assert.equal(keepsSaved.variantImportErrors, '');
      assert.equal(keepsSaved.hasVariantImportErrors, false);
      assert.equal(keepsSaved.productImportErrors, 'child-size');
      assert.equal(keepsSaved.hasProductImportErrors, true);

      const noDuplicate = withSaved('child-size', '9C');
      assert.equal(noDuplicate.variantImportErrors, 'child-size');
      assert.equal(noDuplicate.productImportErrors, 'child-size');

      const appends = withSaved('child-size', '14M/12.5W');
      assert.equal(appends.variantImportErrors, 'inconsistent-size');
      assert.equal(appends.productImportErrors, 'child-size,inconsistent-size');

      const tidies = withSaved(' child-size , ,unknown-size ', 'Default Title');
      assert.equal(tidies.productImportErrors, 'child-size,unknown-size');

      const jsonList = withSaved('["child-size","size-mismatch"]', '14M/12.5W');
      assert.equal(jsonList.productImportErrors, 'child-size,size-mismatch,inconsistent-size');
    });

    it('reads only descriptionHtml, not description', () => {
      const result = main(kcpInput('10.5M / 12W', {
        descriptionHtml: undefined,
        description: kcpBody({ condition: 'VNDS' })
      }));
      assert.equal(result.supplierDescription, '');
      assert.equal(result.normalizedCondition, '');
      assert.ok(result.variantImportErrors.includes('unknown-condition'));
      assert.ok(result.variantImportErrors.includes('unknown-title'));
    });
  });

  // ==========================================================================
  // 5. Description
  // ==========================================================================
  describe('Description', () => {
    const describeWith = (bodyOpts) =>
      main(kcpInput('10.5M / 12W', { descriptionHtml: kcpBody(bodyOpts) })).normalizedDescription;

    it('builds "Condition (note), box" with lowercase box', () => {
      assert.equal(describeWith({ condition: 'Lightly Worn', box: 'Original Box' }), 'Worn (light wear), with box');
      assert.equal(describeWith({ condition: 'VNDS (no soles)', box: 'No Box' }), 'Worn (VNDS, no soles), no box');
      assert.equal(describeWith({ condition: 'Moderately Worn', box: 'Missing Lid' }), 'Worn (moderate wear), with box - missing lid');
      assert.equal(describeWith({ condition: 'New', box: null }), 'Brand New, with box');
      assert.equal(describeWith({ condition: 'New', box: 'Original Box' }), 'Brand New, with box');
      assert.equal(describeWith({ condition: 'Pre-Owned', box: null }), 'Worn');
      assert.equal(describeWith({ condition: 'Lightly Worn', box: null }), 'Worn (light wear)');
      assert.equal(describeWith({ condition: '', box: 'No Box' }), 'no box');
      assert.equal(describeWith({ condition: null, box: null }), '');
    });

    it('keeps normalizedBox capitalized', () => {
      const res = main(kcpInput('10.5M / 12W', { descriptionHtml: kcpBody({ box: 'No Box' }) }));
      assert.equal(res.normalizedBox, 'No Box');
    });
  });

  // ==========================================================================
  // 6. Title & Defensive Fallbacks
  // ==========================================================================
  describe('Title Normalization & General Robustness', () => {
    it('takes normalizedTitle from the Body name line with casing as written', () => {
      const res = main(kcpInput('10.5M / 12W', {
        title: "Nike Air Force 1 Low '07 Off-White MoMA 10.5 (Pre-Owned)",
        descriptionHtml: kcpBody({ name: "Nike Air Force 1 Low '07 Off-White MoMA", size: '10.5M / 12W' })
      }));
      assert.equal(res.normalizedTitle, "Nike Air Force 1 Low '07 Off-White MoMA (Size 10.5)");
      assert.ok(!res.variantImportErrors.includes('title-mismatch'));

      const lowerBrand = main(kcpInput('10.5M / 12W', {
        title: 'adidas Yeezy Boost 350 V2 Black Red 10.5 (Pre-Owned)',
        descriptionHtml: kcpBody({ name: 'adidas Yeezy Boost 350 V2 Black Red', size: '10.5M / 12W' })
      }));
      assert.equal(lowerBrand.normalizedTitle, 'adidas Yeezy Boost 350 V2 Black Red (Size 10.5)');
    });

    it('appends the men\'s size to normalizedTitle', () => {
      const cases = [
        { option: '10M / 11.5W', title: 'Jordan 3 Cool Grey (Size 10)' },
        { option: '11.5W', title: 'Jordan 3 Cool Grey (Size 10)' },
        { option: '6.5Y / 8W', title: 'Jordan 3 Cool Grey (Size 6.5)' },
        { option: '13 (Damaged Box)', title: 'Jordan 3 Cool Grey (Size 13)' },
        { option: 'EU44', title: 'Jordan 3 Cool Grey (Size 11)' }
      ];
      for (const tc of cases) {
        const res = main(kcpInput(tc.option, {
          title: 'Jordan 3 Cool Grey',
          descriptionHtml: kcpBody({ name: 'Jordan 3 Cool Grey', size: tc.option })
        }));
        assert.equal(res.normalizedTitle, tc.title, `title for ${tc.option}`);
      }

      const womens = main(kcpInput('11.5W', {
        title: "Jordan 4 Retro Seafoam (Women's) 11.5W (Pre-Owned)",
        descriptionHtml: kcpBody({ name: "Jordan 4 Retro Seafoam (Women's)", size: '11.5W' })
      }));
      assert.equal(womens.normalizedTitle, 'Jordan 4 Retro Seafoam (Size 10)');
      assert.ok(!womens.variantImportErrors.includes('title-mismatch'));

      const noSize = main(kcpInput('Default Title', {
        title: 'Jordan 3 Cool Grey',
        descriptionHtml: kcpBody({ name: 'Jordan 3 Cool Grey' })
      }));
      assert.equal(noSize.normalizedTitle, 'Jordan 3 Cool Grey');
      assert.ok(noSize.variantImportErrors.includes('unknown-size'));
    });

    it("removes women's qualifiers from normalizedTitle and keeps other brackets", () => {
      const cases = [
        { name: "Jordan 1 Retro High OG Seafoam (Women's)", title: 'Jordan 1 Retro High OG Seafoam (Size 10.5)' },
        { name: 'Jordan 1 Retro High OG Seafoam (Women’s)', title: 'Jordan 1 Retro High OG Seafoam (Size 10.5)' },
        { name: 'Nike Dunk Low (Womens)', title: 'Nike Dunk Low (Size 10.5)' },
        { name: 'Nike Dunk Low (Women)', title: 'Nike Dunk Low (Size 10.5)' },
        { name: 'Nike Dunk Low (WMNS)', title: 'Nike Dunk Low (Size 10.5)' },
        { name: 'Nike Dunk Low (W)', title: 'Nike Dunk Low (Size 10.5)' },
        { name: "Nike Dunk Low (Women's) Panda", title: 'Nike Dunk Low Panda (Size 10.5)' },
        { name: "Nike Dunk Low (Men's)", title: "Nike Dunk Low (Men's) (Size 10.5)" },
        { name: 'Jordan 6 Retro Wheat (GS)', title: 'Jordan 6 Retro Wheat (GS) (Size 10.5)' },
        { name: 'Jordan 6 Retro Wheat (PS)', title: 'Jordan 6 Retro Wheat (PS) (Size 10.5)' },
        { name: 'Jordan 6 Retro Wheat (TD)', title: 'Jordan 6 Retro Wheat (TD) (Size 10.5)' },
        { name: 'Jordan 6 Retro Wheat (Kids)', title: 'Jordan 6 Retro Wheat (Kids) (Size 10.5)' },
        { name: "Nike Air Force 1 Low '07 Off-White MoMA (with Socks)", title: "Nike Air Force 1 Low '07 Off-White MoMA (with Socks) (Size 10.5)" },
        { name: 'Nike Air Huarache Stussy Dark Olive (2021)', title: 'Nike Air Huarache Stussy Dark Olive (2021) (Size 10.5)' },
        { name: 'Nike Dunk Low (Wolf Grey)', title: 'Nike Dunk Low (Wolf Grey) (Size 10.5)' }
      ];
      for (const tc of cases) {
        const res = main(kcpInput('10.5M / 12W', { title: tc.name, descriptionHtml: kcpBody({ name: tc.name, size: '10.5M / 12W' }) }));
        assert.equal(res.normalizedTitle, tc.title, `title for ${tc.name}`);
        assert.ok(!res.variantImportErrors.includes('title-mismatch'), `title-mismatch for ${tc.name}`);
      }
    });

    it('removes a trailing size from the Body name and keeps model numbers', () => {
      const canary = main(kcpInput('8.5W', {
        title: "Jordan 1 Retro Low OG SP Travis Scott Canary (Women's) 8.5W (Pre-Owned)",
        descriptionHtml: kcpBody({ name: "Jordan 1 Retro Low OG SP Travis Scott Canary (Women's) 8.5W", size: '8.5W' })
      }));
      assert.equal(canary.normalizedTitle, 'Jordan 1 Retro Low OG SP Travis Scott Canary (Size 7)');
      assert.ok(!canary.variantImportErrors.includes('title-mismatch'));

      const cases = [
        { name: 'Jordan 1 Retro Low OG SP Travis Scott Mocha Size 10', title: 'Jordan 1 Retro Low OG SP Travis Scott Mocha (Size 10.5)' },
        { name: 'adidas Yeezy 500 Bone White (2019) 6.5M/8W', title: 'adidas Yeezy 500 Bone White (2019) (Size 10.5)' },
        { name: 'Jordan 6 Retro Wheat (GS) 6.5Y', title: 'Jordan 6 Retro Wheat (GS) (Size 10.5)' },
        { name: 'Nike Dunk Low 10.5M', title: 'Nike Dunk Low (Size 10.5)' },
        { name: 'adidas Yeezy Boost 350 V2 Zyon', title: 'adidas Yeezy Boost 350 V2 Zyon (Size 10.5)' },
        { name: 'adidas Yeezy 500', title: 'adidas Yeezy 500 (Size 10.5)' },
        { name: 'Nike Kobe 6', title: 'Nike Kobe 6 (Size 10.5)' },
        { name: 'Nike Air Force 1 Low 3M', title: 'Nike Air Force 1 Low 3M (Size 10.5)' }
      ];
      for (const tc of cases) {
        const res = main(kcpInput('10.5M / 12W', { title: tc.name, descriptionHtml: kcpBody({ name: tc.name, size: '10.5M / 12W' }) }));
        assert.equal(res.normalizedTitle, tc.title, `title for ${tc.name}`);
      }
    });

    it('leaves the size out of normalizedTitle for size runs (no Body Size line)', () => {
      for (const size of [null, '']) {
        const res = main(kcpInput('4Y / 5.5W', {
          title: 'Jordan 12 Retro Field Purple',
          descriptionHtml: kcpBody({ name: 'Jordan 12 Retro Field Purple', size, condition: 'New', box: null })
        }));
        assert.equal(res.normalizedTitle, 'Jordan 12 Retro Field Purple', `title for size=${JSON.stringify(size)}`);
        assert.equal(res.normalizedMSize, '4');
        assert.equal(res.normalizedWSize, '5.5');
        assert.equal(res.variantImportErrors, '');
      }
    });

    it('accepts Title suffix variants without flagging title-mismatch', () => {
      const name = "Jordan 1 Retro Low OG SP Travis Scott Olive (Women's)";
      const titles = [
        name,
        `${name} (Pre-Owned)`,
        `${name} 11.5W (Pre-Owned)`,
        `${name} Size 11.5W (Pre-Owned)`,
        `${name} 6.5M/8W (Pre-Owned)`,
        `${name} 6.5Y (Pre-Owned)`,
        `${name} 10.5 (Pre-Owned)`,
        name.toUpperCase(),
        `${name}  `
      ];
      for (const title of titles) {
        const res = main(kcpInput('10.5M / 12W', { title, descriptionHtml: kcpBody({ name }) }));
        assert.ok(!res.variantImportErrors.includes('title-mismatch'), `Unexpected title-mismatch for "${title}"`);
      }

      const modelNumber = main(kcpInput('10.5M / 12W', {
        title: 'Jordan 1 Retro High Shadow 2.0',
        descriptionHtml: kcpBody({ name: 'Jordan 1 Retro High Shadow 2.0' })
      }));
      assert.ok(!modelNumber.variantImportErrors.includes('title-mismatch'));
    });

    it('flags title-mismatch when Title and Body name differ', () => {
      const socks = main(kcpInput('10.5M / 12W', {
        title: "Nike Air Force 1 Low '07 Off-White MoMA (without Socks) 10.5 (Pre-Owned)",
        descriptionHtml: kcpBody({ name: "Nike Air Force 1 Low '07 Off-White MoMA (with Socks)", size: '10.5M / 12W' })
      }));
      assert.ok(socks.variantImportErrors.includes('title-mismatch'));
      assert.equal(socks.normalizedTitle, "Nike Air Force 1 Low '07 Off-White MoMA (with Socks) (Size 10.5)");

      const colorway = main(kcpInput('11M / 12.5W', {
        title: 'Nike Paul Rodriguez 2 Zoom Air Grey Haze/Black 11 (Pre-Owned)',
        descriptionHtml: kcpBody({ name: 'Nike Paul Rodriguez 2 Zoom Air Black Gold' })
      }));
      assert.ok(colorway.variantImportErrors.includes('title-mismatch'));
    });

    it('flags unknown-title when Body has no name line', () => {
      const draft = main(kcpInput('10.5M / 12W', {
        title: 'Pre-Owned Draft dcbe20d7-7af3-402d-b7b0-aadabb71aba7',
        descriptionHtml: 'SKU: DRAFT-879E47B9<br><br>This is a pre-owned item. All sales are final.'
      }));
      assert.equal(draft.normalizedTitle, '');
      assert.ok(draft.variantImportErrors.includes('unknown-title'));
      assert.ok(!draft.variantImportErrors.includes('title-mismatch'));

      const legacy = main(kcpInput('9.5', {
        title: 'Jordan 4 Retro Thunder (2023)',
        descriptionHtml: 'Release Date: May 13, 2023<br>SKU: DH6927-017-9.5-PO-9<br><br>This is a pre-owned item.'
      }));
      assert.equal(legacy.normalizedTitle, '');
      assert.ok(legacy.variantImportErrors.includes('unknown-title'));

      const emptyBody = main(kcpInput('10.5M / 12W', { descriptionHtml: '' }));
      assert.ok(emptyBody.variantImportErrors.includes('unknown-title'));
      assert.ok(emptyBody.variantImportErrors.includes('unknown-condition'));
    });

    it('safely handles empty/malformed inputs without throwing exceptions', () => {
      assert.doesNotThrow(() => {
        const res = main({});
        assert.equal(res.supplierCode, 'UNK');
        assert.equal(res.hasVariantImportErrors, true);
        assert.ok(res.variantImportErrors.includes('unknown-supplier'));
      });

      assert.doesNotThrow(() => main(null));
      assert.doesNotThrow(() => main(undefined));

      assert.doesNotThrow(() => {
        const res = main({
          productVariant: {
            selectedOptions: [null, { name: 'Size', value: 10.5 }],
            product: { vendor: KCP, productType: 'sneakers' }
          }
        });
        assert.equal(res.normalizedMSize, '10.5');
        assert.equal(res.normalizedWSize, '12');
        assert.equal(res.normalizedCategory, NORMALIZED_CATEGORY.SNEAKERS);
      });

      assert.doesNotThrow(() => {
        const res = main({
          productVariant: {
            selectedOptions: 'not-an-array',
            product: { vendor: KCP, productType: 'sneakers' }
          }
        });
        assert.ok(res.variantImportErrors.includes('unknown-size'));
      });
    });

    it('does not treat a blank-named non-size option as Size when a named Size exists', () => {
      const res = main({
        productVariant: {
          selectedOptions: [
            { name: '', value: 'Red' },
            { name: 'Size', value: '10M' }
          ],
          product: { vendor: KCP, productType: 'sneakers' }
        }
      });
      assert.equal(res.normalizedMSize, '10');
      assert.equal(res.normalizedWSize, '11.5');
    });

    it('still accepts blank-named size values from CSV continuation rows', () => {
      const res = main({
        productVariant: {
          selectedOptions: [{ name: '', value: '10.5M / 12W' }],
          product: { vendor: KCP, productType: 'sneakers' }
        }
      });
      assert.equal(res.normalizedMSize, '10.5');
      assert.equal(res.normalizedWSize, '12');
    });
  });
});
