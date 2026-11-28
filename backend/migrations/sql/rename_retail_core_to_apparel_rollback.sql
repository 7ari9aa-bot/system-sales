-- Undo rename_retail_core_to_apparel.sql.
--
-- Restores the pre-rename keys so the previous release (which knows nothing about
-- LEGACY_KEYS) keeps serving. Same conflict policy: an existing old-key row wins
-- and the duplicate new-key row is removed.
BEGIN;

CREATE TEMP TABLE _key_map (new_key text PRIMARY KEY, old_key text NOT NULL) ON COMMIT DROP;
INSERT INTO _key_map (new_key, old_key) VALUES
    ('apparel', 'retail.core'),
    ('apparel.purchasing', 'retail.purchasing'),
    ('apparel.warehouse', 'retail.warehouse'),
    ('apparel.inventory_advanced', 'retail.inventory_advanced'),
    ('apparel.customers', 'customer.engagement'),
    ('apparel.ai_support', 'ai.customer_support'),
    ('apparel.ai_intelligence', 'ai.business_intelligence');

UPDATE plan_application_inclusions AS p SET application_key = m.old_key
  FROM _key_map AS m
 WHERE p.application_key = m.new_key
   AND NOT EXISTS (SELECT 1 FROM plan_application_inclusions AS q
                    WHERE q.plan_id = p.plan_id AND q.application_key = m.old_key);
DELETE FROM plan_application_inclusions AS p USING _key_map AS m WHERE p.application_key = m.new_key;

UPDATE subscription_items AS s SET application_key = m.old_key
  FROM _key_map AS m
 WHERE s.application_key = m.new_key
   AND NOT EXISTS (SELECT 1 FROM subscription_items AS q
                    WHERE q.subscription_id = s.subscription_id
                      AND q.workspace_id IS NOT DISTINCT FROM s.workspace_id
                      AND q.application_key = m.old_key);
DELETE FROM subscription_items AS s USING _key_map AS m WHERE s.application_key = m.new_key;

UPDATE workspace_app_installations AS i SET application_key = m.old_key
  FROM _key_map AS m
 WHERE i.application_key = m.new_key
   AND NOT EXISTS (SELECT 1 FROM workspace_app_installations AS q
                    WHERE q.workspace_id = i.workspace_id AND q.application_key = m.old_key);
DELETE FROM workspace_app_installations AS i USING _key_map AS m WHERE i.application_key = m.new_key;

COMMIT;
