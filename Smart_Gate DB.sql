-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Host: 127.0.0.1
-- Generation Time: Mar 10, 2026 at 07:22 AM
-- Server version: 10.4.32-MariaDB
-- PHP Version: 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Database: `smart_gate`
--

-- --------------------------------------------------------

--
-- Table structure for table `home_vehicles`
--

CREATE TABLE `home_vehicles` (
  `Licence_plate` varchar(15) NOT NULL,
  `Type` varchar(20) NOT NULL,
  `category` varchar(50) DEFAULT 'Home',
  `owner_name` varchar(100) DEFAULT '',
  `plate_number` varchar(20) DEFAULT NULL,
  `vehicle_type` varchar(50) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `home_vehicles`
--

INSERT INTO `home_vehicles` (`Licence_plate`, `Type`, `category`, `owner_name`, `plate_number`, `vehicle_type`) VALUES
('KL 10 AZ 2075', 'Car', 'Home', '', 'KL 10 AZ 2075', 'Car'),
('TN 28 BJ 2223', 'Motorcycle', 'Home', '', 'TN 28 BJ 2223', 'Motorcycle'),
('', '', 'Home', '', 'KL21S8086', 'CAR');

-- --------------------------------------------------------

--
-- Table structure for table `system_config`
--

CREATE TABLE `system_config` (
  `id` int(11) NOT NULL,
  `config_key` varchar(100) NOT NULL,
  `config_value` text DEFAULT NULL,
  `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `system_config`
--

INSERT INTO `system_config` (`id`, `config_key`, `config_value`, `updated_at`) VALUES
(1, 'smtp_user', 'preetiking143@gmail.com', '2026-03-09 09:11:16'),
(2, 'smtp_pass', 'qbmg gucd qrlx rzsn', '2026-03-09 09:11:16'),
(3, 'default_report_to', 'dharshan.s.2026@rkmshome.org', '2026-03-09 09:11:16'),
(4, 'smtp_from_name', 'Smart Gate AI', '2026-03-09 09:11:16'),
(5, 'admin_username', 'admin', '2026-03-09 09:11:16'),
(6, 'admin_password', 'admin123', '2026-03-09 09:21:12');

-- --------------------------------------------------------

--
-- Table structure for table `vehicle_activity`
--

CREATE TABLE `vehicle_activity` (
  `id` int(11) NOT NULL,
  `plate_number` varchar(50) DEFAULT NULL,
  `vehicle_type` varchar(20) DEFAULT NULL,
  `vehicle` varchar(20) NOT NULL DEFAULT 'UNKNOWN',
  `entry_time` datetime DEFAULT NULL,
  `exit_time` datetime DEFAULT NULL,
  `duration` varchar(50) DEFAULT NULL,
  `status` varchar(20) DEFAULT NULL,
  `image_path` varchar(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `vehicle_activity`
--

INSERT INTO `vehicle_activity` (`id`, `plate_number`, `vehicle_type`, `vehicle`, `entry_time`, `exit_time`, `duration`, `status`, `image_path`) VALUES
(73, 'MH20EE7602', 'car', 'Unknown Vehicle', '2026-01-14 01:47:00', '2026-01-14 01:47:12', '0h 0m', 'Completed', 'captured_images/MH20EE7602_014712.jpg'),
(104, 'MH20EJ0364', 'BUS', 'Unknown Vehicle', '2026-01-18 23:39:08', '2026-01-20 22:10:13', '46h 31m', 'Completed', 'captured_images/MH20EJ0364_221013.jpg'),
(130, 'MH20EE7602', 'CAR', 'Unknown Vehicle', '2026-01-20 02:14:42', '2026-01-27 22:37:42', '188h 23m', 'Completed', 'captured_images/MH20EE7602_223742.jpg'),
(212, 'MH20EE7602', 'car', 'Unknown Vehicle', '2026-01-21 22:40:20', '2026-01-28 01:05:04', '146h 24m', 'Completed', 'captured_images/MH20EE7602_010504.jpg'),
(217, 'MH20EE7602', 'car', 'Unknown Vehicle', '2026-01-21 22:42:07', '2026-02-27 16:23:20', '881h 41m', 'Completed', 'captured_images/MH20EE7602_162320.jpg'),
(220, 'MH20EJ1036', 'BUS', 'Unknown Vehicle', '2026-01-27 22:44:52', NULL, NULL, 'Inside', 'captured_images/MH20EJ1036_224452.jpg'),
(227, 'MHZOEJ0364', 'CAR', 'Unknown Vehicle', '2026-02-26 12:54:07', NULL, NULL, 'Inside', 'captured_images/MHZOEJ0364_125407.jpg'),
(276, 'TN09BY9726', 'CAR', 'Unknown Vehicle', '2026-02-28 08:50:53', '2026-03-02 10:49:46', '49h 58m', 'Completed', 'captured_images/TN09BY9726_104946.jpg'),
(277, 'TN09BY9726', 'CAR', 'Unknown Vehicle', '2026-03-02 10:50:03', '2026-03-04 10:30:11', '47h 40m', 'Completed', 'captured_images/TN09BY9726_103011.jpg'),
(283, 'MH20EJ0364', 'CAR', 'Unknown Vehicle', '2026-03-02 11:17:23', '2026-03-04 12:59:41', '49h 42m', 'Completed', 'captured_images/MH20EJ0364_125941.jpg'),
(284, 'TN09BY9126', 'CAR', 'Unknown Vehicle', '2026-03-04 10:29:55', NULL, NULL, 'Inside', 'captured_images/TN09BY9126_102955.jpg'),
(285, 'TN09BY9726', 'CAR', 'Unknown Vehicle', '2026-03-04 10:30:13', '2026-03-04 11:04:36', '0h 34m', 'Completed', 'captured_images/TN09BY9726_110436.jpg'),
(286, 'TN09BY9226', 'CAR', 'Unknown Vehicle', '2026-03-04 10:30:18', NULL, NULL, 'Inside', 'captured_images/TN09BY9226_103018.jpg'),
(287, 'MH20EE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 10:35:02', '2026-03-04 10:36:02', '0h 1m', 'Completed', 'captured_images/MH20EE7602_103602.jpg'),
(293, 'MH20EE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 10:36:07', '2026-03-04 11:57:08', '1h 21m', 'Completed', 'captured_images/MH20EE7602_115708.jpg'),
(294, 'TN09BY9726', 'CAR', 'Unknown Vehicle', '2026-03-04 11:04:42', '2026-03-04 11:05:45', '0h 1m', 'Completed', 'captured_images/TN09BY9726_110545.jpg'),
(296, 'TN09BY9726', 'CAR', 'Unknown Vehicle', '2026-03-04 11:05:50', '2026-03-04 13:12:45', '2h 6m', 'Completed', 'captured_images/TN09BY9726_131245.jpg'),
(298, 'MH20EE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 11:57:19', '2026-03-04 11:58:28', '0h 1m', 'Completed', 'captured_images/MH20EE7602_115828.jpg'),
(300, 'MH20EE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 12:59:28', '2026-03-04 13:56:02', '0h 56m', 'Completed', 'captured_images/MH20EE7602_135602.jpg'),
(301, 'MH20EJ0364', 'CAR', 'Unknown Vehicle', '2026-03-04 12:59:41', '2026-03-04 13:00:47', '0h 1m', 'Completed', 'captured_images/MH20EJ0364_130047.jpg'),
(302, 'MH2QEJ0364', 'CAR', 'Unknown Vehicle', '2026-03-04 13:00:01', NULL, NULL, 'Inside', 'captured_images/MH2QEJ0364_130001.jpg'),
(303, 'TN09BY9726', 'CAR', 'Unknown Vehicle', '2026-03-04 13:14:29', '2026-03-04 13:15:47', '0h 1m', 'Completed', 'captured_images/TN09BY9726_131547.jpg'),
(304, 'TN0IBY9726', 'CAR', 'Unknown Vehicle', '2026-03-04 13:15:32', NULL, NULL, 'Inside', 'captured_images/TN0IBY9726_131532.jpg'),
(305, 'TN09BY9726', 'CAR', 'Unknown Vehicle', '2026-03-04 13:15:55', '2026-03-04 13:55:40', '0h 39m', 'Completed', 'captured_images/TN09BY9726_135540.jpg'),
(306, 'MH20EE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 13:56:09', '2026-03-04 13:57:14', '0h 1m', 'Completed', 'captured_images/MH20EE7602_135714.jpg'),
(307, 'MH2OEE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 13:56:41', NULL, NULL, 'Inside', 'captured_images/MH2OEE7602_135641.jpg'),
(308, 'MH20EE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 13:57:25', '2026-03-04 14:03:42', '0h 6m', 'Completed', 'captured_images/MH20EE7602_140342.jpg'),
(309, 'MH20E7602', 'CAR', 'Unknown Vehicle', '2026-03-04 13:57:42', NULL, NULL, 'Inside', 'captured_images/MH20E7602_135742.jpg'),
(310, 'MZ0EE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 13:57:58', NULL, NULL, 'Inside', 'captured_images/MZ0EE7602_135758.jpg'),
(311, 'MH20EE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 14:03:49', '2026-03-04 14:04:56', '0h 1m', 'Completed', 'captured_images/MH20EE7602_140456.jpg'),
(312, 'MH20EE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 14:05:21', NULL, NULL, 'Inside', 'captured_images/MH20EE7602_140521.jpg'),
(313, 'JH20EE7602', 'CAR', 'Unknown Vehicle', '2026-03-04 14:05:36', '2026-03-05 14:24:53', '24h 19m', 'Completed', 'captured_images/JH20EE7602_142453.jpg'),
(314, 'KL21S8086', 'TRUCK', 'Unknown Vehicle', '2026-03-04 15:04:45', '2026-03-04 15:05:59', '0h 1m', 'Completed', 'captured_images/KL21S8086_150559.jpg'),
(315, 'KL2IS8086', 'CAR', 'Unknown Vehicle', '2026-03-04 15:05:41', '2026-03-04 16:13:08', '1h 7m', 'Completed', 'captured_images/KL2IS8086_161308.jpg'),
(316, 'KL2IS0086', 'CAR', 'Unknown Vehicle', '2026-03-04 15:36:58', NULL, NULL, 'Inside', 'captured_images/KL2IS0086_153658.jpg'),
(317, 'KL21S8086', 'TRUCK', 'Unknown Vehicle', '2026-03-04 15:37:03', '2026-03-04 15:38:21', '0h 1m', 'Completed', 'captured_images/KL21S8086_153821.jpg'),
(318, 'KL21S8086', 'CAR', 'Unknown Vehicle', '2026-03-04 15:38:30', '2026-03-04 15:40:47', '0h 2m', 'Completed', 'captured_images/KL21S8086_154047.jpg'),
(320, 'DL2CAB1234', 'CAR', 'Unknown Vehicle', '2026-03-04 16:11:51', '2026-03-09 15:51:53', '119h 40m', 'Completed', 'captured_images/DL2CAB1234_155153.jpg'),
(321, 'KA03GH9012', 'BICYCLE', 'Unknown Vehicle', '2026-03-05 03:12:00', NULL, NULL, 'Inside', 'captured_images/KA03GH9012_161201.jpg'),
(322, 'KL21S8086', 'CAR', 'Unknown Vehicle', '2026-03-04 16:13:04', '2026-03-05 13:58:52', '21h 45m', 'Completed', 'captured_images/KL21S8086_135852.jpg'),
(323, 'KL2IS8086', 'TRUCK', 'Unknown Vehicle', '2026-03-04 16:14:00', NULL, NULL, 'Inside', 'captured_images/KL2IS8086_161400.jpg'),
(324, 'KA03GH9012', 'MOTORCYCLE', 'Unknown Vehicle', '2026-03-04 21:44:00', NULL, NULL, 'Inside', 'captured_images/KA03GH9013_161423.jpg'),
(325, 'TN01AB1234', 'BUS', 'Unknown Vehicle', '2026-03-04 16:14:31', '2026-03-05 14:00:35', '21h 46m', 'Completed', 'captured_images/TN01AB1234_140035.jpg'),
(326, 'MH20EJ0364', 'TRAIN', 'Unknown Vehicle', '2026-03-05 13:54:03', NULL, NULL, 'Inside', 'captured_images/MH20EJ0364_135403.jpg'),
(327, 'TN01AB1234', 'TRUCK', 'Unknown Vehicle', '2026-03-05 14:12:01', '2026-03-05 14:28:46', '0h 16m', 'Completed', 'captured_images/TN01AB1234_142846.jpg'),
(328, 'TN0AB1234', 'BUS', 'Unknown Vehicle', '2026-03-05 14:12:03', NULL, NULL, 'Inside', 'captured_images/TN0AB1234_141203.jpg'),
(330, 'TN01AB1234', 'TRUCK', 'Unknown Vehicle', '2026-03-05 14:53:40', '2026-03-09 14:37:17', '95h 43m', 'Completed', 'captured_images/TN01AB1234_143717.jpg'),
(331, 'KA01EK5678', 'MOTORCYCLE', 'Unknown Vehicle', '2026-03-05 15:45:06', '2026-03-10 11:08:21', '115h 23m', 'Completed', 'captured_images/KA01EK5678_110821.jpg'),
(332, 'MH12AB1234', 'BUS', 'Unknown Vehicle', '2026-03-09 11:17:54', '2026-03-09 15:23:27', '4h 5m', 'Completed', 'captured_images/MH12AB1234_152327.jpg'),
(333, 'TN01AB1234', 'BUS', 'Unknown Vehicle', '2026-03-09 14:37:44', '2026-03-09 15:19:51', '0h 42m', 'Completed', 'captured_images/TN01AB1234_151951.jpg'),
(334, 'TN01AB1234', 'BUS', 'Unknown Vehicle', '2026-03-09 15:20:24', '2026-03-10 08:59:05', '17h 38m', 'Completed', 'captured_images/TN01AB1234_085905.jpg'),
(335, 'MH12AB1234', 'BUS', 'Unknown Vehicle', '2026-03-09 15:23:28', NULL, NULL, 'Inside', 'captured_images/MH12AB1234_152328.jpg'),
(336, 'TN4JA1111', 'MOTORCYCLE', 'Unknown Vehicle', '2026-03-09 16:14:14', NULL, NULL, 'Inside', 'captured_images/TN4JA1111_161414.jpg'),
(337, 'TN43A1111', 'MOTORCYCLE', 'Unknown Vehicle', '2026-03-09 16:15:07', NULL, NULL, 'Inside', 'captured_images/TN43A1111_161507.jpg'),
(338, 'TN01AB1234', 'TRUCK', 'Unknown Vehicle', '2026-03-10 08:59:10', '2026-03-10 11:03:39', '2h 4m', 'Completed', 'captured_images/TN01AB1234_110339.jpg'),
(339, 'DL7CQ1939', 'TRUCK', 'Unknown Vehicle', '2026-03-10 14:31:00', NULL, NULL, 'Inside', 'captured_images/DL7CO1939_090114.jpg'),
(340, 'TN01AB1234', 'BUS', 'Unknown Vehicle', '2026-03-10 11:04:10', '2026-03-10 11:05:58', '0h 1m', 'Completed', 'captured_images/TN01AB1234_110558.jpg'),
(341, 'KL21S8086', 'CAR', 'Unknown Vehicle', '2026-03-10 11:08:37', NULL, NULL, 'Inside', 'captured_images/KL21S8086_110837.jpg');

--
-- Triggers `vehicle_activity`
--
DELIMITER $$
CREATE TRIGGER `calculate_duration_automatically` BEFORE UPDATE ON `vehicle_activity` FOR EACH ROW BEGIN
    -- Check if exit_time is being updated and is not empty
    IF NEW.exit_time IS NOT NULL THEN
        -- Calculate the duration and format it as 'Xh Ym'
        SET NEW.duration = CONCAT(
            TIMESTAMPDIFF(HOUR, OLD.entry_time, NEW.exit_time), 'h ', 
            MOD(TIMESTAMPDIFF(MINUTE, OLD.entry_time, NEW.exit_time), 60), 'm'
        );
    END IF;
END
$$
DELIMITER ;
DELIMITER $$
CREATE TRIGGER `set_home_visitor_status` BEFORE INSERT ON `vehicle_activity` FOR EACH ROW BEGIN
    DECLARE is_home INT;

    -- Check if the new plate exists in home_vehicles
    -- We use REPLACE() to remove spaces from the home_vehicles list for a fair comparison
    SELECT COUNT(*) INTO is_home
    FROM home_vehicles
    WHERE REPLACE(Licence_plate, ' ', '') = NEW.plate_number;

    -- If a match is found, label it 'Home Vehicle', otherwise 'Visitor'
    IF is_home > 0 THEN
        SET NEW.vehicle = 'Home Vehicle';
    ELSE
        SET NEW.vehicle = 'Unknown Vehicle';
    END IF;
END
$$
DELIMITER ;

--
-- Indexes for dumped tables
--

--
-- Indexes for table `system_config`
--
ALTER TABLE `system_config`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `config_key` (`config_key`);

--
-- Indexes for table `vehicle_activity`
--
ALTER TABLE `vehicle_activity`
  ADD PRIMARY KEY (`id`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `system_config`
--
ALTER TABLE `system_config`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=13;

--
-- AUTO_INCREMENT for table `vehicle_activity`
--
ALTER TABLE `vehicle_activity`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=343;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
