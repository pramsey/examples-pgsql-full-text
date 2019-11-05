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
PORT = 8080


########################################################################

class AutocompleteRequestHandler(http.server.BaseHTTPRequestHandler):

    DATABASE_CONNECTION = None

    # Generate a SQL query to pull parcels of interest     
    def generateSql(self, partialstr):
        if not partialstr:
            return None
        sql_tmpl = """
            WITH 
            rows AS (
                SELECT
                  gid,
                  initcap(concat_ws(', ', concat_ws(' ', 
                    house, street_prefix, street_name, street_type), city)) AS value,
                  ts_rank_cd(ts, query) AS rank,
                  geom
                FROM parcels,
                     to_tsquery_partial('{}') AS query
                WHERE ts @@ query
                ORDER BY rank DESC, house::integer
                LIMIT 15
            )
            SELECT json_agg(row_to_json(rows.*))::text FROM rows
        """
        return sql_tmpl.format(partialstr)


    # Run query SQL and return error on failure conditions
    def executeSql(self, sql):
        # Make and hold connection to database
        if not self.DATABASE_CONNECTION:
            try:
                self.DATABASE_CONNECTION = psycopg2.connect(**DATABASE)
            except (Exception, psycopg2.Error) as error:
                self.send_error(500, "cannot connect: %s" % (str(DATABASE)))
                return None

        # Query for MVT
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
        q = query_components["term"][0]

        if not q:
            self.send_error(400, "invalid query: %s" % (str(query_components)))
            return

        # self.log_message("term: %s" % (q))        
        sql = self.generateSql(q)
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

with http.server.HTTPServer((HOST, PORT), AutocompleteRequestHandler) as server:
    try:
        print("serving at port", PORT)
        server.serve_forever()
    except KeyboardInterrupt:
        if self.DATABASE_CONNECTION:
            self.DATABASE_CONNECTION.close()
        print('^C received, shutting down server')
        server.socket.close()


