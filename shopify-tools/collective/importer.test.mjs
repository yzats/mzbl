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
      { category: 'Clothing', type: "Preschool" }
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
        assert.equal(res.normalizedCategory, 'unknown', `Expected unknown category for ${tc.category} / ${tc.type}`);
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
      { input: '10.5M - Brand New - With Box', m: '10.5', w: '' },
      { input: '8.5W - Pre-Owned - No Box', m: '', w: '8.5' },
      { input: 'US 10M / 11.5W - Brand New - No Box', m: '10', w: '11.5' },
      { input: 'EU44 - Brand New', m: '11', w: '13' },
      { input: 'EU 45 - Brand New', m: '12', w: '14' }
    ];

    it('successfully parses valid US Men\'s and Women\'s size patterns and EU sizes', () => {
      for (const tc of validSizes) {
        const res = main(createInput('Size', tc.input));
        assert.equal(res.normalizedMSize, tc.m, `Expected MSize ${tc.m} for ${tc.input}`);
        assert.equal(res.normalizedWSize, tc.w, `Expected WSize ${tc.w} for ${tc.input}`);
      }
    });

    it('flags unknown-size error for unexpected size formats or unconfigured option names', () => {
      const invalidSizeInputs = [
        { name: 'Size', value: '7Y - Pre-Owned' },               // Youth
        { name: 'Size', value: '9C - Brand New' },               // Child
        { name: 'Size', value: '10-5-m-11-5-w' },                // Hyphenated slug
        { name: 'Size', value: 'copyt:temporary:size' },         // Temporary slug
        { name: 'Title', value: 'Default Title' }                // Unmapped option name
      ];

      for (const tc of invalidSizeInputs) {
        const res = main(createInput(tc.name, tc.value));
        assert.equal(res.normalizedMSize, '');
        assert.equal(res.normalizedWSize, '');
        assert.ok(res.importErrors.includes('unknown-size'), `Expected unknown-size error for option ${tc.name}: ${tc.value}`);
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
    const createInput = (optVal) => ({
      productVariant: {
        sku: 'SKU-1',
        selectedOptions: [{ name: 'Size', value: optVal }],
        product: { vendor: 'Kicks Collective PA', category: { name: 'Shoes' } }
        }
    });

    const validMappings = [
      { input: '10M - Brand New - Original Box (Good)', cond: 'Brand New', box: 'With Box' },
      { input: '10M - Pre-Owned - Original Box (Damaged)', cond: 'Worn', box: 'Damaged Box' },
      { input: '10M - Pre-Owned - Replacement Box', cond: 'Worn', box: 'Replacement Box' },
      { input: '10M - Pre-Owned - No Box', cond: 'Worn', box: 'No Box' },

      { input: '9M/10.5W - Brand New - Missing Lid', cond: 'Brand New', box: 'With Box - Missing Lid' },
      { input: '10M - Brand New', cond: 'Brand New', box: 'With Box' } // Default box fallback
    ];

    it('successfully maps expected condition and box combinations', () => {
      for (const tc of validMappings) {
        const res = main(createInput(tc.input));
        assert.equal(res.normalizedCondition, tc.cond);
        assert.equal(res.normalizedBox, tc.box);
        assert.equal(res.normalizedDescription, `${tc.cond} (${tc.box})`);
      }
    });

    it('flags unknown-condition or unknown-box errors when mappings are unexpected', () => {
      const unknownCondition = main(createInput('10M - Refurbished - No Box'));
      assert.equal(unknownCondition.normalizedCondition, 'unknown');
      assert.ok(unknownCondition.importErrors.includes('unknown-condition'));

      const unknownBox = main(createInput('10M - Brand New - Custom Acrylic Case'));
      assert.equal(unknownBox.normalizedBox, 'unknown');
      assert.ok(unknownBox.importErrors.includes('unknown-box'));
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
  });
});

});

