-- Run this only if the existing XAMPP database already has the coupons table.
-- It makes is_released safe even if an older project migration created it
-- without a database default.

USE coupon_management;

ALTER TABLE coupons
MODIFY COLUMN is_released TINYINT(1) NOT NULL DEFAULT 0;
