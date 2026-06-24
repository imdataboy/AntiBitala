PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    company_id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    normalized_name TEXT,
    aliases TEXT,
    city TEXT,
    region TEXT,
    country TEXT DEFAULT 'Morocco',
    sector_primary TEXT,
    sector_secondary TEXT,
    company_type TEXT,
    website TEXT,
    domain TEXT,
    career_page TEXT,
    contact_page TEXT,
    public_email TEXT,
    phone TEXT,
    address TEXT,
    latitude REAL,
    longitude REAL,
    trust_score INTEGER DEFAULT 0,
    job_relevance_score INTEGER DEFAULT 0,
    source_count INTEGER DEFAULT 0,
    first_seen_date TEXT,
    last_seen_date TEXT,
    last_checked_date TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_sources (
    source_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT UNIQUE NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    country TEXT DEFAULT 'Morocco',
    region TEXT,
    city TEXT,
    sector TEXT,
    coverage_scope TEXT NOT NULL,
    reliability_level TEXT NOT NULL,
    access_method TEXT,
    base_url TEXT,
    enabled INTEGER DEFAULT 1,
    update_frequency TEXT DEFAULT 'quarterly',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_sources (
    source_id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT,
    source_url TEXT NOT NULL,
    source_region TEXT,
    coverage_scope TEXT,
    source_reliability TEXT,
    date_collected TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS company_contacts (
    contact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    contact_type TEXT NOT NULL,
    contact_value TEXT NOT NULL,
    contact_source_url TEXT,
    confidence_score INTEGER DEFAULT 0,
    last_checked_date TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS zones (
    zone_id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_name TEXT NOT NULL,
    region TEXT,
    city TEXT,
    zone_type TEXT,
    operator TEXT,
    source_url TEXT,
    latitude REAL,
    longitude REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_zones (
    company_id INTEGER NOT NULL,
    zone_id INTEGER NOT NULL,
    source_url TEXT,
    confidence_score INTEGER DEFAULT 0,
    PRIMARY KEY (company_id, zone_id),
    FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
    FOREIGN KEY (zone_id) REFERENCES zones(zone_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS update_log (
    update_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    update_date TEXT DEFAULT CURRENT_TIMESTAMP,
    records_added INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_removed_or_not_seen INTEGER DEFAULT 0,
    errors TEXT,
    notes TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS companies_fts USING fts5(
    company_name,
    city,
    region,
    sector_primary,
    sector_secondary,
    company_type,
    content='companies',
    content_rowid='company_id'
);

CREATE INDEX IF NOT EXISTS idx_companies_city ON companies(city);
CREATE INDEX IF NOT EXISTS idx_companies_region ON companies(region);
CREATE INDEX IF NOT EXISTS idx_companies_sector ON companies(sector_primary);
CREATE INDEX IF NOT EXISTS idx_companies_trust ON companies(trust_score);
CREATE INDEX IF NOT EXISTS idx_companies_job_relevance ON companies(job_relevance_score);
CREATE INDEX IF NOT EXISTS idx_sources_company_id ON company_sources(company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_company_id ON company_contacts(company_id);

CREATE INDEX IF NOT EXISTS idx_data_sources_key ON data_sources(source_key);
CREATE INDEX IF NOT EXISTS idx_data_sources_type ON data_sources(source_type);
CREATE INDEX IF NOT EXISTS idx_data_sources_region ON data_sources(region);
CREATE INDEX IF NOT EXISTS idx_data_sources_enabled ON data_sources(enabled);
