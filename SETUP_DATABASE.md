# Setting up PostgreSQL for the HEXOS Streamlit app (Neon, free tier)

1. Go to neon.tech and sign up (no credit card required).
2. Create a new project. Neon gives you a connection string that looks like:
   postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require
3. In your project root, create the folder `.streamlit` if it doesn't exist,
   and inside it a file named `secrets.toml` containing exactly:

   DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"

4. CRITICAL: add this line to your .gitignore (if not already covered by
   `.streamlit/`) so the real connection string is never committed:

   .streamlit/secrets.toml

5. Install the driver:
   pip install psycopg2-binary

6. Run the app as usual:
   streamlit run app/streamlit_app.py

   The schema (two tables: scenarios, runs) is created automatically on
   first run. If DATABASE_URL is not set at all, the app still works fully --
   saving/history are simply unavailable, nothing crashes.
