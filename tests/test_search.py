import unittest
from helpers import tmp_db
from hesabat.db.connection import connect
from hesabat.db.migrations import init_db
from hesabat.logic import products
from hesabat.logic.search import first_match, matches, normalize


class SearchTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("أَحْمَد"), normalize("احمد"))
        self.assertEqual(normalize("إبراهيم آل"), "ابراهيم ال")
        self.assertEqual(normalize("مكرونة"), normalize("مكرونه"))
        self.assertEqual(normalize("على"), normalize("علي"))
        self.assertEqual(normalize("سُكّر"), "سكر")
        self.assertEqual(normalize("كـــتاب"), "كتاب")                   # تطويل
        self.assertEqual(normalize("١٢٣ ۴۵"), "123 45")                  # أرقام عربية وفارسية
        self.assertEqual(normalize("Sugar"), "sugar")
        self.assertEqual(normalize(None), "")

    def test_matches(self):
        self.assertTrue(matches("", "أي حاجة", 1))
        self.assertTrue(matches("   ", "أي حاجة", 1))
        self.assertTrue(matches("سكر", "سكر أبيض ناعم 1 كجم", 7))
        self.assertTrue(matches("ابيض سكر", "سكر أبيض ناعم", 7))         # الترتيب مش مهم
        self.assertTrue(matches("احمد", "أحمد", 1))
        self.assertFalse(matches("سكر بني", "سكر أبيض", 1))               # كل الكلمات لازم تتوافر
        self.assertTrue(matches("12", "شاي", 12))                          # برقم الصنف
        self.assertTrue(matches("١٢", "شاي", 12))                          # برقم عربي
        self.assertFalse(matches("12", "شاي", 3))
        self.assertTrue(matches("1", "سكر 1 كجم", 99))                    # الرقم جوه الاسم برضه بيطابق
        self.assertFalse(matches("سكر", "شاي", 1))
        self.assertTrue(matches("شاي 12", "شاي أخضر", 12))               # اسم + رقم مع بعض


class FirstMatchTests(unittest.TestCase):
    ITEMS = [("سكر أبيض", 1), ("سكر بني", 2), ("شاي أخضر", 3)]

    def test_first_match(self):
        self.assertEqual(first_match("سكر", self.ITEMS), 0)              # أول مطابق
        self.assertEqual(first_match("بني", self.ITEMS), 1)
        self.assertEqual(first_match("شاى", self.ITEMS), 2)              # ى/ي
        self.assertEqual(first_match("3", self.ITEMS), 2)                # بالرقم
        self.assertIsNone(first_match("مش موجود", self.ITEMS))
        self.assertIsNone(first_match("", self.ITEMS))                   # بحث فاضي مبيختارش حاجة
        self.assertIsNone(first_match("   ", self.ITEMS))
        self.assertEqual(first_match("2", [("سكر", None), ("بني 2", None)]), 1)   # من غير أرقام بيطابق الاسم بس


class ProductSearchTests(unittest.TestCase):
    def setUp(self):
        path = tmp_db(); self.c = connect(path); init_db(self.c, path)
        self.ids = {n: products.create(self.c, n, "1", "2") for n in ("سكر أبيض", "سكر بني", "شاي أخضر", "أرز", "مكرونة")}

    def names(self, q):
        return [r["name"] for r in products.list_products(self.c, q)]

    def test_search(self):
        self.assertEqual(len(self.names("")), 5)
        self.assertEqual(self.names("سكر"), ["سكر أبيض", "سكر بني"])
        self.assertEqual(self.names("سكر بني"), ["سكر بني"])
        self.assertEqual(self.names("ارز"), ["أرز"])                      # أ/ا
        self.assertEqual(self.names("مكرونه"), ["مكرونة"])                # ة/ه
        self.assertEqual(self.names("غير موجود"), [])
        self.assertEqual(self.names(str(self.ids["شاي أخضر"])), ["شاي أخضر"])   # برقم الصنف
        self.assertEqual(products.count(self.c), 5)

    def test_numbers_are_stable_and_unique(self):
        ids = [r["id"] for r in products.list_products(self.c)]
        self.assertEqual(len(set(ids)), 5)
        products.deactivate(self.c, self.ids["أرز"])
        new_id = products.create(self.c, "ملح", "1", "2")
        self.assertNotIn(new_id, (self.ids["أرز"],))                        # الرقم القديم مبيتعادش استخدامه
        self.assertGreater(new_id, max(self.ids.values()))
        self.assertEqual(products.count(self.c), 5)
        self.assertEqual(self.names("ارز"), [])                              # الموقوف مبيظهرش في البحث


if __name__ == "__main__":
    unittest.main(verbosity=2)
