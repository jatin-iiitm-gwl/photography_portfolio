"""
================================================================================
PHOTOGRAPHY PORTFOLIO DBMS - ZERO-DEPENDENCY LOCALHOST PYTHON BRIDGE
Works with standard Python. Only requires 'mysql-connector-python'.
Supports:
  1. Full 25,000-row dataset loading (/api/connect, /api/photos)
  2. Role-Based Authentication:
     - User (Client) Login  -> POST /api/user/login
     - Photographer Login   -> POST /api/photographer/login
     - Administrator Login  -> POST /api/admin/login
  3. Admin Management & User Granular Permissions:
     - List Users (client)  -> POST /api/admin/users/list
     - Add/Update User      -> POST /api/admin/users/save
     - Delete User          -> POST /api/admin/users/delete
     - Admin Change Pass    -> POST /api/admin/change-password
  4. Live MySQL Photo CRUD Operations:
     - ADD Photo (INSERT)    -> POST /api/photo/add
     - EDIT Photo (UPDATE)   -> POST /api/photo/update
     - DELETE Photo (DELETE) -> POST /api/photo/delete
  5. Instant Server Stop (<0.1s):
     - Press Ctrl + C in terminal (instant exit)
     - Type 'q' or 'stop' + Enter in terminal
     - Or click 'Stop Bridge Server' button in Webpage Settings (/api/shutdown)
================================================================================
"""

import hashlib
import json
import os
import signal
import sys
import threading
import time
from decimal import Decimal
import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import mysql.connector  # type: ignore

# ==============================================================================
# CONFIGURATION: MySQL Credentials
# ==============================================================================
MYSQL_CONFIG = {
    "host": "localhost", # Enter HOST
    "port": 3306 , #Enter PORT 
    "user": "root", #Enter USER
    "password": "******",  # MySQL root password
    "database": "photography_studio" # Enter DATABASE NAME
}

DEFAULT_ROW_LIMIT = 25000
_SERVER_INSTANCE = None


def stop_server_immediately(reason="User requested stop"):
    """Instantly releases port 5000 and terminates the process with zero delay."""
    print(f"\n[STOP] {reason} — Stopping bridge server immediately...")
    try:
        if _SERVER_INSTANCE is not None:
            _SERVER_INSTANCE.socket.close()
    except Exception:
        pass
    os._exit(0)


def json_serializer(obj):
    """Custom serializer so MySQL Decimal, Date, and DateTime convert cleanly to JSON"""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return str(obj)
    return str(obj)


def get_db_connection(client_params=None):
    params = client_params or {}
    cfg = {
        "host": params.get("host") or MYSQL_CONFIG["host"],
        "port": int(params.get("port") or MYSQL_CONFIG["port"]),
        "user": params.get("user") or MYSQL_CONFIG["user"],
        "password": params.get("password") if params.get("password") not in (None, "") else MYSQL_CONFIG["password"],
        "database": params.get("database") or MYSQL_CONFIG["database"]
    }
    return mysql.connector.connect(**cfg), cfg


def ensure_role_and_aux_tables(conn, cursor):
    """
    Ensures client, administrator, photo_exif, and ai_landmark tables have all required
    columns so User login, Admin login, and Granular User Permissions work seamlessly.
    """
    try:
        # 1. Ensure client table exists & has username + permissions_json columns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS client (
                client_id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) NULL,
                full_name VARCHAR(150) NOT NULL,
                email VARCHAR(150) NULL,
                phone VARCHAR(50) NULL,
                company VARCHAR(150) NULL,
                permissions_json LONGTEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("SHOW COLUMNS FROM client LIKE 'username';")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE client ADD COLUMN username VARCHAR(100) NULL AFTER client_id;")
        cursor.execute("SHOW COLUMNS FROM client LIKE 'permissions_json';")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE client ADD COLUMN permissions_json LONGTEXT NULL;")

        cursor.execute("SHOW COLUMNS FROM photographer LIKE 'permissions_json';")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE photographer ADD COLUMN permissions_json LONGTEXT NULL;")

        # 2. Ensure administrator table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS administrator (
                admin_id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(150) NULL,
                role VARCHAR(50) DEFAULT 'SuperAdmin',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
    except Exception as e:
        print(f"[BRIDGE-INFO] Role table schema check note: {e}")

    try:
        cursor.execute("SELECT COUNT(*) AS cnt FROM photo_exif;")
        exif_count = cursor.fetchone()["cnt"]
        if exif_count == 0:
            cursor.execute("SHOW TABLES LIKE 'unsplash_staging';")
            if cursor.fetchone():
                print("[BRIDGE] Auto-syncing photo_exif & ai_landmark from unsplash_staging...")
                cursor.execute("""
                    INSERT IGNORE INTO photo_exif (
                        photo_id, camera_id, location_id, iso, aperture_value, focal_length, exposure_time
                    )
                    SELECT
                        s.photo_id,
                        c.camera_id,
                        l.location_id,
                        CAST(NULLIF(s.exif_iso, '') AS UNSIGNED),
                        CAST(NULLIF(s.exif_aperture_value, '') AS DECIMAL(5,2)),
                        NULLIF(s.exif_focal_length, ''),
                        NULLIF(s.exif_exposure_time, '')
                    FROM unsplash_staging s
                    INNER JOIN photo p ON p.photo_id = s.photo_id
                    LEFT JOIN camera c
                        ON c.make = COALESCE(NULLIF(s.exif_camera_make, ''), 'Unknown')
                       AND c.model = COALESCE(NULLIF(s.exif_camera_model, ''), 'Unknown')
                    LEFT JOIN location l
                        ON l.location_name = COALESCE(NULLIF(s.photo_location_name, ''), 'Unknown')
                       AND l.city = COALESCE(NULLIF(s.photo_location_city, ''), 'Unknown')
                       AND l.country = COALESCE(NULLIF(s.photo_location_country, ''), 'Unknown');
                """)
                cursor.execute("""
                    INSERT IGNORE INTO ai_landmark (
                        photo_id, landmark_name, latitude, longitude, confidence
                    )
                    SELECT
                        s.photo_id,
                        NULLIF(s.ai_primary_landmark_name, ''),
                        CAST(NULLIF(s.ai_primary_landmark_latitude, '') AS DECIMAL(10,6)),
                        CAST(NULLIF(s.ai_primary_landmark_longitude, '') AS DECIMAL(10,6)),
                        CAST(NULLIF(s.ai_primary_landmark_confidence, '') AS DECIMAL(6,4))
                    FROM unsplash_staging s
                    INNER JOIN photo p ON p.photo_id = s.photo_id
                    WHERE s.ai_primary_landmark_name IS NOT NULL AND s.ai_primary_landmark_name != '';
                """)
                conn.commit()
                print("[BRIDGE] Aux tables synced successfully!")
    except Exception as e:
        print(f"[BRIDGE-INFO] Aux table check skipped: {e}")


def fetch_clients_list(conn, cursor):
    """Fetches all users from the client table along with their parsed permissions."""
    try:
        cursor.execute("""
            SELECT client_id, username, full_name, email, phone, company,
                   permissions_json, CAST(created_at AS CHAR) AS created_at
            FROM client
            ORDER BY client_id ASC;
        """)
        rows = cursor.fetchall()
        for r in rows:
            raw_perm = r.get("permissions_json")
            if raw_perm:
                try:
                    r["permissions"] = json.loads(raw_perm) if isinstance(raw_perm, str) else raw_perm
                except Exception:
                    r["permissions"] = {"allowAll": True}
            else:
                r["permissions"] = {"allowAll": True}
        return rows
    except Exception as e:
        print(f"[BRIDGE-WARN] Could not fetch client list: {e}")
        return []


def fetch_photographers_list(conn, cursor):
    """Fetches all photographers from the photographer table along with their parsed CRUD permissions."""
    try:
        cursor.execute("""
            SELECT pg.photographer_id, pg.username, pg.first_name, pg.last_name, pg.permissions_json,
                   COUNT(p.photo_id) AS photo_count
            FROM photographer pg
            LEFT JOIN photo p ON p.photographer_id = pg.photographer_id
            GROUP BY pg.photographer_id, pg.username, pg.first_name, pg.last_name, pg.permissions_json
            ORDER BY photo_count DESC, pg.photographer_id ASC;
        """)
        rows = cursor.fetchall()
        for r in rows:
            raw_perm = r.get("permissions_json")
            if raw_perm:
                try:
                    r["permissions"] = json.loads(raw_perm) if isinstance(raw_perm, str) else raw_perm
                except Exception:
                    r["permissions"] = None
            else:
                r["permissions"] = None
        return rows
    except Exception as e:
        print(f"[BRIDGE-WARN] Could not fetch photographers list: {e}")
        return []


def fetch_photos_from_mysql(client_params=None, limit=DEFAULT_ROW_LIMIT):
    params = client_params or {}
    req_limit = params.get("limit", limit)
    safe_limit = max(1, min(int(req_limit or DEFAULT_ROW_LIMIT), 50000))

    conn, cfg = get_db_connection(params)
    print(f"\n[BRIDGE] Connecting to MySQL ({cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}) [Limit: {safe_limit}]...")
    cursor = conn.cursor(dictionary=True)

    # Ensure role & EXIF/Landmark lookup tables are ready
    ensure_role_and_aux_tables(conn, cursor)

    # 1. Total photos count in database
    cursor.execute("SELECT COUNT(*) AS total_count FROM photo;")
    total_photos = cursor.fetchone()["total_count"]

    # 2. Joined Photos Query (Optimized for 25,000 rows)
    query = f"""
        SELECT 
            p.photo_id,
            p.photographer_id,
            COALESCE(pg.username, 'creator') AS photographer_username,
            COALESCE(pg.first_name, 'Unsplash') AS photographer_first_name,
            COALESCE(pg.last_name, '') AS photographer_last_name,
            p.photo_url,
            p.image_url,
            p.description,
            p.ai_description,
            p.width,
            p.height,
            p.aspect_ratio,
            p.blur_hash,
            p.featured,
            CAST(p.submitted_at AS CHAR) AS submitted_at,
            e.camera_id,
            c.make AS exif_camera_make,
            c.model AS exif_camera_model,
            e.location_id,
            l.location_name AS photo_location_name,
            l.city AS photo_location_city,
            l.country AS photo_location_country,
            l.latitude AS photo_location_latitude,
            l.longitude AS photo_location_longitude,
            e.iso AS exif_iso,
            e.aperture_value AS exif_aperture_value,
            e.focal_length AS exif_focal_length,
            e.exposure_time AS exif_exposure_time,
            s.views AS stats_views,
            s.downloads AS stats_downloads,
            al.landmark_name AS ai_primary_landmark_name,
            al.confidence AS ai_primary_landmark_confidence,
            al.latitude AS ai_primary_landmark_latitude,
            al.longitude AS ai_primary_landmark_longitude
        FROM photo p
        LEFT JOIN photographer pg ON p.photographer_id = pg.photographer_id
        LEFT JOIN photo_exif e ON p.photo_id = e.photo_id
        LEFT JOIN camera c ON e.camera_id = c.camera_id
        LEFT JOIN location l ON e.location_id = l.location_id
        LEFT JOIN photo_stats s ON p.photo_id = s.photo_id
        LEFT JOIN ai_landmark al ON p.photo_id = al.photo_id
        LIMIT {safe_limit};
    """
    cursor.execute(query)
    photos = cursor.fetchall()

    clients = fetch_clients_list(conn, cursor)

    cursor.close()
    conn.close()

    return total_photos, photos, clients


def verify_user_in_mysql(payload):
    """
    Verifies User (client table) login:
      Input 1 (identifier): username OR email OR client_id OR full_name
      Input 2 (phone): phone
    """
    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor(dictionary=True)
    ensure_role_and_aux_tables(conn, cursor)

    identifier = str(payload.get("identifier") or "").strip().lstrip("@")
    phone = str(payload.get("phone") or "").strip()

    if not identifier or not phone:
        cursor.close()
        conn.close()
        return None, "Both Username/Email/ID and Phone Number are required."

    cursor.execute(
        """
        SELECT client_id, username, full_name, email, phone, company,
               permissions_json, CAST(created_at AS CHAR) AS created_at
        FROM client
        WHERE (
            CAST(client_id AS CHAR) = %s
            OR LOWER(COALESCE(username, '')) = LOWER(%s)
            OR LOWER(COALESCE(email, '')) = LOWER(%s)
            OR LOWER(COALESCE(full_name, '')) = LOWER(%s)
        )
        AND TRIM(COALESCE(phone, '')) = %s
        LIMIT 1;
        """,
        (identifier, identifier, identifier, identifier, phone)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return None, f"No User found in 'client' table matching '{identifier}' with phone '{phone}'."

    raw_perm = row.get("permissions_json")
    if raw_perm:
        try:
            row["permissions"] = json.loads(raw_perm) if isinstance(raw_perm, str) else raw_perm
        except Exception:
            row["permissions"] = {"allowAll": True}
    else:
        row["permissions"] = {"allowAll": True}

    return row, None


def verify_admin_in_mysql(payload):
    """
    Verifies Administrator (administrator table) login:
      Input 1 (identifier): username OR admin_id
      Input 2 (password): password (matches plain password_hash OR SHA-256 hash)
    """
    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor(dictionary=True)
    ensure_role_and_aux_tables(conn, cursor)

    identifier = str(payload.get("identifier") or "").strip().lstrip("@")
    password = str(payload.get("password") or "")

    if not identifier or not password:
        cursor.close()
        conn.close()
        return None, "Both Admin Username/ID and Password are required."

    sha256_hex = hashlib.sha256(password.encode("utf-8")).hexdigest()

    cursor.execute(
        """
        SELECT admin_id, username, full_name, role, CAST(created_at AS CHAR) AS created_at
        FROM administrator
        WHERE (
            CAST(admin_id AS CHAR) = %s
            OR LOWER(username) = LOWER(%s)
        )
        AND (
            password_hash = %s
            OR LOWER(password_hash) = LOWER(%s)
        )
        LIMIT 1;
        """,
        (identifier, identifier, password, sha256_hex)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return None, f"Invalid Administrator credentials for '{identifier}'."
    return row, None


def change_admin_password_in_mysql(payload):
    """Executes UPDATE administrator SET password_hash = ... WHERE admin_id = ..."""
    admin_id = payload.get("admin_id")
    username = str(payload.get("username") or "").strip()
    new_password = str(payload.get("new_password") or "")

    if not new_password:
        raise ValueError("New password cannot be empty.")

    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor()
    try:
        ensure_role_and_aux_tables(conn, cursor)
        if admin_id is not None and str(admin_id).strip() != "":
            cursor.execute(
                "UPDATE administrator SET password_hash = %s WHERE admin_id = %s;",
                (new_password, int(admin_id))
            )
        else:
            cursor.execute(
                "UPDATE administrator SET password_hash = %s WHERE username = %s;",
                (new_password, username)
            )
        conn.commit()
        affected = cursor.rowcount
        print(f"[ADMIN-PASS] Updated password for admin_id={admin_id} / username='{username}' (rows: {affected}).")
        return affected
    finally:
        cursor.close()
        conn.close()


def save_client_user_in_mysql(payload):
    """Creates or updates a User in the client table along with granular permissions_json."""
    u = payload.get("user") or {}
    is_edit = bool(payload.get("isEdit") or payload.get("isUpdate"))
    raw_id = u.get("client_id")
    username = str(u.get("username") or "").strip()
    full_name = str(u.get("full_name") or username or "Client User").strip()
    email = str(u.get("email") or "").strip()
    phone = str(u.get("phone") or "").strip()
    company = str(u.get("company") or "").strip()
    permissions = u.get("permissions") if isinstance(u.get("permissions"), dict) else {"allowAll": True}
    perm_json = json.dumps(permissions)

    if not phone:
        raise ValueError("Phone number is required for User login authentication.")

    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_role_and_aux_tables(conn, cursor)
        client_id = int(raw_id) if (raw_id is not None and str(raw_id).strip() != "") else None

        if is_edit and client_id is not None:
            cursor.execute(
                """
                UPDATE client
                SET username = %s,
                    full_name = %s,
                    email = %s,
                    phone = %s,
                    company = %s,
                    permissions_json = %s
                WHERE client_id = %s;
                """,
                (username, full_name, email, phone, company, perm_json, client_id)
            )
        else:
            if client_id is not None:
                cursor.execute(
                    """
                    INSERT INTO client (client_id, username, full_name, email, phone, company, permissions_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        username = VALUES(username),
                        full_name = VALUES(full_name),
                        email = VALUES(email),
                        phone = VALUES(phone),
                        company = VALUES(company),
                        permissions_json = VALUES(permissions_json);
                    """,
                    (client_id, username, full_name, email, phone, company, perm_json)
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO client (username, full_name, email, phone, company, permissions_json)
                    VALUES (%s, %s, %s, %s, %s, %s);
                    """,
                    (username, full_name, email, phone, company, perm_json)
                )
                client_id = cursor.lastrowid

        conn.commit()
        clients = fetch_clients_list(conn, cursor)
        print(f"[ADMIN-USER-SAVE] Saved client_id={client_id} ({full_name}) in MySQL.")
        return client_id, clients
    finally:
        cursor.close()
        conn.close()


def delete_client_user_in_mysql(payload):
    """Deletes a User from the client table in MySQL."""
    raw_id = payload.get("client_id")
    if raw_id is None or str(raw_id).strip() == "":
        raise ValueError("Missing client_id for User deletion.")
    client_id = int(raw_id)

    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor(dictionary=True)
    try:
        try:
            cursor.execute("DELETE FROM shoot WHERE client_id = %s;", (client_id,))
        except Exception:
            pass
        cursor.execute("DELETE FROM client WHERE client_id = %s;", (client_id,))
        conn.commit()
        clients = fetch_clients_list(conn, cursor)
        print(f"[ADMIN-USER-DELETE] Deleted client_id={client_id} from MySQL.")
        return clients
    finally:
        cursor.close()
        conn.close()


def verify_photographer_in_mysql(payload):
    """Verifies photographer login by username and photographer_id in MySQL."""
    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor(dictionary=True)

    username = str(payload.get("username") or "").strip().lstrip("@")
    raw_id = str(payload.get("photographer_id") or "").strip()

    try:
        pg_id = int(raw_id)
    except Exception:
        cursor.close()
        conn.close()
        return None, "Photographer User ID must be a valid number."

    ensure_role_and_aux_tables(conn, cursor)
    cursor.execute(
        """
        SELECT photographer_id, username, first_name, last_name, permissions_json
        FROM photographer
        WHERE photographer_id = %s AND LOWER(username) = LOWER(%s)
        LIMIT 1;
        """,
        (pg_id, username)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return None, f"No photographer found with Username '{username}' and User ID '{pg_id}'."
    raw_perm = row.get("permissions_json")
    if raw_perm:
        try:
            row["permissions"] = json.loads(raw_perm) if isinstance(raw_perm, str) else raw_perm
        except Exception:
            row["permissions"] = None
    else:
        row["permissions"] = None
    return row, None


def save_photographer_in_mysql(payload):
    """Creates or updates a Photographer and their 4-option CRUD permissions_json in MySQL."""
    pg = payload.get("photographer") or {}
    raw_id = pg.get("photographer_id")
    username = str(pg.get("username") or "").strip().lstrip("@")
    first_name = str(pg.get("first_name") or username or "Photographer").strip()
    last_name = str(pg.get("last_name") or "").strip()
    permissions = pg.get("permissions") if isinstance(pg.get("permissions"), dict) else None
    perm_json = json.dumps(permissions) if permissions is not None else None

    if not username:
        raise ValueError("Username is required for Photographer.")

    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_role_and_aux_tables(conn, cursor)
        pg_id = int(raw_id) if (raw_id is not None and str(raw_id).strip() != "") else None

        if pg_id is not None:
            cursor.execute("SELECT photographer_id FROM photographer WHERE photographer_id = %s LIMIT 1;", (pg_id,))
            exists = cursor.fetchone()
            if exists:
                cursor.execute(
                    """
                    UPDATE photographer
                    SET username = %s,
                        first_name = %s,
                        last_name = %s,
                        permissions_json = %s
                    WHERE photographer_id = %s;
                    """,
                    (username, first_name, last_name, perm_json, pg_id)
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO photographer (photographer_id, username, first_name, last_name, permissions_json)
                    VALUES (%s, %s, %s, %s, %s);
                    """,
                    (pg_id, username, first_name, last_name, perm_json)
                )
        else:
            cursor.execute("SELECT COALESCE(MAX(photographer_id), 100) + 1 AS next_id FROM photographer;")
            pg_id = int(cursor.fetchone()["next_id"])
            cursor.execute(
                """
                INSERT INTO photographer (photographer_id, username, first_name, last_name, permissions_json)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (pg_id, username, first_name, last_name, perm_json)
            )

        try:
            cursor.execute(
                """
                UPDATE unsplash_staging s
                INNER JOIN photo p ON p.photo_id = s.photo_id
                SET s.photographer_username = %s,
                    s.photographer_first_name = %s,
                    s.photographer_last_name = %s
                WHERE p.photographer_id = %s;
                """,
                (username, first_name, last_name, pg_id)
            )
        except Exception:
            pass

        conn.commit()
        pg_list = fetch_photographers_list(conn, cursor)
        print(f"[ADMIN-PG-SAVE] Saved photographer_id={pg_id} (@{username}) in MySQL.")
        return pg_id, pg_list
    finally:
        cursor.close()
        conn.close()


def delete_photographer_in_mysql(payload):
    """Deletes a Photographer and all their associated photos from MySQL."""
    raw_id = payload.get("photographer_id")
    username = str(payload.get("username") or "").strip().lstrip("@")
    if raw_id is None and not username:
        raise ValueError("Missing photographer_id or username for Photographer deletion.")

    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor(dictionary=True)
    try:
        pg_id = int(raw_id) if (raw_id is not None and str(raw_id).strip() != "") else None
        if pg_id is not None:
            cursor.execute("SELECT photo_id FROM photo WHERE photographer_id = %s;", (pg_id,))
        else:
            cursor.execute(
                "SELECT p.photo_id FROM photo p INNER JOIN photographer pg ON pg.photographer_id = p.photographer_id WHERE LOWER(pg.username) = LOWER(%s);",
                (username,)
            )
        photo_rows = cursor.fetchall()
        for r in photo_rows:
            pid = r["photo_id"]
            for child_table in ("photo_tag", "ai_landmark", "photo_stats", "photo_exif"):
                try:
                    cursor.execute(f"DELETE FROM {child_table} WHERE photo_id = %s;", (pid,))
                except Exception:
                    pass
            try:
                cursor.execute("DELETE FROM unsplash_staging WHERE photo_id = %s;", (pid,))
            except Exception:
                pass
            cursor.execute("DELETE FROM photo WHERE photo_id = %s;", (pid,))

        if pg_id is not None:
            cursor.execute("DELETE FROM photographer WHERE photographer_id = %s;", (pg_id,))
        else:
            cursor.execute("DELETE FROM photographer WHERE LOWER(username) = LOWER(%s);", (username,))

        conn.commit()
        pg_list = fetch_photographers_list(conn, cursor)
        print(f"[ADMIN-PG-DELETE] Deleted photographer_id={pg_id} (@{username}) and {len(photo_rows)} photo(s) from MySQL.")
        return pg_list
    finally:
        cursor.close()
        conn.close()


def delete_photo_in_mysql(payload):
    """CRUD DELETE: Deletes a photo by photo_id across child & parent tables in MySQL."""
    photo_id = str(payload.get("photo_id") or "").strip()
    if not photo_id:
        raise ValueError("Missing photo_id for DELETE operation.")

    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor()

    try:
        for child_table in ("photo_tag", "ai_landmark", "photo_stats", "photo_exif"):
            try:
                cursor.execute(f"DELETE FROM {child_table} WHERE photo_id = %s;", (photo_id,))
            except Exception:
                pass

        cursor.execute("DELETE FROM photo WHERE photo_id = %s;", (photo_id,))
        deleted_count = cursor.rowcount

        try:
            cursor.execute("DELETE FROM unsplash_staging WHERE photo_id = %s;", (photo_id,))
        except Exception:
            pass

        conn.commit()
        print(f"[CRUD-DELETE] Deleted photo_id='{photo_id}' from MySQL (affected rows: {deleted_count}).")
        return deleted_count
    finally:
        cursor.close()
        conn.close()


def update_photo_in_mysql(payload):
    """CRUD UPDATE: Updates structured & staging attributes for a photo in MySQL."""
    photo_id = str(payload.get("photo_id") or "").strip()
    u = payload.get("updates") or {}
    if not photo_id:
        raise ValueError("Missing photo_id for UPDATE operation.")

    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor(dictionary=True)

    try:
        pg_id = int(u.get("photographer_id") or 101)
        username = str(u.get("username") or u.get("photographer_username") or "creator").strip().lstrip("@")
        first_name = str(u.get("first_name") or u.get("photographer_first_name") or "Unsplash").strip()
        last_name = str(u.get("last_name") or u.get("photographer_last_name") or "").strip()

        make = str(u.get("make") or u.get("exif_camera_make") or "Canon").strip()
        model = str(u.get("model") or u.get("exif_camera_model") or "EOS").strip()
        focal_length = str(u.get("focal_length") or u.get("exif_focal_length") or "35mm").strip()
        exposure_time = str(u.get("exposure_time") or u.get("exif_exposure_time") or "1/250s").strip()
        iso = int(float(u.get("iso") or u.get("exif_iso") or 100))
        aperture = float(u.get("aperture_value") or u.get("exif_aperture_value") or 2.8)

        loc_name = str(u.get("location_name") or u.get("photo_location_name") or "Unknown").strip()
        city = str(u.get("city") or u.get("photo_location_city") or "Unknown").strip()
        country = str(u.get("country") or u.get("photo_location_country") or "").strip()
        lat = float(u.get("latitude") or u.get("photo_location_latitude") or 0.0)
        lon = float(u.get("longitude") or u.get("photo_location_longitude") or 0.0)

        width = int(float(u.get("width") or u.get("photo_width") or 6000))
        height = int(float(u.get("height") or u.get("photo_height") or 4000))
        aspect_ratio = float(u.get("aspect_ratio") or u.get("photo_aspect_ratio") or round(width / max(height, 1), 3))
        raw_feat = str(u.get("featured") if u.get("featured") is not None else u.get("photo_featured", 0)).lower().strip()
        featured = 1 if raw_feat in ("1", "true", "t", "featured", "yes") else 0
        blur_hash = str(u.get("blur_hash") or "LKO2?U%2Tw=w]~RBVZRi};RPxuwH").strip()
        description = str(u.get("description") or u.get("photo_description") or "").strip()
        ai_description = str(u.get("ai_description") or "").strip()
        photo_url = str(u.get("photo_url") or f"https://unsplash.com/photos/{photo_id}").strip()
        image_url = str(u.get("image_url") or u.get("photo_image_url") or "").strip()

        landmark_name = str(u.get("landmark_name") or u.get("ai_primary_landmark_name") or "None").strip()
        confidence = float(u.get("confidence") or u.get("ai_primary_landmark_confidence") or 0.0)
        landmark_lat = float(u.get("landmark_lat") or u.get("ai_primary_landmark_latitude") or 0.0)
        landmark_lon = float(u.get("landmark_lon") or u.get("ai_primary_landmark_longitude") or 0.0)

        cursor.execute(
            """
            UPDATE photographer
            SET first_name = %s, last_name = %s
            WHERE photographer_id = %s;
            """,
            (first_name, last_name, pg_id)
        )

        cursor.execute(
            "SELECT camera_id FROM camera WHERE make = %s AND model = %s LIMIT 1;",
            (make, model)
        )
        cam_row = cursor.fetchone()
        if cam_row:
            camera_id = cam_row["camera_id"]
        else:
            cursor.execute("INSERT INTO camera (make, model) VALUES (%s, %s);", (make, model))
            camera_id = cursor.lastrowid

        cursor.execute(
            "SELECT location_id FROM location WHERE location_name = %s AND city = %s AND country = %s LIMIT 1;",
            (loc_name, city, country)
        )
        loc_row = cursor.fetchone()
        if loc_row:
            location_id = loc_row["location_id"]
            cursor.execute(
                "UPDATE location SET latitude = %s, longitude = %s WHERE location_id = %s;",
                (lat, lon, location_id)
            )
        else:
            cursor.execute(
                "INSERT INTO location (location_name, city, country, latitude, longitude) VALUES (%s, %s, %s, %s, %s);",
                (loc_name, city, country, lat, lon)
            )
            location_id = cursor.lastrowid

        cursor.execute(
            """
            UPDATE photo
            SET photo_url = %s,
                image_url = %s,
                description = %s,
                ai_description = %s,
                width = %s,
                height = %s,
                aspect_ratio = %s,
                blur_hash = %s,
                featured = %s
            WHERE photo_id = %s;
            """,
            (photo_url, image_url, description, ai_description, width, height, aspect_ratio, blur_hash, featured, photo_id)
        )

        cursor.execute("SELECT photo_id FROM photo_exif WHERE photo_id = %s LIMIT 1;", (photo_id,))
        if cursor.fetchone():
            cursor.execute(
                """
                UPDATE photo_exif
                SET camera_id = %s,
                    location_id = %s,
                    iso = %s,
                    aperture_value = %s,
                    focal_length = %s,
                    exposure_time = %s
                WHERE photo_id = %s;
                """,
                (camera_id, location_id, iso, aperture, focal_length, exposure_time, photo_id)
            )
        else:
            cursor.execute(
                """
                INSERT INTO photo_exif (photo_id, camera_id, location_id, iso, aperture_value, focal_length, exposure_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (photo_id, camera_id, location_id, iso, aperture, focal_length, exposure_time)
            )

        cursor.execute("SELECT photo_id FROM ai_landmark WHERE photo_id = %s LIMIT 1;", (photo_id,))
        if cursor.fetchone():
            cursor.execute(
                """
                UPDATE ai_landmark
                SET landmark_name = %s,
                    latitude = %s,
                    longitude = %s,
                    confidence = %s
                WHERE photo_id = %s;
                """,
                (landmark_name, landmark_lat, landmark_lon, confidence, photo_id)
            )
        elif landmark_name and landmark_name.lower() != "none":
            cursor.execute(
                """
                INSERT INTO ai_landmark (photo_id, landmark_name, latitude, longitude, confidence)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (photo_id, landmark_name, landmark_lat, landmark_lon, confidence)
            )

        try:
            cursor.execute(
                """
                UPDATE unsplash_staging
                SET photo_url = %s,
                    photo_image_url = %s,
                    photo_featured = %s,
                    photo_width = %s,
                    photo_height = %s,
                    photo_aspect_ratio = %s,
                    photo_description = %s,
                    ai_description = %s,
                    blur_hash = %s,
                    photographer_username = %s,
                    photographer_first_name = %s,
                    photographer_last_name = %s,
                    photo_location_name = %s,
                    photo_location_city = %s,
                    photo_location_country = %s,
                    photo_location_latitude = %s,
                    photo_location_longitude = %s,
                    exif_camera_make = %s,
                    exif_camera_model = %s,
                    exif_iso = %s,
                    exif_aperture_value = %s,
                    exif_focal_length = %s,
                    exif_exposure_time = %s,
                    ai_primary_landmark_name = %s,
                    ai_primary_landmark_latitude = %s,
                    ai_primary_landmark_longitude = %s,
                    ai_primary_landmark_confidence = %s
                WHERE photo_id = %s;
                """,
                (
                    photo_url, image_url, "t" if featured == 1 else "f",
                    width, height, aspect_ratio, description, ai_description, blur_hash,
                    username, first_name, last_name, loc_name, city, country, lat, lon,
                    make, model, iso, aperture, focal_length, exposure_time,
                    landmark_name, landmark_lat, landmark_lon, confidence,
                    photo_id
                )
            )
        except Exception:
            pass

        conn.commit()
        print(f"[CRUD-UPDATE] Updated photo_id='{photo_id}' across MySQL tables.")
        return {"camera_id": camera_id, "location_id": location_id}
    finally:
        cursor.close()
        conn.close()


def add_photo_in_mysql(payload):
    """CRUD CREATE (INSERT): Inserts a new photo for the logged-in photographer into MySQL."""
    p = payload.get("photo") or {}
    photo_id = str(p.get("photo_id") or "").strip()
    if not photo_id:
        raise ValueError("Missing photo_id for INSERT operation.")

    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor(dictionary=True)

    try:
        pg_id = int(p.get("photographer_id") or 101)
        username = str(p.get("username") or "creator").strip().lstrip("@")
        first_name = str(p.get("first_name") or "Unsplash").strip()
        last_name = str(p.get("last_name") or "").strip()

        make = str(p.get("make") or "Canon").strip()
        model = str(p.get("model") or "EOS R5").strip()
        focal_length = str(p.get("focal_length") or "35mm").strip()
        exposure_time = str(p.get("exposure_time") or "1/250s").strip()
        iso = int(float(p.get("iso") or 100))
        aperture = float(p.get("aperture_value") or 2.8)

        loc_name = str(p.get("location_name") or "Studio").strip()
        city = str(p.get("city") or "Unknown").strip()
        country = str(p.get("country") or "").strip()
        lat = float(p.get("latitude") or 0.0)
        lon = float(p.get("longitude") or 0.0)

        width = int(float(p.get("width") or 6000))
        height = int(float(p.get("height") or 4000))
        aspect_ratio = float(p.get("aspect_ratio") or round(width / max(height, 1), 3))
        raw_feat = str(p.get("featured", 0)).lower().strip()
        featured = 1 if raw_feat in ("1", "true", "t", "featured", "yes") else 0
        submitted_at = str(p.get("submitted_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")).strip()
        blur_hash = str(p.get("blur_hash") or "LKO2?U%2Tw=w]~RBVZRi};RPxuwH").strip()
        description = str(p.get("description") or "").strip()
        ai_description = str(p.get("ai_description") or "").strip()
        photo_url = str(p.get("photo_url") or f"https://unsplash.com/photos/{photo_id}").strip()
        image_url = str(p.get("image_url") or "").strip()

        landmark_name = str(p.get("landmark_name") or "None").strip()
        confidence = float(p.get("confidence") or 0.0)
        landmark_lat = float(p.get("landmark_lat") or 0.0)
        landmark_lon = float(p.get("landmark_lon") or 0.0)

        cursor.execute("SELECT photographer_id FROM photographer WHERE photographer_id = %s LIMIT 1;", (pg_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT IGNORE INTO photographer (photographer_id, username, first_name, last_name) VALUES (%s, %s, %s, %s);",
                (pg_id, username, first_name, last_name)
            )

        cursor.execute("SELECT camera_id FROM camera WHERE make = %s AND model = %s LIMIT 1;", (make, model))
        cam_row = cursor.fetchone()
        if cam_row:
            camera_id = cam_row["camera_id"]
        else:
            cursor.execute("INSERT INTO camera (make, model) VALUES (%s, %s);", (make, model))
            camera_id = cursor.lastrowid

        cursor.execute(
            "SELECT location_id FROM location WHERE location_name = %s AND city = %s AND country = %s LIMIT 1;",
            (loc_name, city, country)
        )
        loc_row = cursor.fetchone()
        if loc_row:
            location_id = loc_row["location_id"]
        else:
            cursor.execute(
                "INSERT INTO location (location_name, city, country, latitude, longitude) VALUES (%s, %s, %s, %s, %s);",
                (loc_name, city, country, lat, lon)
            )
            location_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO photo (
                photo_id, photographer_id, photo_url, image_url,
                description, ai_description, width, height, aspect_ratio,
                blur_hash, featured, submitted_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (
                photo_id, pg_id, photo_url, image_url,
                description, ai_description, width, height, aspect_ratio,
                blur_hash, featured, submitted_at
            )
        )

        cursor.execute(
            """
            INSERT INTO photo_exif (
                photo_id, camera_id, location_id, iso, aperture_value, focal_length, exposure_time
            ) VALUES (%s, %s, %s, %s, %s, %s, %s);
            """,
            (photo_id, camera_id, location_id, iso, aperture, focal_length, exposure_time)
        )

        if landmark_name and landmark_name.lower() != "none":
            cursor.execute(
                """
                INSERT INTO ai_landmark (photo_id, landmark_name, latitude, longitude, confidence)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (photo_id, landmark_name, landmark_lat, landmark_lon, confidence)
            )

        try:
            cursor.execute(
                """
                INSERT INTO unsplash_staging (
                    photo_id, photo_url, photo_image_url, photo_submitted_at, photo_featured,
                    photo_width, photo_height, photo_aspect_ratio, photo_description, ai_description, blur_hash,
                    photographer_username, photographer_first_name, photographer_last_name,
                    photo_location_name, photo_location_city, photo_location_country,
                    photo_location_latitude, photo_location_longitude,
                    exif_camera_make, exif_camera_model, exif_iso, exif_aperture_value,
                    exif_focal_length, exif_exposure_time,
                    ai_primary_landmark_name, ai_primary_landmark_latitude,
                    ai_primary_landmark_longitude, ai_primary_landmark_confidence
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s
                );
                """,
                (
                    photo_id, photo_url, image_url, submitted_at, "t" if featured == 1 else "f",
                    width, height, aspect_ratio, description, ai_description, blur_hash,
                    username, first_name, last_name,
                    loc_name, city, country, lat, lon,
                    make, model, iso, aperture, focal_length, exposure_time,
                    landmark_name, landmark_lat, landmark_lon, confidence
                )
            )
        except Exception:
            pass

        conn.commit()
        print(f"[CRUD-INSERT] Added new photo_id='{photo_id}' for photographer='{username}' (ID: {pg_id}) into MySQL.")
        return {"camera_id": camera_id, "location_id": location_id}
    finally:
        cursor.close()
        conn.close()



def execute_admin_db_sql_in_mysql(payload):
    """Executes an Admin SQL statement (SELECT, INSERT, UPDATE, DELETE, ALTER TABLE) in MySQL."""
    conn, _ = get_db_connection(payload.get("dbConfig"))
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_role_and_aux_tables(conn, cursor)
        sql_text = str(payload.get("sql") or "").strip()
        if not sql_text:
            raise ValueError("Empty SQL query provided.")

        statements = [s.strip() for s in sql_text.split(";") if s.strip()]
        last_rows = []
        last_cols = []
        affected_total = 0

        for stmt in statements:
            cursor.execute(stmt)
            if cursor.with_rows:
                rows = cursor.fetchall()
                last_rows = rows
                last_cols = list(rows[0].keys()) if rows else [d[0] for d in (cursor.description or [])]
            else:
                affected_total += max(0, cursor.rowcount if cursor.rowcount is not None else 0)

        conn.commit()
        print(f"[ADMIN-DB-SQL] Executed {len(statements)} statement(s). Affected rows: {affected_total}")
        return {
            "rows": last_rows,
            "columns": last_cols,
            "affected_rows": affected_total
        }
    finally:
        cursor.close()
        conn.close()


class FastThreadingHTTPServer(ThreadingHTTPServer):
    """Daemon-threaded HTTPServer that releases its socket and exits immediately on Ctrl+C."""
    daemon_threads = True
    allow_reuse_address = True


class BridgeRequestHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Connection", "close")

    def _send_json(self, status_code, payload):
        json_bytes = json.dumps(payload, default=json_serializer).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(json_bytes)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json_bytes)

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body_data = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(body_data.decode("utf-8")) if body_data else {}
        except Exception:
            payload = {}

        if self.path.startswith("/api/shutdown"):
            self._send_json(200, {"status": "success", "message": "Bridge server stopping immediately."})
            threading.Thread(
                target=lambda: (time.sleep(0.1), stop_server_immediately("Stopped via Webpage /api/shutdown")),
                daemon=True
            ).start()
            return

        if self.path.startswith("/api/connect"):
            try:
                req_limit = int(payload.get("limit", DEFAULT_ROW_LIMIT))
                total_photos, photos, clients = fetch_photos_from_mysql(payload, limit=req_limit)
                print(f"[SUCCESS] Handshake successful! Loaded {len(photos)} photos & {len(clients)} client users (Total in DB: {total_photos}).")
                self._send_json(200, {
                    "status": "success",
                    "message": f"Connected to MySQL. Loaded {len(photos)} photos.",
                    "total_photos_in_db": total_photos,
                    "table_count": 13,
                    "photos": photos,
                    "clients": clients
                })
            except mysql.connector.Error as err:
                print(f"[ERROR] MySQL Query Failed: {err}")
                self._send_json(500, {
                    "status": "error",
                    "code": err.errno,
                    "message": f"MySQL Error {err.errno}: {err.msg}"
                })
            except Exception as e:
                print(f"[ERROR] Unexpected Server Error: {e}")
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/user/login"):
            try:
                user_row, err_msg = verify_user_in_mysql(payload)
                if err_msg:
                    self._send_json(404, {"status": "error", "message": err_msg})
                else:
                    self._send_json(200, {"status": "success", "user": user_row})
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/admin/login"):
            try:
                admin_row, err_msg = verify_admin_in_mysql(payload)
                if err_msg:
                    self._send_json(401, {"status": "error", "message": err_msg})
                else:
                    self._send_json(200, {"status": "success", "admin": admin_row})
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/admin/change-password"):
            try:
                affected = change_admin_password_in_mysql(payload)
                self._send_json(200, {
                    "status": "success",
                    "message": "Administrator password updated in MySQL.",
                    "affected_rows": affected
                })
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/admin/users/list"):
            try:
                conn, _ = get_db_connection(payload.get("dbConfig"))
                cursor = conn.cursor(dictionary=True)
                ensure_role_and_aux_tables(conn, cursor)
                clients = fetch_clients_list(conn, cursor)
                cursor.close()
                conn.close()
                self._send_json(200, {"status": "success", "clients": clients, "users": clients})
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/admin/users/save"):
            try:
                cid, clients = save_client_user_in_mysql(payload)
                self._send_json(200, {
                    "status": "success",
                    "client_id": cid,
                    "clients": clients,
                    "users": clients
                })
            except Exception as e:
                print(f"[ADMIN-USER-SAVE-ERR] {e}")
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/admin/users/delete"):
            try:
                clients = delete_client_user_in_mysql(payload)
                self._send_json(200, {
                    "status": "success",
                    "clients": clients,
                    "users": clients
                })
            except Exception as e:
                print(f"[ADMIN-USER-DEL-ERR] {e}")
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/admin/photographers/list"):
            try:
                conn, _ = get_db_connection(payload.get("dbConfig"))
                cursor = conn.cursor(dictionary=True)
                ensure_role_and_aux_tables(conn, cursor)
                pg_list = fetch_photographers_list(conn, cursor)
                cursor.close()
                conn.close()
                self._send_json(200, {"status": "success", "photographers": pg_list})
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/admin/photographers/save"):
            try:
                pg_id, pg_list = save_photographer_in_mysql(payload)
                self._send_json(200, {
                    "status": "success",
                    "photographer_id": pg_id,
                    "photographers": pg_list
                })
            except Exception as e:
                print(f"[ADMIN-PG-SAVE-ERR] {e}")
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/admin/photographers/delete"):
            try:
                pg_list = delete_photographer_in_mysql(payload)
                self._send_json(200, {
                    "status": "success",
                    "photographers": pg_list
                })
            except Exception as e:
                print(f"[ADMIN-PG-DEL-ERR] {e}")
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/admin/db/execute-sql"):
            try:
                res = execute_admin_db_sql_in_mysql(payload)
                self._send_json(200, {
                    "status": "success",
                    **res
                })
            except mysql.connector.Error as err:
                print(f"[ADMIN-DB-SQL-ERR] MySQL Error {err.errno}: {err.msg}")
                self._send_json(400, {
                    "status": "error",
                    "code": err.errno,
                    "message": f"ERROR {err.errno} ({err.sqlstate or 'HY000'}): {err.msg}"
                })
            except Exception as e:
                print(f"[ADMIN-DB-SQL-ERR] {e}")
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/photographer/login"):
            try:
                pg_row, err_msg = verify_photographer_in_mysql(payload)
                if err_msg:
                    self._send_json(404, {"status": "error", "message": err_msg})
                else:
                    self._send_json(200, {"status": "success", "photographer": pg_row})
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/photo/delete"):
            try:
                deleted_count = delete_photo_in_mysql(payload)
                self._send_json(200, {
                    "status": "success",
                    "message": f"Photo '{payload.get('photo_id')}' deleted from MySQL database.",
                    "deleted_count": deleted_count
                })
            except Exception as e:
                print(f"[CRUD-DELETE-ERR] {e}")
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/photo/update"):
            try:
                meta = update_photo_in_mysql(payload)
                self._send_json(200, {
                    "status": "success",
                    "message": f"Photo '{payload.get('photo_id')}' updated in MySQL database.",
                    **meta
                })
            except Exception as e:
                print(f"[CRUD-UPDATE-ERR] {e}")
                self._send_json(500, {"status": "error", "message": str(e)})

        elif self.path.startswith("/api/photo/add"):
            try:
                meta = add_photo_in_mysql(payload)
                self._send_json(200, {
                    "status": "success",
                    "message": "New photo inserted into MySQL database.",
                    **meta
                })
            except Exception as e:
                print(f"[CRUD-ADD-ERR] {e}")
                self._send_json(500, {"status": "error", "message": str(e)})

        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/shutdown"):
            self._send_json(200, {"status": "success", "message": "Bridge server stopping immediately."})
            threading.Thread(
                target=lambda: (time.sleep(0.1), stop_server_immediately("Stopped via GET /api/shutdown")),
                daemon=True
            ).start()
            return

        if self.path.startswith("/api/connect") or self.path.startswith("/api/photos"):
            try:
                total_photos, photos, clients = fetch_photos_from_mysql(None, limit=DEFAULT_ROW_LIMIT)
                self._send_json(200, {
                    "status": "success",
                    "total_photos_in_db": total_photos,
                    "photos": photos,
                    "clients": clients
                })
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(b"<h1>MySQL Bridge Server is Running on Port 5000 (Limit: 25,000 + Role Auth + Admin CRUD)!</h1>")

    def log_message(self, format, *args):
        print(f"[HTTP] {self.command} {self.path} - {args[1] if len(args) > 1 else ''}")


def _terminal_command_listener():
    """Allows typing 'q', 'stop', or 'exit' + Enter in terminal to stop instantly."""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            cmd = line.strip().lower()
            if cmd in ("q", "quit", "stop", "exit"):
                stop_server_immediately(f"Terminal command '{cmd}' received")
        except Exception:
            break


def run_server():
    global _SERVER_INSTANCE

    # Register instant signal handlers for Ctrl+C (SIGINT) and Ctrl+Break (SIGBREAK on Windows)
    signal.signal(signal.SIGINT, lambda sig, frame: stop_server_immediately("Ctrl+C (SIGINT) pressed"))
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda sig, frame: stop_server_immediately("Ctrl+Break pressed"))

    server_address = ("127.0.0.1", 5000)
    httpd = FastThreadingHTTPServer(server_address, BridgeRequestHandler)
    _SERVER_INSTANCE = httpd

    # Run HTTP server in a daemon thread so main thread wakes up every 0.1s to catch Ctrl+C on Windows
    server_thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    server_thread.start()

    # Also listen for 'q' or 'stop' + Enter in terminal
    input_thread = threading.Thread(target=_terminal_command_listener, daemon=True)
    input_thread.start()

    print("=" * 68)
    print("  PHOTOGRAPHY STUDIO DBMS - LOCALHOST PYTHON BRIDGE SERVER")
    print("  Ready on http://localhost:5000 (Max Rows: 25,000 + Role Auth + CRUD)")
    print("  To STOP instantly: Press Ctrl+C  OR  type 'q' + Enter in terminal")
    print("                     OR click 'Stop Server' in Webpage Settings!")
    print("=" * 68)

    try:
        while server_thread.is_alive():
            time.sleep(0.1)
    except KeyboardInterrupt:
        stop_server_immediately("KeyboardInterrupt (Ctrl+C)")


if __name__ == "__main__":
    run_server()