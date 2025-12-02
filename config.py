"""
Configuración centralizada para el sistema de migración MongoDB → PostgreSQL.

Este módulo define:
- Credenciales y URIs de conexión (desde variables de entorno)
- Mapeo de nombres de tablas compartidas
- Configuración específica por colección (arquitectura multi-colección)

Estructura:
- Schema 'public': Entidades compartidas entre colecciones (users, customers, etc.)
- Schemas específicos: Un schema por cada colección MongoDB migrada

Uso:
    import config
    
    # Obtener configuración de una colección
    coleccion_config = config.COLLECTIONS["lml_processes_mesa4core"]
    schema_destino = coleccion_config["postgres_schema"]
"""

import os
from dotenv import load_dotenv

# Carga las variables del archivo .env en las variables de entorno del sistema
load_dotenv(override=True)

# --- Configuración de MongoDB (Origen) ---
MONGO_URI = (
    f"mongodb://{os.getenv('MONGO_USER')}:{os.getenv('MONGO_PASSWORD')}"
    f"@{os.getenv('MONGO_HOST')}:{os.getenv('MONGO_PORT')}/"
    f"?authSource={os.getenv('MONGO_AUTH_SOURCE')}&readPreference=primary"
    f"&directConnection=true&ssl=false"
)
MONGO_DATABASE_NAME = "mesa4core"

# --- Configuración de PostgreSQL (Destino) ---
POSTGRES_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB'),
    'user': os.getenv('POSTGRES_USER'),
    'password': os.getenv('POSTGRES_PASSWORD'),
    'host': os.getenv('POSTGRES_HOST'),
    'port': os.getenv('POSTGRES_PORT')
}

# --- Nombres de Tablas Compartidas ---
# Mapeo consistente de entidades que viven en schema 'public'
# y son referenciadas por múltiples colecciones vía FKs
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

# --- Configuración de Migración ---
BATCH_SIZE = 2000  # Número de registros a insertar por lote (balance entre memoria y velocidad)

# --- Configuración Multi-Colección ---
# Cada colección MongoDB define:
# - postgres_schema: Nombre del schema destino en PostgreSQL
# - primary_key: Nombre semántico de la clave primaria (ej: process_id, list_id)
# - shared_entities: Lista de tablas en 'public' que esta colección referencia
COLLECTIONS = {
    "lml_processes_mesa4core": {
        "postgres_schema": "lml_processes",
        "primary_key": "process_id",
        "shared_entities": ["users", "customers", "areas", "subareas", "roles", "groups"],
        "description": "Procesos de negocio y trámites"
    },
    "lml_listbuilder_mesa4core": {
        "postgres_schema": "lml_listbuilder",
        "primary_key": "listbuilder_id",
        "shared_entities": ["users", "customers", "areas", "subareas", "roles", "groups"],  # ← Agregar groups
        "description": "Configuraciones de listados y pantallas UI"
    },
    "lml_formbuilder_mesa4core": {
        "postgres_schema": "lml_formbuilder",
        "primary_key": "formbuilder_id",
        "shared_entities": ["users", "customers", "areas", "subareas", "roles", "groups"],  # ← Completo
        "description": "Configuraciones de formularios dinámicos UI"
    }
}