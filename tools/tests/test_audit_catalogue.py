import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit_catalogue import coverage


class CoverageTests(unittest.TestCase):
    def test_barcode_link_and_approval_are_distinct(self):
        products = [
            {"store_code": "coles", "barcode": "00012345"},
            {"store_code": "coles", "gtin_id": 1, "gtin_verified": False},
            {"store_code": "coles", "gtin_id": 2, "gtin_verified": True},
            {"store_code": "coles"},
        ]
        before = [dict(p) for p in products]
        row = coverage(products)["coles"]
        self.assertEqual(row["products"], 4)
        self.assertEqual(row["with_barcode"], 1)
        self.assertEqual(row["linked_gtin"], 2)
        self.assertEqual(row["without_gtin_link"], 2)
        self.assertEqual(row["verified"], 1)
        self.assertEqual(row["not_verified"], 3)
        self.assertEqual(products, before)

    def test_unknown_vendor_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "Unknown retailer"):
            coverage([{"store_code": "unknown"}])

    def test_inconsistent_verified_identity_is_visible(self):
        row = coverage([{"store_code": "aldi", "gtin_verified": True}])["aldi"]
        self.assertEqual(row["verified_without_link"], 1)


if __name__ == "__main__":
    unittest.main()
