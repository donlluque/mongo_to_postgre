import os
from dotenv import load_dotenv

# Carga las variables del archivo .env en las variables de entorno del sistema
load_dotenv(override=True)

# --- Configuración de MongoDB (Origen) ---
# Lee las credenciales del entorno y construye la URI de conexión.
MONGO_URI = (
    f"mongodb://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASSWORD')}"
    f"@{os.getenv('MONGO_HOST')}:{os.getenv('MONGO_PORT')}/"
    f"?authSource={os.getenv('MONGO_AUTH_SOURCE')}&readPreference=primary"
    f"&directConnection=true&ssl=false"
)
MONGO_DATABASE_NAME = "mesa4core" # Nombre de la BBDD de origen
MONGO_SOURCE_COLLECTION = "lml_processes_mesa4core" # Nombre de la coleccion a migrar

# --- Configuración de PostgreSQL (Destino) ---
# Lee las credenciales del entorno y las organiza en un diccionario.
POSTGRES_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB'),
    'user': os.getenv('POSTGRES_USER'),
    'password': os.getenv('POSTGRES_PASSWORD'),
    'host': os.getenv('POSTGRES_HOST'),
    'port': os.getenv('POSTGRES_PORT')
}

# --- Mapeo de Tablas de Destino ---
TABLE_NAMES = {
    "main": "main",
    "users": "users",
    "areas": "areas",
    "subareas": "subareas",
    "roles": "roles",
    "groups": "groups",
    "user_groups": "user_groups",
    "movements": "movements",
    "customers": "customers"
}

# Nombre del schema para las tablas específicas de la colección del POC
POC_SCHEMA_NAME = "lml_processes"
BATCH_SIZE = 500 # Número de registros a insertar por lote