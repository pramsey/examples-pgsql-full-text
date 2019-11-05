# Setup and Installation

The address server requires a database connection, so set up a virtual environment and then install the `psycopg2` driver using `pip`.

    cd address-lookup-mvt
    virtualenv --python python3 venv
    source venv/bin/activate
    pip install -r requirements.txt


# Running the Server

    source venv/bin/activate
    python address-lookup.py

or

    source venv/bin/activate
    python geonames-lookup.py

and

    open geonames-lookup.html
    open address-lookup.html