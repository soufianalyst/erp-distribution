"""scope tax rates to countries

Replaces the free-text `tax_rates.country` label with a structured
`country_code` (ISO 3166-1 alpha-2), and records the company's own country so
country-specific taxes can be offered only where they apply.

The old column was a display label that nothing read; any text in it cannot be
mapped to a code automatically, so it is copied across only when it already
holds a valid two-letter code and dropped otherwise.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-08-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tax_rates", sa.Column("country_code", sa.String(length=2), nullable=True))
    op.create_index(op.f("ix_tax_rates_country_code"), "tax_rates", ["country_code"])
    # Salvage anything already stored as a plain country code.
    op.execute(
        """
        UPDATE tax_rates
        SET country_code = upper(country)
        WHERE country IS NOT NULL AND length(trim(country)) = 2
        """
    )
    op.drop_column("tax_rates", "country")

    op.add_column(
        "company_settings", sa.Column("country_code", sa.String(length=2), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("company_settings", "country_code")
    op.add_column("tax_rates", sa.Column("country", sa.String(length=100), nullable=True))
    op.execute("UPDATE tax_rates SET country = country_code WHERE country_code IS NOT NULL")
    op.drop_index(op.f("ix_tax_rates_country_code"), table_name="tax_rates")
    op.drop_column("tax_rates", "country_code")
