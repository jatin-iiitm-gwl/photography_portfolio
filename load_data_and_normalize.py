import os
import mysql.connector

# 1. TSV Path
# Automatically locate photos.tsv000 in the current project folder
base_dir = os.path.dirname(os.path.abspath(__file__))
raw_path = os.path.join(base_dir, "photos.tsv000")
tsv_file_path = raw_path.replace("\\", "/")

formatted_path = raw_path.replace("\\", "/")
print(f"Target TSV File: {formatted_path}")

# 2. Database Connection
conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="*******",  # <-- Enter MySQL password
    database="photography_studio",
    allow_local_infile=True
)
cursor = conn.cursor()

cursor.execute("SET GLOBAL local_infile = 1;")

print("\n--- Step 1: Re-creating 'unsplash_staging' with exact Unsplash Lite 31-column order ---")
cursor.execute("DROP TABLE IF EXISTS unsplash_staging;")
cursor.execute("""
CREATE TABLE unsplash_staging (
    photo_id VARCHAR(50),
    photo_url VARCHAR(1000),
    photo_image_url VARCHAR(1000),
    photo_submitted_at VARCHAR(50),
    photo_featured VARCHAR(20),
    photo_width INT,
    photo_height INT,
    photo_aspect_ratio DECIMAL(8,3),
    photo_description TEXT,
    photographer_username VARCHAR(100),
    photographer_first_name VARCHAR(100),
    photographer_last_name VARCHAR(100),
    exif_camera_make VARCHAR(100),
    exif_camera_model VARCHAR(150),
    exif_iso INT,
    exif_aperture_value DECIMAL(6,2),
    exif_focal_length VARCHAR(50),
    exif_exposure_time VARCHAR(50),
    photo_location_name VARCHAR(255),
    photo_location_latitude DECIMAL(9,6),
    photo_location_longitude DECIMAL(10,6),
    photo_location_country VARCHAR(100),
    photo_location_city VARCHAR(100),
    stats_views BIGINT,
    stats_downloads BIGINT,
    ai_description TEXT,
    ai_primary_landmark_name VARCHAR(255),
    ai_primary_landmark_latitude DECIMAL(9,6),
    ai_primary_landmark_longitude DECIMAL(10,6),
    ai_primary_landmark_confidence DECIMAL(5,4),
    blur_hash VARCHAR(255)
);
""")
conn.commit()

print("--- Step 2: Bulk Loading 25,000 photos into unsplash_staging ---")
load_query = f"""
LOAD DATA LOCAL INFILE '{formatted_path}'
INTO TABLE unsplash_staging
FIELDS TERMINATED BY '\\t'
LINES TERMINATED BY '\\n'
IGNORE 1 LINES;
"""
cursor.execute(load_query)
conn.commit()

cursor.execute("SELECT COUNT(*) FROM unsplash_staging;")
print(f" Loaded {cursor.fetchone()[0]} rows into unsplash_staging with accurate column mapping!")

print("\n--- Step 3: Ensuring AUTO_INCREMENT on Relational Tables ---")
for tbl, col in [("photographer", "photographer_id"), ("camera", "camera_id"), ("location", "location_id")]:
    try:
        cursor.execute(f"ALTER TABLE {tbl} MODIFY {col} INT AUTO_INCREMENT;")
        conn.commit()
    except Exception as e:
        pass

# 2. Camera (Safe Insert + Trim)
cursor.execute("INSERT IGNORE INTO photographer (photographer_id, username, first_name, last_name) VALUES (1, 'unsplash_creator', 'Unsplash', 'Contributor');")
conn.commit()

print("--- Step 4: Normalizing into 9 Relational Tables ---")

# 1. Photographers
print("  Populating 'photographer'...")
cursor.execute("""
INSERT IGNORE INTO photographer (username, first_name, last_name)
SELECT DISTINCT 
    photographer_username, 
    NULLIF(photographer_first_name, ''), 
    NULLIF(photographer_last_name, '')
FROM unsplash_staging
WHERE photographer_username IS NOT NULL AND photographer_username != '';
""")
conn.commit()
print(f"    Photographers ready: {cursor.rowcount} inserted.")

# 2. Cameras
print("  Populating 'camera'...")
cursor.execute("""
INSERT IGNORE INTO camera (make, model)
SELECT DISTINCT 
    NULLIF(exif_camera_make, ''), 
    NULLIF(exif_camera_model, '')
FROM unsplash_staging
WHERE exif_camera_make IS NOT NULL AND exif_camera_make != '';
""")
conn.commit()
print(f"    Cameras ready: {cursor.rowcount} inserted.")

# 3. Locations
print("  Populating 'location'...")
cursor.execute("""
INSERT IGNORE INTO location (location_name, city, country, latitude, longitude)
SELECT DISTINCT 
    NULLIF(photo_location_name, ''),
    NULLIF(photo_location_city, ''),
    NULLIF(photo_location_country, ''),
    NULLIF(photo_location_latitude, ''),
    NULLIF(photo_location_longitude, '')
FROM unsplash_staging
WHERE (photo_location_name IS NOT NULL AND photo_location_name != '')
   OR (photo_location_city IS NOT NULL AND photo_location_city != '')
   OR (photo_location_country IS NOT NULL AND photo_location_country != '');
""")
conn.commit()
print(f"    Locations ready: {cursor.rowcount} inserted.")

# 4. Photos (Core)
print("  Populating core 'photo' table...")
cursor.execute("""
INSERT IGNORE INTO photo (
    photo_id, photographer_id, photo_url, image_url, description, 
    ai_description, width, height, aspect_ratio, blur_hash, featured, submitted_at
)
SELECT 
    s.photo_id,
    COALESCE(pg.photographer_id, 1),
    s.photo_url,
    s.photo_image_url,
    s.photo_description,
    s.ai_description,
    s.photo_width,
    s.photo_height,
    s.photo_aspect_ratio,
    s.blur_hash,
    CASE WHEN LOWER(s.photo_featured) IN ('true', '1') THEN 1 ELSE 0 END,
    STR_TO_DATE(LEFT(s.photo_submitted_at, 19), '%Y-%m-%d %H:%i:%s')
FROM unsplash_staging s
LEFT JOIN photographer pg ON s.photographer_username = pg.username
WHERE s.photo_id IS NOT NULL AND s.photo_id != '';
""")
conn.commit()
print(f"    Photos ready: {cursor.rowcount} inserted.")

# 5. Photo EXIF
print("  Populating 'photo_exif'...")
cursor.execute("""
INSERT IGNORE INTO photo_exif (
    photo_id, camera_id, location_id, iso, aperture_value, focal_length, exposure_time
)
SELECT 
    s.photo_id,
    c.camera_id,
    l.location_id,
    NULLIF(s.exif_iso, ''),
    NULLIF(s.exif_aperture_value, ''),
    NULLIF(s.exif_focal_length, ''),
    NULLIF(s.exif_exposure_time, '')
FROM unsplash_staging s
JOIN photo p ON s.photo_id = p.photo_id
LEFT JOIN camera c ON s.exif_camera_make = c.make AND s.exif_camera_model = c.model
LEFT JOIN location l ON (
    (s.photo_location_name IS NOT NULL AND s.photo_location_name = l.location_name)
    OR (s.photo_location_name IS NULL AND s.photo_location_city = l.city AND s.photo_location_country = l.country)
);
""")
conn.commit()
print(f"    EXIF metadata ready: {cursor.rowcount} inserted.")

# 6. Photo Stats
print("  Populating 'photo_stats'...")
cursor.execute("""
INSERT IGNORE INTO photo_stats (photo_id, views, downloads)
SELECT 
    s.photo_id,
    COALESCE(s.stats_views, 0),
    COALESCE(s.stats_downloads, 0)
FROM unsplash_staging s
JOIN photo p ON s.photo_id = p.photo_id;
""")
conn.commit()
print(f"    Stats ready: {cursor.rowcount} inserted.")

# 7. AI Landmarks
print("  Populating 'ai_landmark'...")
cursor.execute("""
INSERT IGNORE INTO ai_landmark (photo_id, landmark_name, latitude, longitude, confidence)
SELECT 
    s.photo_id,
    s.ai_primary_landmark_name,
    NULLIF(s.ai_primary_landmark_latitude, ''),
    NULLIF(s.ai_primary_landmark_longitude, ''),
    NULLIF(s.ai_primary_landmark_confidence, '')
FROM unsplash_staging s
JOIN photo p ON s.photo_id = p.photo_id
WHERE s.ai_primary_landmark_name IS NOT NULL AND s.ai_primary_landmark_name != '';
""")
conn.commit()
print(f"    AI Landmarks ready: {cursor.rowcount} inserted.")

# Final Verification
cursor.execute("SELECT COUNT(*) FROM photo;")
total_photos = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM photographer;")
total_pg = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM camera;")
total_cam = cursor.fetchone()[0]

print("\n🎉 ETL NORMALIZATION COMPLETED SUCCESSFULLY!")
print(f"Total Photos in Database: {total_photos}")
print(f"Total Photographers: {total_pg}")
print(f"Total Camera Models: {total_cam}")

cursor.close()
conn.close()