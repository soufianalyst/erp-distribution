"""Frontend rules that no other check enforces.

The frontend has no test runner of its own — `vite build` is the only gate, and it
happily builds a page that renders four thousand rows. So the one project rule that
keeps being broken by hand-written markup is checked here, from the suite that does
run.

The rule (CLAUDE.md, Part III): every data table paginates at 15 rows, implemented
once in `components/Ui.jsx`'s `Table`. It was broken three times anyway, each time by
building a `<table>` inline instead of reaching for the shared one:

* the journal — 3,787 entries on a single page, and no way to search them
* purchase reorder suggestions — up to 743 products inside a fixed-height scroll box
* the stocktake counting sheet — up to 2,475 batch lines

Nobody reads a rule while writing markup that looks fine against seed data. A test
does.
"""

import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src"

# Where a hand-written <table> is correct, and why. Anything not listed here is
# expected to use the shared Table.
ALLOWED = {
    # Print pages must render the whole document: paginating paper is nonsense, and
    # a picking list that stopped at row 15 would send the driver out short.
    "pages/PrintInvoicePage.jsx": "printed document",
    "pages/PrintPickingPage.jsx": "printed document",
    "pages/PrintPickupPrepPage.jsx": "printed document",
    "pages/PrintStocktakePage.jsx": "printed document",
    "pages/PrintAdjustmentPage.jsx": "printed document",
    "pages/PrintDamageReportPage.jsx": "printed document",
    "pages/PrintDiscountReportPage.jsx": "printed document",
    "pages/PrintRationedPage.jsx": "printed document",
    # Detail views of a single record — bounded by the document itself, not by how
    # much the business has traded.
    "pages/AuditLogPage.jsx": "before/after fields of one audited change",
    "pages/FieldPage.jsx": "provisional receipt for one sale",
    "pages/SalesPage.jsx": "returns recorded against one invoice",
    "pages/PurchasesPage.jsx": "returns recorded against one invoice",
    # The implementation itself.
    "components/Ui.jsx": "the shared Table",
}


def _sources() -> list[pathlib.Path]:
    return sorted(FRONTEND.glob("pages/*.jsx")) + sorted(FRONTEND.glob("components/*.jsx"))


def test_the_frontend_is_where_we_think_it_is() -> None:
    """Guard the guard: a moved directory would make everything below vacuous."""
    assert FRONTEND.is_dir(), f"frontend source not found at {FRONTEND}"
    assert (FRONTEND / "components" / "Ui.jsx").is_file()
    assert len(_sources()) > 20, "found suspiciously few pages to check"


def test_no_page_builds_its_own_data_table() -> None:
    """Every list goes through the shared, paginated Table."""
    offenders = []
    for path in _sources():
        relative = f"{path.parent.name}/{path.name}"
        if relative in ALLOWED:
            continue
        if "<table" in path.read_text(encoding="utf-8"):
            offenders.append(relative)
    assert not offenders, (
        f"{offenders} render a <table> by hand, which skips the 15-row pagination "
        "every data list is supposed to have. Use <Table> from components/Ui, or add "
        "the file to ALLOWED here with the reason it is exempt."
    )


def test_the_shared_table_still_paginates_at_fifteen() -> None:
    """The rule's actual number, in the one place it is implemented.

    Checked because the whole point of centralising pagination is that this default
    is the only thing standing between a screen and four thousand rows.
    """
    source = (FRONTEND / "components" / "Ui.jsx").read_text(encoding="utf-8")
    assert re.search(r"pageSize\s*=\s*15", source), (
        "the shared Table no longer defaults to 15 rows a page"
    )
    assert "slice((currentPage - 1) * pageSize, currentPage * pageSize)" in source, (
        "the shared Table no longer slices its rows — it may be rendering all of them"
    )


def test_no_page_overrides_the_page_size() -> None:
    """An override is how "paginated" quietly becomes "all of it on one page"."""
    offenders = []
    for path in _sources():
        if path.name == "Ui.jsx":
            continue
        for match in re.finditer(r"pageSize=\{(\d+)\}", path.read_text(encoding="utf-8")):
            if int(match.group(1)) > 50:
                offenders.append(f"{path.name}: pageSize={match.group(1)}")
    assert not offenders, f"page-size overrides large enough to defeat paging: {offenders}"
