-- Rewind a database stamped with a8c1d2e3f4a5 back onto the shared trunk.
--
-- Why this is needed
-- ------------------
-- `main` used to be an independently committed line whose migrations forked from the
-- trunk at d3e4f5a6b7c8 ("the company owns its own day boundary") and applied exactly
-- one migration of its own: a8c1d2e3f4a5, an earlier customer portal. When `main` was
-- replaced by the development line, that one revision ceased to exist in the repository
-- — and Alembic refuses to run at all when the database names a revision it cannot find:
--
--     ERROR [alembic.util.messaging] Can't locate revision identified by 'a8c1d2e3f4a5'
--
-- What this does
-- --------------
-- Undoes exactly what a8c1d2e3f4a5 created, then rewinds the stamp to the fork point.
-- The next `alembic upgrade head` walks the surviving chain from d3e4f5a6b7c8 onward and
-- builds its own portal (e4f5a6b7c8d9 → f5a6b7c8d9e0 → …) on the way.
--
-- What is lost, and what is not
-- -----------------------------
-- Lost: rows in customer_orders / customer_order_lines, and the users.customer_id link.
-- Those exist only on the abandoned fork; the surviving chain models the same idea with
-- its own tables (customer_logins, and its own customer_orders), so they cannot be
-- carried across.
--
-- Kept: everything created before the fork — products, batches, warehouses, customers,
-- suppliers, every invoice, return, payment and journal entry. That is the great majority
-- of the database, and none of it is touched here.
--
-- Take a backup before running this. Render's dashboard can do it, or:
--   pg_dump "$DATABASE_URL" > before-rewind.sql

BEGIN;

-- Refuse to run against anything other than the state this script is written for. A
-- database already on the trunk, or on some third lineage, must not be altered.
DO $$
DECLARE current_rev text;
BEGIN
    SELECT version_num INTO current_rev FROM alembic_version;
    IF current_rev IS DISTINCT FROM 'a8c1d2e3f4a5' THEN
        RAISE EXCEPTION
            'refusing to rewind: expected stamp a8c1d2e3f4a5, found %. This script is '
            'only for a database left on the abandoned main fork.', current_rev;
    END IF;
END $$;

-- The abandoned fork's portal. CASCADE because its own indexes and foreign keys hang
-- off these, and dropping them individually only spells out what CASCADE already does.
DROP TABLE IF EXISTS customer_order_lines CASCADE;
DROP TABLE IF EXISTS customer_orders CASCADE;

-- The link it added to users. The surviving chain keeps portal identities in their own
-- table instead, so this column has no counterpart to migrate into.
ALTER TABLE users DROP COLUMN IF EXISTS customer_id;

-- Its enum type. Left behind by the fork's own downgrade() — which said so — but it
-- collides with the type the surviving chain creates under the same name, so it goes.
DROP TYPE IF EXISTS customerorderstatus;

-- Back to the fork point. From here the surviving chain is a straight line to head.
UPDATE alembic_version SET version_num = 'd3e4f5a6b7c8';

COMMIT;
