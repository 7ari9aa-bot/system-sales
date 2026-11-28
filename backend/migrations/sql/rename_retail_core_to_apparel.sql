-- Rename the shared "retail.core" product to the sector application it always was.
--
-- The architecture has two levels only; a base application every sector sits on
-- is the third level it forbids (industry-applications §1, §21). The code rename
-- shipped with a LEGACY_KEYS bridge, so this migration may run before or after
-- the deploy without closing a paid screen.
--
-- Idempotent: running it twice changes nothing. Every statement is scoped to the
-- old keys, and a row whose new key already exists is removed rather than
-- duplicated (the three tables carry unique constraints on the new pair).
-- Rollback: rename_retail_core_to_apparel_rollback.sql
BEGIN;

CREATE TEMP TABLE _key_map (old_key text PRIMARY KEY, new_key text NOT NULL) ON COMMIT DROP;
INSERT INTO _key_map (old_key, new_key) VALUES
    ('retail.core', 'apparel'),
    ('retail.purchasing', 'apparel.purchasing'),
    ('retail.warehouse', 'apparel.warehouse'),
    ('retail.inventory_advanced', 'apparel.inventory_advanced'),
    ('customer.engagement', 'apparel.customers'),
    ('ai.customer_support', 'apparel.ai_support'),
    ('ai.business_intelligence', 'apparel.ai_intelligence');

-- 1. Plan inclusions: (plan_id, application_key) is unique.
UPDATE plan_application_inclusions AS p
   SET application_key = m.new_key
  FROM _key_map AS m
 WHERE p.application_key = m.old_key
   AND NOT EXISTS (
       SELECT 1 FROM plan_application_inclusions AS q
        WHERE q.plan_id = p.plan_id AND q.application_key = m.new_key
   );
DELETE FROM plan_application_inclusions AS p
 USING _key_map AS m
 WHERE p.application_key = m.old_key;

-- 2. Subscription items: (subscription_id, application_key, workspace_id) is unique.
UPDATE subscription_items AS s
   SET application_key = m.new_key
  FROM _key_map AS m
 WHERE s.application_key = m.old_key
   AND NOT EXISTS (
       SELECT 1 FROM subscription_items AS q
        WHERE q.subscription_id = s.subscription_id
          AND q.workspace_id IS NOT DISTINCT FROM s.workspace_id
          AND q.application_key = m.new_key
   );
DELETE FROM subscription_items AS s
 USING _key_map AS m
 WHERE s.application_key = m.old_key;

-- 3. Installations: (workspace_id, application_key) is unique. The installation
--    state is what the access gate reads, so the surviving row keeps the state
--    of whichever row was already recorded as active.
UPDATE workspace_app_installations AS i
   SET application_key = m.new_key
  FROM _key_map AS m
 WHERE i.application_key = m.old_key
   AND NOT EXISTS (
       SELECT 1 FROM workspace_app_installations AS q
        WHERE q.workspace_id = i.workspace_id AND q.application_key = m.new_key
   );
DELETE FROM workspace_app_installations AS i
 USING _key_map AS m
 WHERE i.application_key = m.old_key;

COMMIT;
