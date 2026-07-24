-- migrate:up
CREATE OR REPLACE FUNCTION prevent_referenced_category_kind_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.kind IS DISTINCT FROM OLD.kind
       AND (
           EXISTS (SELECT 1 FROM txn WHERE category_id = OLD.id)
           OR EXISTS (
               SELECT 1 FROM merchant_category_mapping WHERE category_id = OLD.id
           )
           OR EXISTS (
               SELECT 1 FROM categorization_proposal
               WHERE proposed_category_id = OLD.id
           )
           OR EXISTS (SELECT 1 FROM category WHERE parent_id = OLD.id)
       )
    THEN
        RAISE EXCEPTION 'category kind is immutable while the category is referenced'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER category_referenced_kind_immutable
BEFORE UPDATE OF kind ON category
FOR EACH ROW
EXECUTE FUNCTION prevent_referenced_category_kind_change();

-- migrate:down
DROP TRIGGER IF EXISTS category_referenced_kind_immutable ON category;
DROP FUNCTION IF EXISTS prevent_referenced_category_kind_change();
