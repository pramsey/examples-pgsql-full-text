
# Python Setup

The address server requires a database connection, so set up a virtual environment and then install the `psycopg2` driver using `pip`.

    cd address-lookup-mvt
    virtualenv --python python3 venv
    source venv/bin/activate
    pip install -r requirements.txt


# Geonames Data Setup

Download the data from GeoNames

    wget http://download.geonames.org/export/dump/US.zip

Prepare the database with PostGIS

    CREATE DATABASE geonames;
    CREATE EXTENSION postgis;

Load the data file in

    CREATE TABLE geonames ( id integer, name text, lat float8, lon float8, type text, state text );
    \copy geonames (id, name, lat, lon, type, state)
        FROM PROGRAM 'unzip -p US.zip US.txt | cut -f1,2,5,6,8,10' 
        WITH ( 
            format csv,
            delimiter E'\t',
            header false,
            encoding 'latin1'
            );

Add geometry and text search columns, populate and index them

    ALTER TABLE geonames ADD COLUMN geom geometry(point, 4326);
    ALTER TABLE geonames ADD COLUMN ts tsvector;
    UPDATE geonames SET 
        geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326),
        ts = to_tsvector('english', name);
    VACUUM FULL geonames;
    CREATE INDEX geonames_geom_x on geonames using gist (geom);
    CREATE INDEX geonames_ts_x on geonames using gin (ts);
    ANALYZE geonames;

Make the autocomplete lookup table:

    CREATE TABLE geonames_stats as 
        select count(*) as ndoc, 
        unnest(regexp_split_to_array(lower(trim(name)), E'[^a-zA-Z]')) as word 
        from geonames group by 2;
    CREATE INDEX geonames_stats_word_x on geonames_stats (word text_pattern_ops);
    ANALYZE geonames_stats;


# Address Data Setup

    wget --output-file=santa_cruz_parcels.zip "https://data.sccgov.org/api/geospatial/6p99-rtwk?method=export&format=Shapefile"

    createdb santa_cruz
    psql -d santa_cruz -c 'create extension postgis'
    unzip santa_cruz_parcels.zip
    shp2pgsql -s 4329 -D geo_export_de713ab2-5ed6-44a6-b88b-9b91ea232f66 parcels | psql -d santa_cruz

    ALTER TABLE parcels RENAME COLUMN situs_city     to city;
    ALTER TABLE parcels RENAME COLUMN situs_hous     to house;
    ALTER TABLE parcels RENAME COLUMN situs_hous__11 to house_suffix;
    ALTER TABLE parcels RENAME COLUMN situs_stat     to state;
    ALTER TABLE parcels RENAME COLUMN situs_stre     to street_prefix;
    ALTER TABLE parcels RENAME COLUMN situs_stre__14 to street_name;
    ALTER TABLE parcels RENAME COLUMN situs_stre__15 to street_type;
    ALTER TABLE parcels RENAME COLUMN situs_unit     to unit;
    ALTER TABLE parcels RENAME COLUMN situs_zip_     to zip;
    ALTER TABLE parcels RENAME COLUMN tax_rate_a     to tax_rate_area;
    ALTER TABLE parcels DROP COLUMN shape_area;
    ALTER TABLE parcels DROP COLUMN shape_leng;
    ALTER TABLE parcels DROP COLUMN reserved1;
    ALTER TABLE parcels DROP COLUMN reserved2;
    ALTER TABLE parcels DROP COLUMN reserved3;

    -- https://github.com/pramsey/pgsql-addressing-dictionary
    CREATE EXTENSION addressing_dictionary; 

    ALTER TABLE parcels ADD COLUMN ts tsvector;
    UPDATE parcels SET ts = 
        to_tsvector('addressing_en',
            concat_ws(', ', 
                concat_ws(' ', house, house_suffix, street_prefix, street_name, street_type),
                case when unit is null then null else 'UNIT '||unit end,
                city, state));
    VACUUM FULL parcels;
    CREATE INDEX parcels_ts_x ON parcels USING GIN (ts);
    CREATE INDEX parcels_geom_x ON parcels USING GIST (geom);
    ANALYZE parcels;


# Running the Server

    source venv/bin/activate
    python address-lookup.py

or

    source venv/bin/activate
    python geonames-lookup.py

and

    open geonames-lookup.html
    open address-lookup.html