import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import main from './importer.js';

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
          product: { vendor: 'Kicks Collective PA' }
        }
      });
      assert.equal(raw.prefix, 'KCP');
      assert.equal(raw.variantId, '4521987654321');
      assert.equal(raw.originalSku, 'RAW-SKU-99');
      assert.equal(raw.newSku, 'KCP-4521987654321');
    });

    it('falls back to UNK prefix and flags error for unconfigured suppliers', () => {
      const unkSupplier = main({
      productVariant: {
          id: 'gid://shopify/ProductVariant/100',
          sku: 'RAW-100',
          product: { vendor: 'Unknown' }
        }
    });
      assert.equal(unkSupplier.prefix, 'UNK');
      assert.equal(unkSupplier.variantId, '100');
      assert.equal(unkSupplier.newSku, 'UNK-100');
      assert.equal(unkSupplier.originalSku, 'RAW-100');
      assert.ok(unkSupplier.importErrors.includes('unknown-supplier'));
    });

    it('handles missing productVariant id gracefully', () => {
      const missingId = main({
        productVariant: {
          sku: 'RAW-NO-ID',
          product: { vendor: 'Kicks Collective PA' }
        }
      });
      assert.equal(missingId.prefix, 'KCP');
      assert.equal(missingId.variantId, '');
      assert.equal(missingId.newSku, 'KCP-');
      assert.equal(missingId.originalSku, 'RAW-NO-ID');
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
      { category: 'Clothing', type: "Preschool" },
      { category: 'Clothing', type: 'sneakers' },
      { category: 'Clothing', type: 'Pre-Owned Sneakers' }
    ];

    it('successfully normalizes valid shoe categories and product types to Sneakers', () => {
      for (const tc of validCategoryInputs) {
        const res = main({
          productVariant: { product: { category: { name: tc.category }, productType: tc.type } }
        });
        assert.equal(res.normalizedCategory, 'Sneakers', `Expected Sneakers for category="${tc.category}" type="${tc.type}"`);
        assert.equal(res.normalizedCategoryGid, 'gid://shopify/TaxonomyCategory/aa-sneakers');
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
      assert.ok(res.importErrors.includes('unknown-category'));
      }
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
        product: { vendor: 'Kicks Collective PA', category: { name: 'Shoes' } }
          }
    });

    const validSizes = [
      { input: '12.5M/14W - Brand New - No Box', m: '12.5', w: '14' },
      { input: '14W/12.5M - Pre-Owned - No Box', m: '12.5', w: '14' },
      { input: '10.5M - Brand New - With Box', m: '10.5', w: '12' },
      { input: '8.5W - Pre-Owned - No Box', m: '7', w: '8.5' },
      { input: 'US 10M / 11.5W - Brand New - No Box', m: '10', w: '11.5' },
      { input: 'EU44 - Brand New', m: '11', w: '13' },
      { input: 'EU 45 - Brand New', m: '12', w: '14' },
      // Size-only options from newer KCP exports
      { input: '10.5M / 12W', m: '10.5', w: '12' },
      { input: '10.5', m: '10.5', w: '12' },
      { input: '11.5W', m: '10', w: '11.5' },
      { input: '12M / 13.5W (Missing Lid)', m: '12', w: '13.5' },
      // Youth 3.5Y+ maps onto adult US sizing (M = Y, W = Y+1.5 or as written)
      { input: '3.5Y', m: '3.5', w: '5' },
      { input: '3.5Y / 5W', m: '3.5', w: '5' },
      { input: '3.5Y - Pre-Owned - No Box', m: '3.5', w: '5' },
      { input: '4Y / 5.5W', m: '4', w: '5.5' },
      { input: '6.5Y / 8W', m: '6.5', w: '8' },
      { input: '7Y', m: '7', w: '8.5' },
      { input: '7Y - Pre-Owned - No Box', m: '7', w: '8.5' }
    ];

    it('successfully parses valid US Men\'s and Women\'s size patterns and EU sizes', () => {
      for (const tc of validSizes) {
        const res = main(createInput('Size', tc.input));
        assert.equal(res.normalizedMSize, tc.m, `Expected MSize ${tc.m} for ${tc.input}`);
        assert.equal(res.normalizedWSize, tc.w, `Expected WSize ${tc.w} for ${tc.input}`);
      }
    });

    it('flags child-size for youth/child patterns and unknown-size for other unparseable values', () => {
      const childSizeInputs = [
        { name: 'Size', value: '3Y - Pre-Owned' },
        { name: 'Size', value: '3Y / 4.5W' },
        { name: 'Size', value: '9C - Brand New' },
        { name: 'Size', value: 'Y / 1.5W' },
        { name: 'Size', value: '13.5C' }
      ];

      for (const tc of childSizeInputs) {
        const res = main(createInput(tc.name, tc.value));
        assert.equal(res.normalizedMSize, '');
        assert.equal(res.normalizedWSize, '');
        assert.equal(res.normalizedCondition, '');
        assert.equal(res.normalizedBox, '');
        assert.ok(res.importErrors.includes('child-size'), `Expected child-size for ${tc.value}`);
        assert.ok(!res.importErrors.includes('unknown-size'));
        assert.ok(!res.importErrors.includes('unknown-condition'));
        assert.ok(!res.importErrors.includes('unknown-box'));
      }

      const unknownSizeInputs = [
        { name: 'Size', value: '10-5-m-11-5-w' },
        { name: 'Size', value: 'copyt:temporary:size' },
        { name: 'Title', value: 'Default Title' }
      ];

      for (const tc of unknownSizeInputs) {
        const res = main(createInput(tc.name, tc.value));
        assert.equal(res.normalizedMSize, '');
        assert.equal(res.normalizedWSize, '');
        assert.equal(res.normalizedCondition, '');
        assert.equal(res.normalizedBox, '');
        assert.ok(res.importErrors.includes('unknown-size'), `Expected unknown-size for ${tc.value}`);
        assert.ok(!res.importErrors.includes('child-size'));
      }
    });

    it('supports "Shoe size" and blank option name as Size option for KCP', () => {
      const shoeSize = main(createInput('Shoe size', '10.5M/12W - Brand New - With Box'));
      assert.equal(shoeSize.normalizedMSize, '10.5');
      assert.equal(shoeSize.normalizedWSize, '12');

      const blankOptName = main(createInput('', '10.5M/12W - Brand New - With Box'));
      assert.equal(blankOptName.normalizedMSize, '10.5');
      assert.equal(blankOptName.normalizedWSize, '12');
    });
  });

  // ==========================================================================
  // 4. Condition & Box Condition Mapping
  // ==========================================================================
  describe('Condition & Box Mapping', () => {
    const createInput = (optVal, productExtras = {}) => ({
      productVariant: {
        sku: 'SKU-1',
        selectedOptions: [{ name: 'Size', value: optVal }],
        product: {
          vendor: 'Kicks Collective PA',
          category: { name: 'Shoes' },
          ...productExtras
        }
      }
    });

    const validMappings = [
      { input: '10M - Brand New - Original Box (Good)', cond: 'Brand New', box: 'With Box' },
      { input: '10M - Pre-Owned - Original Box (Damaged)', cond: 'Worn', box: 'Damaged Box' },
      { input: '10M - Pre-Owned - Replacement Box', cond: 'Worn', box: 'Replacement Box' },
      { input: '10M - Pre-Owned - No Box', cond: 'Worn', box: 'No Box' },

      { input: '9M/10.5W - Brand New - Missing Lid', cond: 'Brand New', box: 'With Box - Missing Lid' },
      { input: '10M - Brand New', cond: 'Brand New', box: '', desc: 'Brand New' } // No box signal → unset
    ];

    it('successfully maps expected condition and box combinations', () => {
      for (const tc of validMappings) {
        const res = main(createInput(tc.input));
        assert.equal(res.normalizedCondition, tc.cond);
        assert.equal(res.normalizedBox, tc.box);
        const expectedDesc = tc.desc || `${tc.cond} (${tc.box})`;
        assert.equal(res.normalizedDescription, expectedDesc);
      }
    });

    it('resolves size-only condition via metafield, Body, tags, type, or title cascade', () => {
      const fromMf = main(createInput('10.5M / 12W', { conditionMetafield: 'Pre-Owned' }));
      assert.equal(fromMf.normalizedCondition, 'Worn');

      const fromBody = main(createInput('10.5M / 12W', {
        description: 'Condition: Moderately Worn\nBox: No Box\nSKU: DC1060-100'
      }));
      assert.equal(fromBody.normalizedCondition, 'Worn');

      const fromBodyTriedOn = main(createInput('10.5M / 12W', {
        description: '<p>Condition: Tried On</p><p>Box: No Box</p>'
      }));
      assert.equal(fromBodyTriedOn.normalizedCondition, 'Worn');

      const fromBodyVnds = main(createInput('10.5M / 12W', {
        description: 'Condition: VNDS'
      }));
      assert.equal(fromBodyVnds.normalizedCondition, 'Worn');

      const fromBodyNotSpecified = main(createInput('10.5M / 12W', {
        description: 'Condition: Not Specified'
      }));
      assert.equal(fromBodyNotSpecified.normalizedCondition, '');
      assert.ok(!fromBodyNotSpecified.importErrors.includes('unknown-condition'));

      const fromTagsBn = main(createInput('10.5M / 12W', { tags: 'Brand New, COPYT, store-owned' }));
      assert.equal(fromTagsBn.normalizedCondition, 'Brand New');

      const fromType = main(createInput('10.5', { productType: 'Pre-Owned Sneakers' }));
      assert.equal(fromType.normalizedCondition, 'Worn');

      const fromTitlePo = main(createInput('11.5W', {
        title: 'Jordan 1 Retro Low OG SP Travis Scott Olive Size 11.5W (Pre-Owned)'
      }));
      assert.equal(fromTitlePo.normalizedCondition, 'Worn');

      const fromTitleBn = main(createInput('10.5M / 12W', {
        title: 'Jordan 1 Retro High OG Brand New Sample'
      }));
      assert.equal(fromTitleBn.normalizedCondition, 'Brand New');

      const fromTitleWorn = main(createInput('10', {
        title: 'Nike Dunk Low Size 10 (Moderately Worn Pre-Owned)'
      }));
      assert.equal(fromTitleWorn.normalizedCondition, 'Worn');

      const fromTitleNew = main(createInput('9.5', {
        title: 'NEW SIZE 9.5 - Nike Dunk Low Retro Premium Philly'
      }));
      assert.equal(fromTitleNew.normalizedCondition, 'Brand New');

      const fromTitleUsed = main(createInput('10', {
        title: 'Jordan 1 Retro High Used Size 10'
      }));
      assert.equal(fromTitleUsed.normalizedCondition, 'Worn');

      const fromMfWorn = main(createInput('10.5M / 12W', { conditionMetafield: 'Worn' }));
      assert.equal(fromMfWorn.normalizedCondition, 'Worn');

      const newBalanceIgnored = main(createInput('10.5M / 12W', {
        title: 'New Balance 990v3 Made In USA Boston Marathon'
      }));
      assert.equal(newBalanceIgnored.normalizedCondition, '');
      assert.ok(!newBalanceIgnored.importErrors.includes('unknown-condition'));
    });

    it('prefers option condition segment over product metafield', () => {
      const res = main(createInput('10M - Brand New', { conditionMetafield: 'Pre-Owned' }));
      assert.equal(res.normalizedCondition, 'Brand New');
    });

    it('prefers metafield condition over Body Condition field', () => {
      const res = main(createInput('10.5M / 12W', {
        conditionMetafield: 'Brand New',
        description: 'Condition: Pre-Owned'
      }));
      assert.equal(res.normalizedCondition, 'Brand New');
    });

    it('leaves condition unset (no error) when there is no condition signal', () => {
      const noSignals = main(createInput('10.5M / 12W'));
      assert.equal(noSignals.normalizedCondition, '');
      assert.equal(noSignals.normalizedBox, '');
      assert.ok(!noSignals.importErrors.includes('unknown-condition'));
      assert.equal(noSignals.normalizedDescription, '');
    });

    it('flags unknown-condition or unknown-box errors when mappings are unexpected', () => {
      const unknownCondition = main(createInput('10M - Refurbished - No Box'));
      assert.equal(unknownCondition.normalizedCondition, '');
      assert.ok(unknownCondition.importErrors.includes('unknown-condition'));

      const unknownBox = main(createInput('10M - Brand New - Custom Acrylic Case'));
      assert.equal(unknownBox.normalizedBox, '');
      assert.ok(unknownBox.importErrors.includes('unknown-box'));
    });

    it('resolves size-only box via paren, tags, or Body Box: field', () => {
      const fromParen = main(createInput('12M / 13.5W (Missing Lid)'));
      assert.equal(fromParen.normalizedBox, 'With Box - Missing Lid');

      const fromTags = main(createInput('10.5M / 12W', { tags: 'no_box' }));
      assert.equal(fromTags.normalizedBox, 'No Box');

      const fromSpecialTag = main(createInput('10.5M / 12W', { tags: 'special-no_box' }));
      assert.equal(fromSpecialTag.normalizedBox, 'No Box');

      const fromBodyStrong = main(createInput('12M / 13.5W', {
        description: '<p><strong>Condition:</strong> Moderately Worn</p>\n<p><strong>Box:</strong> No Box</p>'
      }));
      assert.equal(fromBodyStrong.normalizedBox, 'No Box');

      const fromBodyPlain = main(createInput('12M / 13.5W', {
        description: 'Condition: Moderately Worn\nBox: No Box\nSKU: DC1060-100'
      }));
      assert.equal(fromBodyPlain.normalizedBox, 'No Box');

      const fromBodyReplacement = main(createInput('11.5M / 13W', {
        description: '<p>Box: Replacement Box</p>'
      }));
      assert.equal(fromBodyReplacement.normalizedBox, 'Replacement Box');

      const fromBodyDamaged = main(createInput('10M / 11.5W', {
        description: 'Box: Damaged Box'
      }));
      assert.equal(fromBodyDamaged.normalizedBox, 'Damaged Box');

      // Free-form Body prose without a Box: label is ignored.
      const proseIgnored = main(createInput('10.5M / 12W', {
        description: '<p>These shoes come with no box included.</p>'
      }));
      assert.equal(proseIgnored.normalizedBox, '');
    });

    it('prefers option box segment over Body and tags', () => {
      const res = main(createInput('10M - Brand New - Original Box (Good)', {
        tags: 'no_box',
        description: '<p><strong>Box:</strong> No Box</p>'
      }));
      assert.equal(res.normalizedBox, 'With Box');
    });

  });

  // ==========================================================================
  // 5. Title Normalization & Defensive Fallbacks
  // ==========================================================================
  describe('Title Normalization & General Robustness', () => {
    it('applies supplier title formatting strategy correctly', () => {
      const lower = main({ productVariant: { product: { vendor: 'Kicks Collective PA', title: 'jordan 1 retro high og sp' } } });
      assert.equal(lower.normalizedTitle, 'Jordan 1 Retro High Og Sp');

      const upper = main({ productVariant: { product: { vendor: 'Kicks Collective PA', title: 'Jordan 1 Retro High OG SP' } } });
      assert.equal(upper.normalizedTitle, 'Jordan 1 Retro High OG SP');
    });

    it('safely handles empty/malformed inputs without throwing exceptions', () => {
      assert.doesNotThrow(() => {
        const res = main({});
        assert.equal(res.prefix, 'UNK');
        assert.equal(res.hasImportErrors, true);
        assert.ok(res.importErrors.includes('unknown-supplier'));
      });

      assert.doesNotThrow(() => main(null));
      assert.doesNotThrow(() => main(undefined));

      assert.doesNotThrow(() => {
        const res = main({
          productVariant: {
            selectedOptions: [null, { name: 'Size', value: 10.5 }],
            product: { vendor: 'Kicks Collective PA', category: 'Shoes' }
          }
        });
        assert.equal(res.normalizedMSize, '10.5');
        assert.equal(res.normalizedWSize, '12');
        assert.equal(res.normalizedCategory, 'Sneakers');
      });

      assert.doesNotThrow(() => {
        const res = main({
          productVariant: {
            selectedOptions: 'not-an-array',
            product: { vendor: 'Kicks Collective PA', category: { name: 'Shoes' } }
          }
        });
        assert.ok(res.importErrors.includes('unknown-size'));
      });
    });

    it('does not treat a blank-named non-size option as Size when a named Size exists', () => {
      const res = main({
        productVariant: {
          selectedOptions: [
            { name: '', value: 'Red' },
            { name: 'Size', value: '10M' }
          ],
          product: { vendor: 'Kicks Collective PA', category: { name: 'Shoes' } }
        }
      });
      assert.equal(res.normalizedMSize, '10');
      assert.equal(res.normalizedWSize, '11.5');
    });

    it('still accepts blank-named size values from CSV continuation rows', () => {
      const res = main({
        productVariant: {
          selectedOptions: [{ name: '', value: '10.5M / 12W' }],
          product: { vendor: 'Kicks Collective PA', category: { name: 'Shoes' } }
        }
      });
      assert.equal(res.normalizedMSize, '10.5');
      assert.equal(res.normalizedWSize, '12');
    });
  });
});

