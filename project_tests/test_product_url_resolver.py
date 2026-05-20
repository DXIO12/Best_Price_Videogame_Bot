from services.url_search_service import get_search_url
from services.url_resolvers.amazon_url_resolver import resolve_amazon_product_url
from services.url_resolvers.pccomponentes_url_resolver import resolve_pccomponentes_product_url


#Amazon URL test
# search_url = get_search_url(
#     "Amazon",
#     "Elden Ring",
#     "PS5"
# )

# print("\nSEARCH URL:")
# print(search_url)

# resolved_url = resolve_amazon_product_url(
#     search_url
# )

# print("\nRESOLVED PRODUCT URL:")
# print(resolved_url)

#PCComponentes URL test

search_url = get_search_url(
    "PCComponentes",
    "Cyberpunk 2077",
    "PS5"
)

print("\nSEARCH URL:")
print(search_url)

resolved_url = resolve_pccomponentes_product_url(search_url)

print("\nRESOLVED PRODUCT URL:")
print(resolved_url)