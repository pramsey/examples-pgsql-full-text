# System Setup

## Database Preparation

Prepare the database with PostGIS and the `postgisftw` schema.
```bash
createdb postgisftw
psql -U postgres -d postgisftw -c 'CREATE EXTENSION postgis'
psql -U username
```
```sql
CREATE SCHEMA IF NOT EXISTS postgisftw;
```

## Run Web Services

* [pg_featureserv](https://github.com/CrunchyData/pg_featureserv)
* [pg_tileserv](https://github.com/CrunchyData/pg_tileserv)

```bash
export DATABASE_URL=postgresql://username:password@localhost/postgisftw
./pg_featureserv
```

```bash
export DATABASE_URL=postgresql://username:password@localhost/postgisftw
./pg_tileserv
```

# Geonames Heat Map Demo

## Geonames Data Setup

Download the data from GeoNames
```bash
wget http://download.geonames.org/export/dump/US.zip
```
Load the data file in

```sql
CREATE TABLE geonames (
    id integer, 
    name text, 
    lat float8, 
    lon float8, 
    type text, 
    state text);

\copy geonames (id, name, lat, lon, type, state) FROM PROGRAM 'unzip -p US.zip US.txt | cut -f1,2,5,6,8,10' WITH ( format csv, delimiter E'\t', header false, encoding 'latin1' );
```

Add geometry and text search columns, populate and index them

```sql
ALTER TABLE geonames ADD COLUMN geom geometry(point, 4326);
ALTER TABLE geonames ADD COLUMN ts tsvector;

UPDATE geonames SET 
    geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326),
    ts = to_tsvector('english', name);

VACUUM (ANALYZE, FULL) geonames;

CREATE INDEX geonames_geom_x on geonames using gist (geom);
CREATE INDEX geonames_ts_x on geonames using gin (ts);
```

Make the autocomplete lookup table:

```sql
CREATE TABLE geonames_stats AS 
    SELECT count(*) AS ndoc, 
    unnest(regexp_split_to_array(lower(trim(name)), E'[^a-zA-Z]')) AS word 
    FROM geonames GROUP BY 2;

CREATE INDEX geonames_stats_word_x 
    ON geonames_stats (word text_pattern_ops);

ANALYZE geonames_stats;
```

## Geonames Web Services Setup

Add a function to expose the geonames text search query via `pg_featureserv`. Note that the feature server only exposes functions defined in the `postgisftw` schema:

```sql
DROP FUNCTION IF EXISTS postgisftw.geonames_query;

CREATE OR REPLACE FUNCTION postgisftw.geonames_query(
    search_word text DEFAULT 'beach')
RETURNS TABLE(name text, kind text, lon float8, lat float8)
AS $$
BEGIN
    RETURN QUERY
        SELECT 
            g.name, g.type, 
            ST_X(g.geom) as lon,
            ST_Y(g.geom) as lat
        FROM geonames g
        WHERE ts @@ plainto_tsquery('english', search_word);
END;
$$
LANGUAGE 'plpgsql'
PARALLEL SAFE
STABLE
STRICT;
```

Add a function to expose the geonames form autofill query via [pg_featureserv](https://github.com/CrunchyData/pg_featureserv):

```sql
DROP FUNCTION IF EXISTS postgisftw.geonames_stats_query;
CREATE OR REPLACE FUNCTION postgisftw.geonames_stats_query(
    search_word text DEFAULT 'bea')
RETURNS TABLE(value text, ndoc bigint)
AS $$
BEGIN
    RETURN QUERY
        SELECT g.word as value, g.ndoc
        FROM geonames_stats g
        WHERE word LIKE search_word || '%'
        ORDER BY ndoc DESC
        LIMIT 15;
END;
$$
LANGUAGE 'plpgsql'
PARALLEL SAFE
STABLE
STRICT;
```

Test that the functions are exposed and operating:

* http://localhost:9000/functions/geonames_query/items.json?search_word=cougar
* http://localhost:9000/functions/geonames_stats_query/items.json?search_word=coug

## Geonames Web Interface

Load up the web page at [geonames-lookup.html](geonames-lookup.html)


# Address Autocomplete Demo

## Address Data Setup

Download the shape file

```bash
curl "https://data.sccgov.org/api/geospatial/6p99-rtwk?method=export&format=Shapefile" > santa_cruz_parcels.zip 
unzip santa_cruz_parcels.zip
```

Load shape file (shp2pgsql):

```bash
# using shp2pgsql
shp2pgsql -s 4329 -D geo_export_*.shp parcels | psql -d postgisftw
# or using ogr2ogr
ogr2ogr -append -f "PostgreSQL" PG:"dbname=postgisftw" geo_export_*.shp -nln parcels -lco GEOMETRY_NAME=geom
```

Fix the column names screwed up by the shape file
```sql
ALTER TABLE parcels RENAME COLUMN situs_city     to city;
ALTER TABLE parcels RENAME COLUMN situs_hous     to house;
ALTER TABLE parcels RENAME COLUMN situs_ho_2     to house_suffix;
ALTER TABLE parcels RENAME COLUMN situs_stat     to state;
ALTER TABLE parcels RENAME COLUMN situs_stre     to street_prefix;
ALTER TABLE parcels RENAME COLUMN situs_st_2     to street_name;
ALTER TABLE parcels RENAME COLUMN situs_st_3     to street_type;
ALTER TABLE parcels RENAME COLUMN situs_unit     to unit;
ALTER TABLE parcels RENAME COLUMN situs_zip_     to zip;
ALTER TABLE parcels RENAME COLUMN tax_rate_a     to tax_rate_area;
ALTER TABLE parcels DROP COLUMN shape_area;
ALTER TABLE parcels DROP COLUMN shape_leng;
ALTER TABLE parcels DROP COLUMN reserved1;
ALTER TABLE parcels DROP COLUMN reserved2;
ALTER TABLE parcels DROP COLUMN reserved3;
```
Install the addressing dictionary for better full-text search on address strings
```sql
-- https://github.com/pramsey/pgsql-addressing-dictionary
CREATE EXTENSION addressing_dictionary; 
```
Create a full-text address string, then parse it into the `ts` column
```sql
ALTER TABLE parcels ADD COLUMN ts tsvector;

UPDATE parcels SET ts = 
    to_tsvector('addressing_en',
        concat_ws(', ', 
            concat_ws(' ', house, house_suffix, street_prefix, street_name, street_type),
            CASE WHEN unit IS NULL THEN NULL ELSE 'UNIT '||unit END,
            city, state));

VACUUM (ANALYZE, FULL) parcels;

CREATE INDEX parcels_ts_x ON parcels USING GIN (ts);
CREATE INDEX parcels_geom_x ON parcels USING GIST (geom);
```

## Address Query Functions

```sql
CREATE OR REPLACE FUNCTION to_tsquery_partial(text)
RETURNS tsquery 
AS $$
BEGIN
  RETURN to_tsquery('simple',
             array_to_string(
               regexp_split_to_array(
                 trim($1),E'\\s+'),' & ') 
             || CASE WHEN $1 ~ ' $' THEN '' ELSE ':*' END
           );
END;
$$ 
LANGUAGE 'plpgsql'
PARALLEL SAFE
IMMUTABLE
STRICT;
```

```sql
DROP FUNCTION IF EXISTS postgisftw.address_query;
CREATE OR REPLACE FUNCTION postgisftw.address_query(
    partialstr text DEFAULT '')
RETURNS TABLE(gid integer, value text, rank real, geom geometry)
AS $$
BEGIN
    RETURN QUERY
        SELECT
          p.gid AS id,
          initcap(concat_ws(', ', concat_ws(' ', 
            p.house, p.street_prefix, p.street_name, p.street_type), p.city)) AS value,
          ts_rank_cd(p.ts, query) AS rank,
          p.geom
        FROM parcels p,
             to_tsquery_partial(partialstr) AS query
        WHERE ts @@ query
        ORDER BY rank DESC, house::integer
        LIMIT 15;
END;
$$
LANGUAGE 'plpgsql'
PARALLEL SAFE
STABLE
STRICT;
```

Test the web service:

* http://localhost:9000/functions/address_query/items.json?partialstr=1234

## Address Autocomplete Web Interface

Load up the web page at [address-lookup.html](address-lookup.html)

