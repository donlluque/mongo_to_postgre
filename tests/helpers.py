"""
Funciones helper compartidas para todos los tests.

Proporciona carga dinámica de migradores basándose en config.py,
evitando imports hardcodeados y facilitando agregar nuevas colecciones.
"""

import sys
import os
import importlib

# Agregar directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


def get_migrator_class_for_collection(collection_name):
    """
    Carga dinámicamente la clase migrador para una colección.

    Sigue la convención de nombres:
    - lml_people_mesa4core → LmlPeopleMigrator (en migrators/lml_people.py)
    - lml_users_mesa4core → LmlUsersMigrator (en migrators/lml_users.py)

    Args:
        collection_name: Nombre completo de la colección (ej: 'lml_people_mesa4core')

    Returns:
        class: Clase del migrador

    Raises:
        ImportError: Si no existe el módulo
        AttributeError: Si no existe la clase
    """
    # Obtener el schema PostgreSQL (ej: 'lml_people')
    cfg = config.get_collection_config(collection_name)
    schema = cfg["postgres_schema"]

    # Construir nombre del módulo (ej: 'migrators.lml_people')
    module_name = f"migrators.{schema}"

    # Construir nombre de la clase (ej: 'LmlPeopleMigrator')
    # lml_people → LmlPeopleMigrator
    class_name = "".join(word.capitalize() for word in schema.split("_")) + "Migrator"

    # Cargar módulo dinámicamente
    module = importlib.import_module(module_name)

    # Obtener clase del módulo
    migrator_class = getattr(module, class_name)

    return migrator_class


def get_all_migrator_classes():
    """
    Retorna lista de tuplas (nombre_clase, clase) para todos los migradores configurados.

    Lee dinámicamente desde config.MIGRATION_ORDER para garantizar que solo
    se incluyen migradores que están listos para migrar.

    Returns:
        list: Lista de tuplas (str, class)
            [
                ('LmlUsersMigrator', LmlUsersMigrator),
                ('LmlPeopleMigrator', LmlPeopleMigrator),
                ...
            ]
    """
    migradores = []

    for collection_name in config.MIGRATION_ORDER:
        try:
            migrator_class = get_migrator_class_for_collection(collection_name)
            class_name = migrator_class.__name__
            migradores.append((class_name, migrator_class))
        except (ImportError, AttributeError) as e:
            # Si falla la carga, registrar el error pero continuar
            # (permite que tests fallen individualmente sin romper todo)
            print(f"⚠️  No se pudo cargar migrador para {collection_name}: {e}")
            continue

    return migradores


def get_all_migrator_instances():
    """
    Retorna lista de tuplas (nombre_clase, instancia) para todos los migradores.

    Instancia cada migrador con su schema correspondiente.

    Returns:
        list: Lista de tuplas (str, BaseMigrator)
            [
                ('LmlUsersMigrator', LmlUsersMigrator('lml_users')),
                ('LmlPeopleMigrator', LmlPeopleMigrator('lml_people')),
                ...
            ]
    """
    instances = []

    for collection_name in config.MIGRATION_ORDER:
        try:
            migrator_class = get_migrator_class_for_collection(collection_name)
            cfg = config.get_collection_config(collection_name)
            schema = cfg["postgres_schema"]

            # Instanciar con el schema correspondiente
            migrator_instance = migrator_class(schema)
            class_name = migrator_class.__name__

            instances.append((class_name, migrator_instance))
        except (ImportError, AttributeError) as e:
            print(f"⚠️  No se pudo instanciar migrador para {collection_name}: {e}")
            continue

    return instances


def get_all_collections():
    """Retorna lista de todas las colecciones configuradas."""
    return list(config.COLLECTIONS.keys())


def get_truth_source_collections():
    """Retorna solo colecciones truth_source."""
    return [
        name
        for name, cfg in config.COLLECTIONS.items()
        if cfg.get("collection_type") == "truth_source"
    ]


def get_consumer_collections():
    """Retorna solo colecciones consumer."""
    return [
        name
        for name, cfg in config.COLLECTIONS.items()
        if cfg.get("collection_type") == "consumer"
    ]
