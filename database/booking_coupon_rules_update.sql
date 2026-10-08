-- CouponFlow Booking / Rules update
-- Run `python manage.py migrate` first/recommended.
-- This SQL is a direct XAMPP/MariaDB fallback for the new Booking columns.

ALTER TABLE bookings
    ADD COLUMN IF NOT EXISTS base_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS discount_percentage DECIMAL(7,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS `auto` TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS `manual` TINYINT(1) NOT NULL DEFAULT 0;

UPDATE bookings
SET base_amount = net_amount
WHERE base_amount = 0;
