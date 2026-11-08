-- ============================================================================
-- COMMERCIAL PHOTOGRAPHY STUDIO & PORTFOLIO MANAGEMENT SYSTEM
-- PURE DATABASE SCHEMA DDL SCRIPT (NO DATA INSERTS)
-- ============================================================================

DROP DATABASE IF EXISTS photography_studio;
CREATE DATABASE photography_studio 
  CHARACTER SET utf8mb4 
  COLLATE utf8mb4_unicode_ci;

USE photography_studio;

-- ============================================================================
-- 1. INDEPENDENT ENTITY TABLES
-- ============================================================================

-- Table 1: photographer (Creators / Artists)
CREATE TABLE photographer (
    photographer_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
	permissions_json LONGTEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Table 2: camera (Hardware Catalog)
CREATE TABLE camera (
    camera_id INT AUTO_INCREMENT PRIMARY KEY,
    make VARCHAR(100) NOT NULL,
    model VARCHAR(150) NOT NULL,
    CONSTRAINT uk_camera_make_model UNIQUE (make, model)
) ENGINE=InnoDB;

-- Table 3: location (Geographic Lookups)
CREATE TABLE location (
    location_id INT AUTO_INCREMENT PRIMARY KEY,
    location_name VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    country VARCHAR(100) NOT NULL,
    latitude DECIMAL(9,6) NULL,
    longitude DECIMAL(10,6) NULL
) ENGINE=InnoDB;

-- Table 4: tag (Category & Taxonomy Catalog)
CREATE TABLE tag (
    tag_id INT AUTO_INCREMENT PRIMARY KEY,
    tag_name VARCHAR(50) NOT NULL,
    category VARCHAR(50) NOT NULL,
    CONSTRAINT uk_tag_category UNIQUE (tag_name, category)
) ENGINE=InnoDB;

-- ============================================================================
-- 2. CORE PHOTO ENTITY
-- ============================================================================

-- Table 5: photo (Main photograph asset records)
CREATE TABLE photo (
    photo_id VARCHAR(50) PRIMARY KEY,
    photographer_id INT NOT NULL,
    photo_url VARCHAR(1000) NOT NULL,
    image_url VARCHAR(1000) NOT NULL,
    description TEXT NULL,
    ai_description TEXT NULL,
    width INT NOT NULL,
    height INT NOT NULL,
    aspect_ratio DECIMAL(8,3) NOT NULL,
    blur_hash VARCHAR(255) NULL,
    featured TINYINT(1) DEFAULT 0,
    submitted_at DATETIME NOT NULL,
    CONSTRAINT fk_photo_photographer 
        FOREIGN KEY (photographer_id) REFERENCES photographer(photographer_id) 
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ============================================================================
-- 3. PHOTO RELATIONSHIPS & TECHNICAL METADATA
-- ============================================================================

-- Table 6: photo_exif (1-to-1 Technical capture specifications)
CREATE TABLE photo_exif (
    photo_id VARCHAR(50) PRIMARY KEY,
    camera_id INT NULL,
    location_id INT NULL,
    iso INT NULL,
    aperture_value DECIMAL(6,2) NULL,
    focal_length VARCHAR(50) NULL,
    exposure_time VARCHAR(50) NULL,
    CONSTRAINT fk_exif_photo 
        FOREIGN KEY (photo_id) REFERENCES photo(photo_id) 
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_exif_camera 
        FOREIGN KEY (camera_id) REFERENCES camera(camera_id) 
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_exif_location 
        FOREIGN KEY (location_id) REFERENCES location(location_id) 
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB;

-- Table 7: photo_stats (1-to-1 User engagement analytics)
CREATE TABLE photo_stats (
    photo_id VARCHAR(50) PRIMARY KEY,
    views BIGINT DEFAULT 0,
    downloads BIGINT DEFAULT 0,
    CONSTRAINT fk_stats_photo 
        FOREIGN KEY (photo_id) REFERENCES photo(photo_id) 
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- Table 8: photo_tag (Many-to-Many junction between photo and tag)
CREATE TABLE photo_tag (
    photo_id VARCHAR(50) NOT NULL,
    tag_id INT NOT NULL,
    PRIMARY KEY (photo_id, tag_id),
    CONSTRAINT fk_phototag_photo 
        FOREIGN KEY (photo_id) REFERENCES photo(photo_id) 
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_phototag_tag 
        FOREIGN KEY (tag_id) REFERENCES tag(tag_id) 
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- Table 9: ai_landmark (1-to-1 AI computer-vision detected landmark)
CREATE TABLE ai_landmark (
    photo_id VARCHAR(50) PRIMARY KEY,
    landmark_name VARCHAR(255) NOT NULL,
    latitude DECIMAL(9,6) NULL,
    longitude DECIMAL(10,6) NULL,
    confidence DECIMAL(5,4) NOT NULL,
    CONSTRAINT fk_landmark_photo 
        FOREIGN KEY (photo_id) REFERENCES photo(photo_id) 
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ============================================================================
-- 4. STAGING TABLE (For Unnormalized Bulk CSV / Kaggle Dataset Imports)
-- ============================================================================

-- Table 10: unsplash_staging
CREATE TABLE unsplash_staging (
    photo_id VARCHAR(50) PRIMARY KEY,
    photo_url VARCHAR(1000),
    photo_image_url VARCHAR(1000),
    photo_submitted_at VARCHAR(50),
    photo_featured VARCHAR(20),
    photo_width INT,
    photo_height INT,
    photo_aspect_ratio DECIMAL(8,3),
    photo_description TEXT,
    ai_description TEXT,
    blur_hash VARCHAR(255),
    photographer_username VARCHAR(100),
    photographer_first_name VARCHAR(100),
    photographer_last_name VARCHAR(100),
    photo_location_name VARCHAR(255),
    photo_location_city VARCHAR(100),
    photo_location_country VARCHAR(100),
    photo_location_latitude DECIMAL(9,6),
    photo_location_longitude DECIMAL(10,6),
    exif_camera_make VARCHAR(100),
    exif_camera_model VARCHAR(150),
    exif_iso INT,
    exif_aperture_value DECIMAL(6,2),
    exif_focal_length VARCHAR(50),
    exif_exposure_time VARCHAR(50),
    ai_primary_landmark_name VARCHAR(255),
    ai_primary_landmark_latitude DECIMAL(9,6),
    ai_primary_landmark_longitude DECIMAL(10,6),
    ai_primary_landmark_confidence DECIMAL(5,4),
    stats_views BIGINT,
    stats_downloads BIGINT
) ENGINE=InnoDB;

-- ============================================================================
-- 5. COMMERCIAL STUDIO EXTENSION TABLES (Phase 2 Report)
-- ============================================================================

-- Table 11: administrator (Studio management credentials & roles)
CREATE TABLE administrator (
    admin_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(150) NOT NULL,
    role VARCHAR(50) DEFAULT 'SuperAdmin',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Table 12: client (Clients booking commercial shoots)
CREATE TABLE client (
    client_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    phone VARCHAR(50) NULL,
    company VARCHAR(150) NULL,
    permissions_json LONGTEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Table 13: shoot (Booked studio sessions & assignments)
CREATE TABLE shoot (
    shoot_id INT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    photographer_id INT NOT NULL,
    shoot_title VARCHAR(255) NOT NULL,
    shoot_date DATE NOT NULL,
    location_name VARCHAR(255) NULL,
    status ENUM('Scheduled', 'In Progress', 'Proofing', 'Completed', 'Delivered') DEFAULT 'Scheduled',
    budget DECIMAL(10,2) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_shoot_client 
        FOREIGN KEY (client_id) REFERENCES client(client_id) 
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_shoot_photographer 
        FOREIGN KEY (photographer_id) REFERENCES photographer(photographer_id) 
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

-- Table 14: client_proofing (Deliverables & review approvals per shoot)
CREATE TABLE client_proofing (
    proofing_id INT AUTO_INCREMENT PRIMARY KEY,
    shoot_id INT NOT NULL,
    photo_id VARCHAR(50) NOT NULL,
    client_feedback TEXT NULL,
    selected_for_delivery TINYINT(1) DEFAULT 0,
    reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_proofing_shoot 
        FOREIGN KEY (shoot_id) REFERENCES shoot(shoot_id) 
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_proofing_photo 
        FOREIGN KEY (photo_id) REFERENCES photo(photo_id) 
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;


-- Default Administrator Account for Initial Login
INSERT IGNORE INTO administrator (admin_id, username, password_hash, full_name, role)
VALUES (101, 'admin', '12345678', 'Administrator', 'SuperAdmin');


-- ============================================================================
-- 6. VERIFY SCHEMA CREATION
-- ============================================================================

SHOW TABLES;