
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

    create database geonames;
    create extension postgis;

Load the data file in

    create table geonames ( id integer, name text, lat float8, lon float8, type text, state text );
    \copy geonames (id, name, lat, lon, type, state)
        from program 'unzip -p US.zip US.txt | cut -f1,2,5,6,8,10' 
        with ( 
            format csv,
            delimiter E'\t',
            header false,
            encoding 'latin1'
            );

Add geometry and text search columns, populate and index them

    alter table geonames add column geom geometry(point, 4326);
    alter table geonames add column ts tsvector;
    update geonames set 
        geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326),
        ts = to_tsvector('english', name);
    vacuum full geonames;
    create index geonames_geom_x on geonames using gist (geom);
    create index geonames_ts_x on geonames using gin (ts);
    analyze geonames;

Make the autocomplete lookup table:

    create table geonames_stats as 
        select count(*) as ndoc, 
        unnest(regexp_split_to_array(lower(trim(name)), E'[^a-zA-Z]')) as word 
        from geonames group by 2;
    create index geonames_stats_word_x on geonames_stats (word text_pattern_ops);
    analyze geonames_stats;


# Address Data Setup




# Running the Server

    source venv/bin/activate
    python address-lookup.py

or

    source venv/bin/activate
    python geonames-lookup.py

and

    open geonames-lookup.html
    open address-lookup.html