-- 清理用户测试产生的 ZZZ 前缀测试数据（按外键依赖顺序，单事务）。
-- 仅删除测试实体；audit_log 保留（历史不抹除）。
BEGIN;

CREATE TEMP TABLE zzz_types AS SELECT id FROM node_type WHERE name LIKE 'ZZZ%';
CREATE TEMP TABLE zzz_skus AS SELECT id FROM sku WHERE root_type_id IN (SELECT id FROM zzz_types);

DELETE FROM quote_item WHERE sku_id IN (SELECT id FROM zzz_skus)
   OR quote_id IN (SELECT id FROM quote WHERE customer_name LIKE '%ZZZ%');
DELETE FROM quote WHERE customer_name LIKE '%ZZZ%';
DELETE FROM sku_price WHERE sku_id IN (SELECT id FROM zzz_skus);
DELETE FROM sku WHERE id IN (SELECT id FROM zzz_skus);  -- 级联 config_node / attribute_value
DELETE FROM config_draft WHERE root_type_id IN (SELECT id FROM zzz_types) OR title LIKE 'ZZZ%';
DELETE FROM import_batch WHERE filename LIKE 'zzz%';

-- 成品件存在 merged_into 自引用：先解除再删
UPDATE purchased_part SET merged_into_id = NULL, status = 'retired' WHERE name LIKE 'ZZZ%';
DELETE FROM purchased_part WHERE name LIKE 'ZZZ%';
DELETE FROM supplier WHERE name LIKE 'ZZZ%';

DELETE FROM attribute_option WHERE attribute_id IN
  (SELECT id FROM attribute_def WHERE node_type_id IN (SELECT id FROM zzz_types));
DELETE FROM attribute_def WHERE node_type_id IN (SELECT id FROM zzz_types);
DELETE FROM component_slot WHERE parent_type_id IN (SELECT id FROM zzz_types)
   OR child_type_id IN (SELECT id FROM zzz_types);
DELETE FROM node_type WHERE id IN (SELECT id FROM zzz_types);

COMMIT;
