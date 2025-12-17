"""
Configuración centralizada para el sistema de migración MongoDB → PostgreSQL.

ARQUITECTURA (Actualizado 2025-12-05):
Modelo de schemas autónomos por colección con prefijo lml_:
- lml_users: Fuente de verdad de usuarios y catálogos embebidos
- lml_usersgroups: Fuente de verdad de grupos y membresías
- lml_processes, lml_listbuilder, lml_formbuilder: Schemas consumidores

FLUJO DE MIGRACIÓN:
1. Ejecutar migradores en orden de MIGRATION_ORDER
2. Los truth_source NO consumen de nadie (extract_shared_entities vacío)
3. Los consumer solo extraen IDs, NO insertan en schemas de verdad

USO DE LAS FUNCIONES HELPER:
    # Obtener configuración de colección
    config = get_collection_config('lml_users_mesa4core')
    schema = config['postgres_schema']  # 'lml_users'

    # Validar dependencias antes de migrar
    deps = validate_migration_order('lml_processes_mesa4core')
    if deps:
        print(f"Primero migrar: {deps}")

    # Verificar si colección es fuente de verdad
    if is_truth_source('lml_users_mesa4core'):
        # Lógica específica para truth_source
        pass
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
    "dbname": os.getenv("POSTGRES_DB") or "",
    "user": os.getenv("POSTGRES_USER") or "",
    "password": os.getenv("POSTGRES_PASSWORD") or "",
    "host": os.getenv("POSTGRES_HOST") or "localhost",
    "port": os.getenv("POSTGRES_PORT") or "5432",
}

# --- Configuración de Migración ---
BATCH_SIZE = 2000  # Número de registros a insertar por lote

# --- Configuración Multi-Colección ---
# Cada colección MongoDB define:
# - postgres_schema: Nombre del schema destino en PostgreSQL
# - primary_key: Nombre de la columna PK en la tabla main del schema
# - collection_type: 'truth_source' (fuente de verdad) o 'consumer' (consumidor)
# - depends_on: Lista de colecciones que DEBEN migrarse antes (por FKs)
# - description: Descripción de negocio de la colección

COLLECTIONS = {
    # === FUENTES DE VERDAD (sin dependencias) ===
    "lml_users_mesa4core": {
        "postgres_schema": "lml_users",
        "primary_key": "id",
        "collection_type": "truth_source",
        "depends_on": [],
        "description": "Usuarios del sistema y catálogos embebidos (roles, areas, subareas, positions, signaturetypes)",
    },
    "lml_usersgroups_mesa4core": {
        "postgres_schema": "lml_usersgroups",
        "primary_key": "id",
        "collection_type": "truth_source",
        "depends_on": ["lml_users_mesa4core"],  # members.user_id → lml_users.main.id
        "description": "Grupos de usuarios y relación N:M con usuarios",
    },
    # === COLECCIONES CONSUMIDORAS (referencian fuentes de verdad) ===
    "lml_processes_mesa4core": {
        "postgres_schema": "lml_processes",
        "primary_key": "process_id",
        "collection_type": "consumer",
        "depends_on": ["lml_users_mesa4core", "lml_processtypes_mesa4core"],
        "description": "Procesos de negocio y trámites",
    },
    "lml_listbuilder_mesa4core": {
        "postgres_schema": "lml_listbuilder",
        "primary_key": "listbuilder_id",
        "collection_type": "consumer",
        "depends_on": ["lml_users_mesa4core"],
        "description": "Configuraciones de listados y pantallas UI",
    },
    "lml_formbuilder_mesa4core": {
        "postgres_schema": "lml_formbuilder",
        "primary_key": "formbuilder_id",
        "collection_type": "consumer",
        "depends_on": ["lml_users_mesa4core"],
        "description": "Configuraciones de formularios dinámicos UI",
    },
    "lml_processtypes_mesa4core": {
        "postgres_schema": "lml_processtypes",
        "primary_key": "processtype_id",
        "collection_type": "consumer",
        "depends_on": [
            "lml_users_mesa4core",
            "lml_listbuilder_mesa4core",
            "lml_formbuilder_mesa4core",
        ],
        "description": "Tipos de trámites/procesos y su configuración (formularios, permisos, flujos)",
    },
    "lml_people_mesa4core": {
        "postgres_schema": "lml_people",
        "primary_key": "people_id",
        "collection_type": "consumer",
        "depends_on": ["lml_users_mesa4core"],
        "description": "Registro de personas físicas y jurídicas con datos específicos por tipo",
    },
}

# --- Orden de Migración ---
# Derivado de las dependencias declaradas en COLLECTIONS.
# Ejecutar migradores en este orden garantiza que las FKs sean válidas.
MIGRATION_ORDER = [
    "lml_users_mesa4core",  # Sin dependencias
    "lml_usersgroups_mesa4core",  # Depende de users
    "lml_processes_mesa4core",  # Depende de users
    "lml_listbuilder_mesa4core",  # Depende de users
    "lml_formbuilder_mesa4core",  # Depende de users
    "lml_processtypes_mesa4core",  # Depende de users, listbuilder, formbuilder
    "lml_people_mesa4core",  # Depende de users
]

# --- Schemas Fuente de Verdad ---
# Lista de schemas PostgreSQL que son fuentes de verdad.
SOURCE_OF_TRUTH_SCHEMAS = ["lml_users", "lml_usersgroups"]


# --- Funciones Helper ---


def get_collection_config(collection_name: str) -> dict:
    """
    Obtiene la configuración de una colección por nombre.

    Args:
        collection_name: Nombre de la colección MongoDB (ej: 'lml_users_mesa4core')

    Returns:
        dict: Configuración de la colección con keys:
              - postgres_schema: Nombre del schema PostgreSQL
              - primary_key: Nombre de columna PK
              - collection_type: 'truth_source' o 'consumer'
              - depends_on: Lista de colecciones requeridas
              - description: Descripción de negocio

    Raises:
        KeyError: Si la colección no está configurada

    Ejemplo:
        >>> config = get_collection_config('lml_users_mesa4core')
        >>> print(config['postgres_schema'])
        'lml_users'
        >>> print(config['collection_type'])
        'truth_source'
    """
    if collection_name not in COLLECTIONS:
        available = ", ".join(COLLECTIONS.keys())
        raise KeyError(
            f"Colección '{collection_name}' no está configurada.\n"
            f"Colecciones disponibles: {available}"
        )
    return COLLECTIONS[collection_name]


def validate_migration_order(collection_name: str) -> list:
    """
    Valida que las dependencias de una colección estén satisfechas.

    Args:
        collection_name: Nombre de la colección a validar

    Returns:
        list: Lista de colecciones que deben migrarse antes.
              Lista vacía si no hay dependencias.

    Uso típico antes de migrar:
        deps = validate_migration_order('lml_processes_mesa4core')
        if deps:
            raise Exception(f"Primero migrar: {deps}")

    Ejemplo:
        >>> deps = validate_migration_order('lml_processes_mesa4core')
        >>> print(deps)
        ['lml_users_mesa4core']

        >>> deps = validate_migration_order('lml_users_mesa4core')
        >>> print(deps)
        []
    """
    config = get_collection_config(collection_name)
    return config.get("depends_on", [])


def is_truth_source(collection_name: str) -> bool:
    """
    Verifica si una colección es fuente de verdad.

    Los migradores de fuentes de verdad tienen comportamiento diferente:
    - NO consumen datos de otros schemas
    - Su extract_shared_entities() retorna dict vacío
    - Son los primeros en el orden de migración
    - Insertan datos directamente en sus propias tablas

    Los migradores consumer:
    - Extraen IDs de entidades existentes
    - NO insertan en schemas de verdad
    - Dependen de que truth_sources ya hayan corrido

    Args:
        collection_name: Nombre de la colección

    Returns:
        bool: True si es fuente de verdad, False si es consumer

    Ejemplo:
        >>> is_truth_source('lml_users_mesa4core')
        True
        >>> is_truth_source('lml_processes_mesa4core')
        False
    """
    config = get_collection_config(collection_name)
    return config.get("collection_type") == "truth_source"


def get_schema_for_collection(collection_name: str) -> str:
    """
    Obtiene el nombre del schema PostgreSQL para una colección.

    Helper de conveniencia para acceso directo al schema.

    Args:
        collection_name: Nombre de la colección MongoDB

    Returns:
        str: Nombre del schema PostgreSQL

    Ejemplo:
        >>> get_schema_for_collection('lml_users_mesa4core')
        'lml_users'
    """
    config = get_collection_config(collection_name)
    return config["postgres_schema"]
