import unittest

from services.url_search_service import get_search_url


class UrlSearchServiceTest(unittest.TestCase):

    def test_get_search_url_amazon(self):

        url = get_search_url(
            "Amazon",
            "Elden Ring",
            "PS5"
        )

        print("\nAMAZON URL:")
        print(url)

        self.assertIn("amazon.es/s?k=", url)
        self.assertIn("Elden+Ring", url)
        self.assertIn("PS5", url)

    def test_get_search_url_pccomponentes(self):

        url = get_search_url(
            "pccomponentes",
            "Cyberpunk 2077",
            None
        )

        print("\nPCCOMPONENTES URL:")
        print(url)

        self.assertTrue(
            url.startswith(
                "https://www.pccomponentes.com/buscar?q="
            )
        )

        self.assertIn(
            "Cyberpunk+2077",
            url
        )

    def test_get_search_url_unsupported_shop(self):

        url = get_search_url(
            "UnknownShop",
            "Test Product",
            "PC"
        )

        print("\nUNSUPPORTED SHOP URL:")
        print(url)

        self.assertEqual(url, "")

    def test_get_search_url_uses_product_name_only_when_platform_empty(self):

        url = get_search_url(
            "MediaMarkt",
            "Halo Infinite",
            ""
        )

        print("\nMEDIAMARKT URL:")
        print(url)

        self.assertIn(
            "Halo+Infinite",
            url
        )

        self.assertNotIn("%20", url)


if __name__ == "__main__":
    unittest.main(verbosity=2)