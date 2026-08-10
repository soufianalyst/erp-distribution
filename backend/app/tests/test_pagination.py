"""The ledger must never be fetched whole.

Measured on the seeded database, `/journal-entries` returned 3,408 rows and 2 MB in
429 ms — after one year, to fill a screen showing fifteen. Every invoice, payment,
return and expense posts another entry, so that cost only ever rises.

These tests hold two things. First the arithmetic: a page is the size it says, the
total counts everything rather than the page, and walking the offsets visits every
row exactly once — an off-by-one there silently hides or duplicates a journal entry,
which in a ledger is the whole ballgame. Second the contract itself, so that an
endpoint cannot quietly go back to returning everything.
"""

from httpx import AsyncClient

from app.tests.conftest import TEST_ACCOUNTANT_PASSWORD, TEST_ADMIN_PASSWORD, login

ENTRIES = "/api/v1/accounting/journal-entries"


async def make_entries(client: AsyncClient, accountant: dict, count: int) -> None:
    """Balanced manual entries — the cheapest way to fill the ledger."""
    for index in range(count):
        response = await client.post(ENTRIES, headers=accountant, json={
            "description": f"قيد اختباري {index}",
            "items": [
                {"account_code": "1010", "debit": "10.00"},
                {"account_code": "3010", "credit": "10.00"},
            ],
        })
        assert response.status_code == 201, response.text


class TestAPageIsAPage:
    async def test_the_response_is_capped_at_the_requested_size(
        self, client: AsyncClient
    ) -> None:
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        await make_entries(client, accountant, 12)

        data = (await client.get(
            ENTRIES, headers=accountant, params={"limit": 5})).json()["data"]

        assert len(data["items"]) == 5
        assert data["limit"] == 5
        assert data["offset"] == 0

    async def test_total_counts_the_whole_ledger_not_the_page(
        self, client: AsyncClient
    ) -> None:
        """Without this a screen cannot say "page 3 of 40", and a user has no way to
        tell a short page from the end of the data."""
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        await make_entries(client, accountant, 12)

        data = (await client.get(
            ENTRIES, headers=accountant, params={"limit": 5})).json()["data"]

        assert data["total"] >= 12
        assert data["total"] > len(data["items"])

    async def test_walking_the_offsets_visits_every_entry_exactly_once(
        self, client: AsyncClient
    ) -> None:
        """The off-by-one test.

        An offset that is out by one either skips a journal entry or shows it twice.
        Both are invisible on screen and both are wrong in a ledger, so the check is
        that the union of the pages equals the whole, with no repeats.
        """
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        await make_entries(client, accountant, 12)

        first = (await client.get(
            ENTRIES, headers=accountant, params={"limit": 5})).json()["data"]
        total = first["total"]

        seen: list[int] = []
        offset = 0
        while offset < total:
            page = (await client.get(ENTRIES, headers=accountant,
                                     params={"limit": 5, "offset": offset})).json()["data"]
            seen.extend(item["id"] for item in page["items"])
            offset += 5

        assert len(seen) == total, "the pages did not add up to the total"
        assert len(set(seen)) == total, "an entry appeared on two pages"

    async def test_a_filtered_total_counts_only_the_matches(
        self, client: AsyncClient
    ) -> None:
        """`total` must respect the filter, or the pager offers pages that are empty."""
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        await make_entries(client, accountant, 6)

        filtered = (await client.get(ENTRIES, headers=accountant, params={
            "reference_type": "customer_payment", "reference_id": 999999,
        })).json()["data"]

        assert filtered["total"] == 0
        assert filtered["items"] == []


class TestSearchRunsInTheDatabase:
    """Paging removed the client-side search, so the server has to carry it.

    The distinction matters: filtering fifteen loaded rows looks identical on screen
    to filtering three thousand stored ones, and only one of them is right.
    """

    async def test_a_search_finds_an_entry_beyond_the_first_page(
        self, client: AsyncClient
    ) -> None:
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        await make_entries(client, accountant, 20)
        # Newest first, so this one is pushed well past a five-row first page.
        await client.post(ENTRIES, headers=accountant, json={
            "description": "قيد نادر جداً للبحث",
            "items": [
                {"account_code": "1010", "debit": "1.00"},
                {"account_code": "3010", "credit": "1.00"},
            ],
        })
        await make_entries(client, accountant, 20)

        found = (await client.get(ENTRIES, headers=accountant, params={
            "limit": 5, "search": "نادر جداً"})).json()["data"]

        assert found["total"] == 1, "the search did not reach past the loaded page"
        assert found["items"][0]["description"] == "قيد نادر جداً للبحث"

    async def test_a_search_matching_nothing_returns_an_empty_page(
        self, client: AsyncClient
    ) -> None:
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        await make_entries(client, accountant, 3)
        empty = (await client.get(ENTRIES, headers=accountant, params={
            "search": "لا يوجد شيء بهذا الاسم إطلاقاً"})).json()["data"]
        assert empty["total"] == 0
        assert empty["items"] == []


class TestTheCeilingHolds:
    async def test_an_enormous_limit_is_refused(self, client: AsyncClient) -> None:
        """Otherwise `?limit=100000` reintroduces exactly the problem paging removed,
        and it will be reached for the first time someone wants "all of it"."""
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        refused = await client.get(ENTRIES, headers=accountant, params={"limit": 100000})
        assert refused.status_code == 422

    async def test_a_negative_offset_is_refused(self, client: AsyncClient) -> None:
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        refused = await client.get(ENTRIES, headers=accountant, params={"offset": -1})
        assert refused.status_code == 422


class TestTheContractIsDeclared:
    """A guard, so a paged endpoint cannot quietly go back to returning everything.

    Reads the OpenAPI schema rather than the source: what matters is the promise the
    API makes to its callers, not how a router happens to be written.
    """

    # Lists that grow with trading volume. Aggregate reports — trial balance, balance
    # sheet, tax summary — are deliberately absent: they return one row per account
    # and paging them would only make them harder to read.
    MUST_BE_PAGED = [
        "/api/v1/accounting/journal-entries",
    ]

    async def test_paged_endpoints_take_limit_and_offset(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        spec = (await client.get("/openapi.json", headers=admin)).json()

        for path in self.MUST_BE_PAGED:
            params = {p["name"] for p in spec["paths"][path]["get"].get("parameters", [])}
            assert {"limit", "offset"} <= params, f"{path} lost its paging controls"

    async def test_paged_endpoints_return_a_page_not_a_list(
        self, client: AsyncClient
    ) -> None:
        """The shape is the safeguard. If `data` were still a bare list, a caller that
        had not been updated would render the first fifty rows as if they were all of
        them — a silent wrong answer instead of a visible break."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        spec = (await client.get("/openapi.json", headers=admin)).json()

        for path in self.MUST_BE_PAGED:
            schema = (spec["paths"][path]["get"]["responses"]["200"]["content"]
                      ["application/json"]["schema"])
            name = schema["$ref"].rsplit("/", 1)[-1]
            data = spec["components"]["schemas"][name]["properties"]["data"]
            ref = data.get("$ref") or next(
                (a["$ref"] for a in data.get("anyOf", []) if "$ref" in a), None
            )
            assert ref is not None, f"{path} does not return a structured envelope"
            page = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
            assert {"items", "total", "limit", "offset"} <= set(page["properties"]), (
                f"{path} does not return a Page"
            )
