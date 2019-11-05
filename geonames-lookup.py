import http.server
from urllib.parse import urlparse, parse_qs
import socketserver
import re
import psycopg2
import json

# Database to connect to
DATABASE = {
    'user':     'pramsey',
    'password': 'password',
    'host':     'localhost',
    'port':     '5432',
    'database': 'tiger'
    }

# HTTP server information
HOST = 'localhost'
PORT = 8081


########################################################################
# alter table geonames add column ts tsvector;
# update geonames set ts = to_tsvector('english', name);
# create index geonames_ts_x on geonames using gin (ts);
# select count(*) from geonames;
# create table geonames_stats as 
#    select count(*) as ndoc, 
#      unnest(regexp_split_to_array(lower(trim(name)), E'[^a-zA-Z]')) as word 
#    from geonames group by 2;
# create index geonames_stats_word_x on geonames_stats (word text_pattern_ops)
########################################################################

class GeonamesRequestHandler(http.server.BaseHTTPRequestHandler):

    DATABASE_CONNECTION = None

    # Generate a SQL query to pull names for heat map
    def generateSqlName(self, namestr):
        if not namestr:
            return None
        sql_tmpl = """
            WITH names AS (
                SELECT name, kind, st_x(geom) AS x, st_y(geom) AS y
                FROM geonames
                WHERE ts @@ plainto_tsquery('english', '{}')
            )
            SELECT json_agg(row_to_json(names.*))::text AS json
            FROM names
            ORDER BY random()
            LIMIT 10000
        """
        return sql_tmpl.format(namestr)


    # Generate a SQL query to pull potential names for autocomplete  
    def generateSqlTerm(self, wordstr):
        if not wordstr:
            return None
        sql_tmpl = """
            WITH words AS (
                SELECT word as value, ndoc
                FROM geonames_stats
                WHERE word LIKE '{}%%'
                ORDER BY ndoc DESC
                LIMIT 15
            )
            SELECT json_agg(row_to_json(words.*))::text AS json
            FROM words
        """
        return sql_tmpl.format(wordstr)


    # Run query SQL and return error on failure conditions
    def executeSql(self, sql):
        # Make and hold connection to database
        if not self.DATABASE_CONNECTION:
            try:
                self.DATABASE_CONNECTION = psycopg2.connect(**DATABASE)
            except (Exception, psycopg2.Error) as error:
                self.send_error(500, "cannot connect: %s" % (str(DATABASE)))
                return None

        # Query for result
        with self.DATABASE_CONNECTION.cursor() as cur:
            cur.execute(sql)
            if not cur:
                self.send_error(404, "sql query failed: %s" % (sql))
                return None
            return cur.fetchone()[0]

        return None


    # Handle HTTP GET requests
    def do_GET(self):

        # Read the "term" CGI variable
        query_components = parse_qs(urlparse(self.path).query)

        if "name" not in query_components and "term" not in query_components:
            self.send_error(400, "invalid query: %s" % (str(query_components)))
            return

        # Generate appropriate SQL for query mode 
        if "name" in query_components:
            q = query_components["name"][0]
            sql = self.generateSqlName(q)
        elif "term" in query_components:
            q = query_components["term"][0]
            sql = self.generateSqlTerm(q)

        self.log_message("sql: %s" % (sql))

        result = self.executeSql(sql)
        # self.log_message("result: %s" % (result))
        if not result:
            result = '[]'
        
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-type", "text/json")
        self.end_headers()
        self.wfile.write(result.encode('utf8'))


########################################################################

with http.server.HTTPServer((HOST, PORT), GeonamesRequestHandler) as server:
    try:
        print("serving at port", PORT)
        server.serve_forever()
    except KeyboardInterrupt:
        if self.DATABASE_CONNECTION:
            self.DATABASE_CONNECTION.close()
        print('^C received, shutting down server')
        server.socket.close()


