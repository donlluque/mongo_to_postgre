r"""
Script principal de migración de colecciones MongoDB a PostgreSQL.

Arquitectura refactorizada con carga dinámica de migradores:
- mongomigra.py: Infraestructura genérica (conexiones, batching, progreso)
- migrators/*.py: Lógica específica por colección (implementan BaseMigrator)
- config.py: Configuración centralizada de colecciones

Flujo de ejecución:
1. Usuario selecciona colección del menú interactivo
2. Sistema carga dinámicamente el migrador correspondiente
3. Validación de dependencias (truth_source deben correr primero)
4. Iteración sobre documentos MongoDB con sesión explícita
5. Extracción via interfaz común (extract_data)
6. Inserción via interfaz común (insert_batches)

Ventajas vs versión anterior:
- Agregar nueva colección no requiere modificar este archivo
- Un solo código funciona con N colecciones
- Validación automática de migradores via interfaz
- Orden de migración garantizado por dependencias

Prerrequisitos:
- Base de datos creada (mesamongo)
- Estructura de tablas creada (ejecutar dbsetup.py primero)
- Migradores implementados en migrators/

Uso:
    python mongomigra.py

    # Seleccionar colección del menú interactivo
    # El resto es automático
"""

from pathlib import Path
import sys
import io
import importlib
import psycopg2
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from psycopg2 import OperationalError

# Asegurar que el directorio raíz esté en sys.path para imports dinámicos
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import config
from migrators.base import BaseMigrator

# Forzar UTF-8 en stdout/stderr para emojis en Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


def connect_to_mongo():
    """
    Establece conexión a MongoDB usando credenciales de config.py.

    Returns:
        tuple: (client, database) de pymongo

    Raises:
        SystemExit: Si no puede conectar
    """
    try:
        print("🔌 Conectando a MongoDB...")
        client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client[config.MONGO_DATABASE_NAME]
        print("✅ Conexión a MongoDB exitosa")
        return client, db
    except ConnectionFailure as e:
        print(f"❌ Error de conexión a MongoDB", file=sys.stderr)
        print(f"   Detalle: {e}", file=sys.stderr)
        sys.exit(1)


def connect_to_postgres():
    """
    Establece conexión a PostgreSQL usando credenciales de config.py.

    Returns:
        tuple: (conexión, cursor) de psycopg2

    Raises:
        SystemExit: Si no puede conectar
    """
    try:
        print("🔌 Conectando a PostgreSQL...")
        conn = psycopg2.connect(**config.POSTGRES_CONFIG)
        cursor = conn.cursor()
        print("✅ Conexión a PostgreSQL exitosa")
        return conn, cursor
    except OperationalError as e:
        print(f"❌ Error de conexión a PostgreSQL", file=sys.stderr)
        print(f"   Detalle: {e}", file=sys.stderr)
        sys.exit(1)


def load_migrator_for_collection(collection_name):
    """
    Carga dinámicamente el migrador correspondiente a una colección.

    Convención de nombres:
        lml_processes_mesa4core → migrators.lml_processes → LmlProcessesMigrator
        lml_users_mesa4core → migrators.lml_users → LmlUsersMigrator

    El sistema:
    1. Extrae nombre base (lml_processes_mesa4core → lml_processes)
    2. Construye nombre de clase en PascalCase (lml_processes → LmlProcessesMigrator)
    3. Importa módulo dinámicamente
    4. Instancia clase con schema de config

    Args:
        collection_name: Nombre completo de la colección en MongoDB

    Returns:
        BaseMigrator: Instancia del migrador específico

    Raises:
        SystemExit: Si no existe el módulo o la clase

    Example:
        >>> migrator = load_migrator_for_collection('lml_processes_mesa4core')
        >>> type(migrator).__name__
        'LmlProcessesMigrator'
    """
    # Extraer nombre base
    base_name = collection_name.replace("_mesa4core", "")

    # Construir nombre de clase: lml_processes → LmlProcessesMigrator
    # Split por '_', capitalizar cada palabra, concatenar
    class_name = (
        "".join(word.capitalize() for word in base_name.split("_")) + "Migrator"
    )

    try:
        # Importar módulo dinámicamente
        module = importlib.import_module(f"migrators.{base_name}")

        # Obtener clase del módulo
        migrator_class = getattr(module, class_name)

        # Verificar que hereda de BaseMigrator (type safety en runtime)
        if not issubclass(migrator_class, BaseMigrator):
            print(f"❌ {class_name} no hereda de BaseMigrator", file=sys.stderr)
            sys.exit(1)

        # Obtener schema de config
        collection_config = config.get_collection_config(collection_name)
        schema = collection_config["postgres_schema"]

        # Instanciar
        return migrator_class(schema=schema)

    except ModuleNotFoundError:
        print(f"❌ No existe migrador para '{collection_name}'", file=sys.stderr)
        print(f"   Se esperaba: migrators/{base_name}.py", file=sys.stderr)
        sys.exit(1)
    except AttributeError:
        print(
            f"❌ El módulo migrators.{base_name} no tiene la clase '{class_name}'",
            file=sys.stderr,
        )
        sys.exit(1)


def select_collection():
    """
    Muestra menú interactivo para seleccionar colección a migrar.

    Lee colecciones de config.MIGRATION_ORDER (respeta dependencias) y presenta:
    - Nombre completo de la colección
    - Descripción (si existe)
    - Schema destino
    - Tipo (truth_source vs consumer)
    - Dependencias (si tiene)

    Returns:
        str: Nombre de la colección seleccionada

    Raises:
        SystemExit: Si no hay colecciones configuradas o usuario cancela
    """
    # Usar MIGRATION_ORDER en vez de COLLECTIONS.keys() para respetar dependencias
    available = config.MIGRATION_ORDER

    if not available:
        print("❌ No hay colecciones configuradas en config.MIGRATION_ORDER")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("📚 COLECCIONES DISPONIBLES (orden de migración recomendado)")
    print("=" * 70)

    for i, coll_name in enumerate(available, 1):
        coll_config = config.get_collection_config(coll_name)
        desc = coll_config.get("description", "Sin descripción")
        schema = coll_config["postgres_schema"]
        coll_type = coll_config.get("collection_type", "unknown")
        depends_on = coll_config.get("depends_on", [])

        print(f"\n{i}. {coll_name}")
        print(f"   └─ {desc}")
        print(f"   └─ Schema: {schema} | Tipo: {coll_type}")
        if depends_on:
            print(f"   └─ Requiere: {', '.join(depends_on)}")

    print("\n" + "=" * 70)

    # Loop hasta obtener selección válida
    while True:
        try:
            choice = input(
                "Seleccione el número de colección a migrar (0 para salir): "
            ).strip()

            if choice == "0":
                print("\n👋 Migración cancelada por usuario")
                sys.exit(0)

            idx = int(choice) - 1

            if 0 <= idx < len(available):
                return available[idx]
            else:
                print("❌ Número fuera de rango. Intente nuevamente.")
        except ValueError:
            print("❌ Entrada inválida. Ingrese un número.")
        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 Migración cancelada por usuario")
            sys.exit(0)


def validate_dependencies(collection_name, pg_cursor):
    """
    Valida que las dependencias de una colección ya hayan sido migradas.

    Verifica que los schemas de las colecciones requeridas tengan datos
    en su tabla main.

    Args:
        collection_name: Nombre de la colección a validar
        pg_cursor: Cursor de psycopg2

    Returns:
        bool: True si puede proceder, False si faltan dependencias
    """
    deps = config.validate_migration_order(collection_name)

    if not deps:
        return True  # Sin dependencias, puede proceder

    print(f"\n🔍 Validando dependencias de '{collection_name}'...")

    missing = []
    for dep in deps:
        dep_config = config.get_collection_config(dep)
        dep_schema = dep_config["postgres_schema"]

        try:
            pg_cursor.execute(f"SELECT COUNT(*) FROM {dep_schema}.main")
            count = pg_cursor.fetchone()[0]

            if count == 0:
                missing.append(dep)
                print(f"   ❌ {dep}: tabla vacía ({dep_schema}.main)")
            else:
                print(f"   ✅ {dep}: {count:,} registros en {dep_schema}.main")
        except Exception as e:
            missing.append(dep)
            print(f"   ❌ {dep}: error al verificar ({e})")

    if missing:
        print(f"\n⚠️  ADVERTENCIA: Faltan dependencias: {', '.join(missing)}")
        print(f"   Recomendación: Migrar primero las colecciones requeridas")

        response = input("\n¿Continuar de todas formas? (s/n): ").strip().lower()
        return response == "s"

    print("   ✅ Todas las dependencias satisfechas")
    return True


def migrate_collection(mongo_client, mongo_db, pg_cursor, pg_conn, collection_name):
    """
    Orquesta la migración de una colección específica usando carga dinámica.

    Esta función es completamente genérica: funciona con cualquier colección
    que tenga un migrador implementando BaseMigrator.

    Flujo:
    1. Validar dependencias
    2. Cargar migrador específico (carga dinámica)
    3. Limpiar datos existentes (full refresh)
    4. Iterar sobre documentos con sesión explícita
    5. Extraer datos usando interfaz común (extract_data)
    6. Acumular en batches
    7. Insertar periódicamente (insert_batches)
    8. Commit cada batch_size documentos

    Args:
        mongo_client: Cliente de MongoDB (para sesiones)
        mongo_db: Base de datos de pymongo
        pg_cursor: Cursor de psycopg2
        pg_conn: Conexión de psycopg2
        collection_name: Nombre de la colección a migrar

    Raises:
        SystemExit: Si la colección no está configurada o faltan dependencias críticas
    """
    print(f"\n🚚 Iniciando migración de colección '{collection_name}'...")

    # Validar configuración
    collection_config = config.get_collection_config(collection_name)

    # ========================================================================
    # PASO 1: VALIDAR DEPENDENCIAS
    # ========================================================================

    if not validate_dependencies(collection_name, pg_cursor):
        print("\n❌ Migración cancelada: dependencias no satisfechas")
        sys.exit(1)

    # ========================================================================
    # PASO 2: CARGAR MIGRADOR DINÁMICAMENTE
    # ========================================================================

    print(f"\n   📦 Cargando migrador...")
    migrator = load_migrator_for_collection(collection_name)
    print(f"   ✅ Migrador cargado: {type(migrator).__name__}")

    # ========================================================================
    # PASO 3: FULL REFRESH (limpiar datos existentes)
    # ========================================================================

    print(
        f"\n   🗑️  Limpiando datos existentes en '{collection_config['postgres_schema']}'..."
    )
    try:
        pg_cursor.execute(
            f"TRUNCATE TABLE {collection_config['postgres_schema']}.main CASCADE"
        )
        pg_conn.commit()
        print(f"   ✅ Tablas limpiadas")
    except Exception as e:
        print(f"   ⚠️  No se pudo limpiar (puede ser primera ejecución): {e}")

    # ========================================================================
    # PASO 4: OBTENER COLECCIÓN DE MONGODB
    # ========================================================================

    source_collection = mongo_db[collection_name]
    batch_size = config.BATCH_SIZE

    total_docs = source_collection.count_documents({})
    if total_docs == 0:
        print(f"⚠️  Advertencia: No se encontraron documentos en '{collection_name}'")
        return

    print(f"\n   📊 Total de documentos: {total_docs:,}")
    print(f"   📦 Tamaño de batch: {batch_size}")
    print(f"   🎯 Schema destino: {collection_config['postgres_schema']}")
    print(f"   🏷️  Tipo: {collection_config.get('collection_type', 'unknown')}")

    # ========================================================================
    # PASO 5: INICIALIZAR ESTRUCTURAS
    # ========================================================================

    # Batches usando la interfaz del migrador
    batches = migrator.initialize_batches()

    # Caches vacío (ya no se usa, pero mantenemos por compatibilidad de interfaz)
    caches = {}

    # ========================================================================
    # PASO 6: ITERAR SOBRE DOCUMENTOS CON SESIÓN EXPLÍCITA
    # ========================================================================

    count = 0

    try:
        # Usar sesión explícita para prevenir timeout de cursor
        with mongo_client.start_session() as session:
            cursor = source_collection.find(no_cursor_timeout=True, session=session)

            for doc in cursor:
                count += 1

                # PASO 6.1: Extraer IDs de entidades compartidas
                # truth_source: retorna {} (no consume nada)
                # consumer: retorna {'created_by_user_id': '...', ...}
                shared_entities = migrator.extract_shared_entities(
                    doc, pg_cursor, caches
                )

                # PASO 6.2: Extraer datos específicos de la colección
                # Retorna estructura {'main': tuple, 'related': {...}}
                data = migrator.extract_data(doc, shared_entities)

                # PASO 6.3: Acumular en batches
                batches["main"].append(data["main"])
                for table_name, records in data["related"].items():
                    batches["related"][table_name].extend(records)

                # Progreso en la misma línea
                if count % 100 == 0 or count % batch_size == 0:
                    # \033[K limpia la línea para evitar basura visual o saltos indeseados
                    print(
                        f"\r\033[K⏳ Procesados: {count:,}/{total_docs:,} ({count*100//total_docs}%)",
                        end="",
                        flush=True,
                    )

                # PASO 6.4: Insertar y commit cada batch_size documentos
                if count % batch_size == 0:
                    migrator.insert_batches(batches, pg_cursor, caches)
                    pg_conn.commit()

                    # Limpiar batches para el próximo ciclo
                    batches = migrator.initialize_batches()

        # ========================================================================
        # PASO 7: INSERTAR REGISTROS FINALES
        # ========================================================================

        print("\n   💾 Insertando registros finales...")
        if batches["main"]:  # Solo insertar si hay datos residuales
            migrator.insert_batches(batches, pg_cursor, caches)
            pg_conn.commit()

        print(f"\n✅ Migración completada: {count:,} documentos procesados")

    except Exception as e:
        print(f"\n❌ Error durante iteración: {e}")
        raise


def main():
    """
    Función principal que coordina el flujo completo de migración.

    Secuencia:
    1. Mostrar banner
    2. Conectar a ambas bases de datos
    3. Selección interactiva de colección
    4. Ejecutar migración
    5. Cerrar conexiones limpiamente

    Exit Codes:
        0: Éxito
        1: Error de conexión o migración
    """
    print("=" * 70)
    print("🚀 SISTEMA DE MIGRACIÓN MONGODB → POSTGRESQL")
    print("=" * 70)
    print(f"📍 MongoDB: {config.MONGO_DATABASE_NAME}")
    print(f"📍 PostgreSQL: {config.POSTGRES_CONFIG['dbname']}")

    # Selección interactiva de colección
    collection_name = select_collection()

    print("\n" + "=" * 70)
    print(f"📦 Colección seleccionada: {collection_name}")
    print("=" * 70)

    # Conectar a bases de datos
    mongo_client, mongo_db = connect_to_mongo()
    pg_conn, pg_cursor = connect_to_postgres()

    try:
        # Ejecutar migración
        migrate_collection(mongo_client, mongo_db, pg_cursor, pg_conn, collection_name)

        print("\n" + "=" * 70)
        print("✅ PROCESO COMPLETADO EXITOSAMENTE")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Error durante la migración: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        pg_conn.rollback()
        sys.exit(1)

    finally:
        print("\n🔒 Cerrando conexiones...")
        pg_cursor.close()
        pg_conn.close()
        mongo_client.close()
        print("✅ Conexiones cerradas correctamente")


if __name__ == "__main__":
    main()
